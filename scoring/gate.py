"""Quality gate pipeline v2 (M3).

Runs a workflow version on the full test suite (gate_config: 20 prompts x 5
seeds = 100 generations), scores every image, aggregates per-metric statistics,
compares against the stored champion **with bootstrapped confidence intervals**,
applies per-metric rules (defect rate, speed, cost), and decides PASS/BLOCK.
Results go to MLflow and Prometheus (pushgateway).

Usage:
  python gate.py <workflow_id> [version]                 # run + compare vs champion
  python gate.py <workflow_id> [version] --seed-champion # set new baseline
  python gate.py <workflow_id> [version] --promote       # PASS + champion upgrade

Env:
  COMFYOPS_GATEWAY          gateway base URL (default http://127.0.0.1:8000)
  COMFYOPS_GATE_PROMPTS     int override for quick dev (e.g. 3)
  COMFYOPS_GATE_SEEDS       int override (e.g. 2)
  COMFYOPS_PUSHGATEWAY      pushgateway URL for metrics (default http://127.0.0.1:9091)
  COMFYOPS_MOCK_SCORE=1     deterministic synthetic scores (no models, no worker)

Champion state: .gate_state/<workflow_id>.json
"""

import argparse
import json
import os
import statistics
import sys
import time
import urllib.request
from pathlib import Path

import mlflow

from gate_config import (
    BOOTSTRAP_ITERATIONS,
    CI_LEVEL,
    COST_PER_SECOND,
    DEFECT_AESTHETIC_BELOW,
    DEFECT_CLIP_BELOW,
    PROMPTS,
    RULES,
    SEEDS,
)

sys.path.insert(0, str(Path(__file__).parent))
from app.score import MOCK as app_score_mock  # noqa: E402
from app.score import score_image  # noqa: E402

GATEWAY = os.getenv("COMFYOPS_GATEWAY", "http://127.0.0.1:8000")
PUSHGATEWAY = os.getenv("COMFYOPS_PUSHGATEWAY", "http://127.0.0.1:9091")
STATE_DIR = Path(__file__).parent / ".gate_state"
POLL_SECONDS = 15
TIMEOUT_SECONDS = 3600

N_PROMPTS = int(os.getenv("COMFYOPS_GATE_PROMPTS", len(PROMPTS)))
N_SEEDS = int(os.getenv("COMFYOPS_GATE_SEEDS", len(SEEDS)))


