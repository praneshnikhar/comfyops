"""Quality gate pipeline v1 (M2).

Runs a workflow version on the fixed test set (gate_config), scores every
image (CLIP + aesthetic), aggregates, compares against the stored champion,
and decides PASS/BLOCK. Results go to MLflow.

Usage:
  python gate.py <workflow_id> [version]            # run + compare vs champion
  python gate.py <workflow_id> [version] --seed-champion   # set new baseline

Champion state: .gate_state/<workflow_id>.json  (later: MLflow registry).
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import mlflow

from gate_config import PROMPTS, SEEDS

sys.path.insert(0, str(Path(__file__).parent))
from app.score import score_image  # noqa: E402

GATEWAY = os.getenv("COMFYOPS_GATEWAY", "http://127.0.0.1:8000")
STATE_DIR = Path(__file__).parent / ".gate_state"
POLL_SECONDS = 15
TIMEOUT_SECONDS = 600


def enqueue(workflow_id: str, version: str | None, prompt: str, seed: int) -> str:
    body = json.dumps(
        {"workflow_id": workflow_id, "version": version, "prompt": prompt, "seed": seed}
    ).encode()
    req = urllib.request.Request(
        f"{GATEWAY}/generate", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["job_id"]


def wait_result(job_id: str) -> str:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        with urllib.request.urlopen(f"{GATEWAY}/jobs/{job_id}", timeout=30) as r:
            job = json.load(r)
        if job["status"] == "done":
            return job["image_url"]
        if job["status"] == "failed":
            raise RuntimeError(f"job {job_id} failed")
        time.sleep(POLL_SECONDS)
    raise TimeoutError(f"job {job_id} timed out")


def fetch_image(url: str, dest: Path) -> Path:
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


def run_suite(workflow_id: str, version: str | None) -> list[dict]:
    results = []
    for prompt in PROMPTS:
        for seed in SEEDS:
            job_id = enqueue(workflow_id, version, prompt, seed)
            url = wait_result(job_id)
            img_path = fetch_image(url, Path("/tmp") / f"{job_id}.png")
            scores = score_image(str(img_path), prompt)
            scores.update({"prompt": prompt, "seed": seed, "job_id": job_id})
            results.append(scores)
            print(f"  [{prompt[:40]}] clip={scores['clip_score']:.3f} "
                  f"aesthetic={scores['aesthetic_score']:.3f}", flush=True)
    return results


def aggregate(results: list[dict]) -> dict:
    import statistics

    return {
        "clip_mean": round(statistics.mean(r["clip_score"] for r in results), 4),
        "clip_std": round(statistics.stdev(r["clip_score"] for r in results), 4),
        "aesthetic_mean": round(statistics.mean(r["aesthetic_score"] for r in results), 4),
        "aesthetic_std": round(statistics.stdev(r["aesthetic_score"] for r in results), 4),
        "n": len(results),
    }


def gate_decision(challenger: dict, champion: dict) -> tuple[bool, str]:
    """PASS if challenger is not significantly worse on any metric."""
    clip_drop = challenger["clip_mean"] - champion["clip_mean"]
    aesthetic_drop = challenger["aesthetic_mean"] - champion["aesthetic_mean"]
    CLIP_TOLERANCE = 0.01    # allow 0.01 mean clip drop
    AESTHETIC_TOLERANCE = 0.10  # allow 0.1 mean aesthetic drop

    issues = []
    if clip_drop < -CLIP_TOLERANCE:
        issues.append(f"clip {clip_drop:+.4f} (tolerance {CLIP_TOLERANCE})")
    if aesthetic_drop < -AESTHETIC_TOLERANCE:
        issues.append(f"aesthetic {aesthetic_drop:+.4f} (tolerance {AESTHETIC_TOLERANCE})")
    if issues:
        return False, "BLOCK: " + ", ".join(issues)
    return True, f"PASS (clip {clip_drop:+.4f}, aesthetic {aesthetic_drop:+.4f})"


def load_champion(workflow_id: str) -> dict | None:
    p = STATE_DIR / f"{workflow_id}.json"
    if p.exists():
        return json.loads(p.read_text())
    return None


def save_champion(workflow_id: str, agg: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / f"{workflow_id}.json").write_text(json.dumps(agg, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow_id")
    ap.add_argument("version", nargs="?")
    ap.add_argument("--seed-champion", action="store_true")
    args = ap.parse_args()

    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
    exp = mlflow.set_experiment("quality-gate")

    with mlflow.start_run(run_name=f"{args.workflow_id}@{args.version or 'latest'}"):
        mlflow.log_params({"workflow_id": args.workflow_id, "version": args.version or "latest"})
        print(f"running suite: {args.workflow_id}@{args.version or 'latest'} "
              f"({len(PROMPTS)} prompts x {len(SEEDS)} seeds)")
        results = run_suite(args.workflow_id, args.version)
        agg = aggregate(results)
        mlflow.log_metrics({f"mean_{k}": v for k, v in agg.items() if isinstance(v, float)})
        for r in results:
            mlflow.log_metrics(
                {f"{r['prompt'][:30]}_clip": r["clip_score"],
                 f"{r['prompt'][:30]}_aesthetic": r["aesthetic_score"]}
            )

        champion = load_champion(args.workflow_id)
        if args.seed_champion or champion is None:
            save_champion(args.workflow_id, agg)
            print(f"champion seeded: {json.dumps(agg)}")
            mlflow.log_param("decision", "champion-seeded")
        else:
            passed, reason = gate_decision(agg, champion)
            mlflow.log_param("decision", reason)
            print(f"verdict: {reason}")
            print(f"  challenger: {json.dumps(agg)}")
            print(f"  champion:   {json.dumps(champion)}")


if __name__ == "__main__":
    main()