def _post(url: str, body: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def enqueue(workflow_id: str, version: str | None, prompt: str, seed: int) -> str:
    return _post(f"{GATEWAY}/generate", {"workflow_id": workflow_id, "version": version, "prompt": prompt, "seed": seed})["job_id"]


def wait_result(job_id: str) -> dict:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        job = _get(f"{GATEWAY}/jobs/{job_id}")
        if job["status"] == "done":
            return job
        if job["status"] == "failed":
            raise RuntimeError(f"job {job_id} failed")
        time.sleep(POLL_SECONDS)
    raise TimeoutError(f"job {job_id} timed out")


def fetch_image(url: str, dest: Path) -> Path:
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


def run_suite(workflow_id: str, version: str | None) -> list[dict]:
    """Batch-enqueue every (prompt, seed), then collect as jobs finish."""
    jobs = [(p, s, enqueue(workflow_id, version, p, s)) for p in PROMPTS[:N_PROMPTS] for s in SEEDS[:N_SEEDS]]
    results = []
    for prompt, seed, job_id in jobs:
        job = wait_result(job_id)
        img_path = fetch_image(job["image_url"], Path("/tmp") / f"{job_id}.png")
        scores = score_image(str(img_path), prompt, version)
        scores.update(
            {
                "prompt": prompt,
                "seed": seed,
                "job_id": job_id,
                "gen_time": scores.get("gen_time") if app_score_mock else (job.get("generation_time") or 0.0),
            }
        )
        results.append(scores)
        print(
            f"  [{prompt[:40]}] clip={scores['clip_score']:.3f} "
            f"aesthetic={scores['aesthetic_score']:.3f} gen={scores['gen_time']:.0f}s",
            flush=True,
        )
    return results


# ---------------------------------------------------------------- metrics --

def is_defect(scores: dict) -> bool:
    return scores["clip_score"] < DEFECT_CLIP_BELOW or scores["aesthetic_score"] < DEFECT_AESTHETIC_BELOW


def aggregate(results: list[dict]) -> dict:
    clips = [r["clip_score"] for r in results]
    aest = [r["aesthetic_score"] for r in results]
    gens = [r["gen_time"] for r in results]
    n = len(results)
    return {
        "clip_mean": round(statistics.mean(clips), 4),
        "clip_std": round(statistics.stdev(clips), 4) if n > 1 else 0.0,
        "aesthetic_mean": round(statistics.mean(aest), 4),
        "aesthetic_std": round(statistics.stdev(aest), 4) if n > 1 else 0.0,
        "defect_rate": round(sum(is_defect(r) for r in results) / n, 4),
        "gen_time_mean": round(statistics.mean(gens), 1),
        "gen_time_p95": round(sorted(gens)[int(n * 0.95) - 1], 1) if n else 0.0,
        "cost_per_image": round(statistics.mean(gens) * COST_PER_SECOND, 6),
        "n": n,
    }


def paired_bootstrap_ci(challenger: list[dict], champion: list[dict], metric: str) -> tuple[float, float]:
    """95% CI for the mean difference (challenger - champion), paired by
    (prompt, seed), resampled with replacement. Pure Python (no scipy)."""
    import random

    rng = random.Random(1337)
    diffs = [c[metric] - b[metric] for c, b in zip(challenger, champion)]
    n = len(diffs)
    if n == 0:
        return 0.0, 0.0
    means = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    tail = int(CI_LEVEL * BOOTSTRAP_ITERATIONS / 2)
    return round(means[tail], 4), round(means[BOOTSTRAP_ITERATIONS - 1 - tail], 4)


def _champion_rows(champion_agg: dict, n: int, metric: str) -> list[dict]:
    """Reference rows for the paired bootstrap.

    New champion state files carry per-image rows (["rows"]); M2 files only
    have aggregates, so synthesize paired rows from mean/std instead.
    """
    rows = champion_agg.get("rows")
    if rows:
        return rows[:n]
    import random

    rng = random.Random(42)
    mean = champion_agg.get(f"{metric}_mean", 0.0)
    std = champion_agg.get(f"{metric}_std", 0.0)
    return [{metric: mean + rng.gauss(0, std)} for _ in range(n)]


def gate_decision(challenger: list[dict], champion_agg: dict, challenger_agg: dict) -> tuple[bool, str, dict]:
    """Per-metric rules + bootstrap CIs. BLOCK if any metric is significantly
    worse than the champion (CI entirely below 0) or beyond its tolerance."""
    report = {}
    issues = []

    for metric, mean_key in (("clip_score", "clip_mean"), ("aesthetic_score", "aesthetic_mean")):
        ci_lo, ci_hi = paired_bootstrap_ci(challenger, _champion_rows(champion_agg, len(challenger), metric), metric)
        tol = RULES[metric]["tolerance"]
        drop = challenger_agg[mean_key] - champion_agg[mean_key]
        report[metric] = {"mean_diff": drop, "ci95": [ci_lo, ci_hi], "tolerance": tol}
        if ci_hi < 0:
            issues.append(f"{metric} sig. worse (CI95 {ci_lo}..{ci_hi} all < 0)")
        elif drop < -tol:
            issues.append(f"{metric} drop {drop:+.4f} beyond tolerance {tol}")

    dr = challenger_agg["defect_rate"] - champion_agg["defect_rate"]
    report["defect_rate"] = {"diff": dr, "max_abs_increase": RULES["defect_rate"]["max_abs_increase"]}
    if dr > RULES["defect_rate"]["max_abs_increase"]:
        issues.append(f"defect rate +{dr:.3f} (max +{RULES['defect_rate']['max_abs_increase']})")

    gt = challenger_agg["gen_time_mean"] / champion_agg["gen_time_mean"] - 1 if champion_agg["gen_time_mean"] else 0
    report["gen_time"] = {"ratio_increase": gt, "max_ratio_increase": RULES["gen_time"]["max_ratio_increase"]}
    if gt > RULES["gen_time"]["max_ratio_increase"]:
        issues.append(f"gen time {gt:+.1%} (max +{RULES['gen_time']['max_ratio_increase']:.0%})")

    co = challenger_agg["cost_per_image"] / champion_agg["cost_per_image"] - 1 if champion_agg["cost_per_image"] else 0
    report["cost_per_image"] = {"ratio_increase": co, "max_ratio_increase": RULES["cost_per_image"]["max_ratio_increase"]}
    if co > RULES["cost_per_image"]["max_ratio_increase"]:
        issues.append(f"cost {co:+.1%} (max +{RULES['cost_per_image']['max_ratio_increase']:.0%})")

    if issues:
        return False, "BLOCK: " + "; ".join(issues), report
    return True, "PASS", report


# ------------------------------------------------------------- champion ---

def load_champion(workflow_id: str) -> dict | None:
    p = STATE_DIR / f"{workflow_id}.json"
    if p.exists():
        return json.loads(p.read_text())
    return None


def save_champion(workflow_id: str, agg: dict, rows: list[dict] | None = None) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    state = dict(agg)
    if rows:
        state["rows"] = rows
    (STATE_DIR / f"{workflow_id}.json").write_text(json.dumps(state, indent=2))


# --------------------------------------------------------------- metrics --

def push_metrics(workflow_id: str, version: str, agg: dict, decision: str) -> None:
    """Push per-run aggregates to Prometheus pushgateway for dashboards v2."""
    import base64

    labels = f'workflow="{workflow_id}",version="{version}"'
    payload = "\n".join(
        f"comfyops_gate_metric{{{labels},metric=\"{k}\"}} {v}"
        for k, v in agg.items()
        if isinstance(v, (int, float))
    )
    payload += f'\ncomfyops_gate_verdict{{{labels}}} {"1" if decision == "PASS" else "0"}\n'
    group = base64.urlsafe_b64encode(f"{workflow_id}@{version}".encode()).decode()
    req = urllib.request.Request(
        f"{PUSHGATEWAY}/metrics/job/comfyops_gate/instance/{group}",
        data=payload.encode(),
        method="PUT",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        print("  (pushgateway unreachable, skipping metric push)", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow_id")
    ap.add_argument("version", nargs="?")
    ap.add_argument("--seed-champion", action="store_true")
    ap.add_argument("--promote", action="store_true")
    args = ap.parse_args()

    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
    mlflow.set_experiment("quality-gate")

    with mlflow.start_run(run_name=f"{args.workflow_id}@{args.version or 'latest'}"):
        mlflow.log_params({"workflow_id": args.workflow_id, "version": args.version or "latest"})
        print(f"running suite: {args.workflow_id}@{args.version or 'latest'} ({N_PROMPTS} prompts x {N_SEEDS} seeds)")
        results = run_suite(args.workflow_id, args.version)
        agg = aggregate(results)
        mlflow.log_metrics({f"mean_{k}": v for k, v in agg.items() if isinstance(v, float)})
        mlflow.log_metrics({f"per_image/{r['prompt'][:30]}_{r['seed']}": r["clip_score"] for r in results})

        champion = load_champion(args.workflow_id)
        if args.seed_champion or champion is None:
            save_champion(args.workflow_id, agg, results)
            print(f"champion seeded: {json.dumps(agg)}")
            mlflow.log_param("decision", "champion-seeded")
            push_metrics(args.workflow_id, args.version or "champion", agg, "SEEDED")
            return

        passed, reason, report = gate_decision(results, champion, agg)
        mlflow.log_param("decision", reason)
        for metric, detail in report.items():
            mlflow.log_metrics({f"gate/{metric}": v for k, v in detail.items() if isinstance(v, (int, float))})
        print(f"verdict: {reason}")
        print(f"  challenger: {json.dumps(agg)}")
        print(f"  champion:   {json.dumps(champion)}")
        print("  report:    " + json.dumps(report, indent=2))
        push_metrics(args.workflow_id, args.version or "latest", agg, reason)

        if args.promote:
            if passed:
                save_champion(args.workflow_id, agg, results)
                try:
                    _post(f"{GATEWAY}/workflows/{args.workflow_id}/promote", {"version": args.version})
                except Exception:
                    pass
                print(f"PROMOTED {args.workflow_id}@{args.version} to champion")
                mlflow.log_param("decision", "PROMOTED: " + reason)
            else:
                print("not promoted (gate failed)")


if __name__ == "__main__":
    main()