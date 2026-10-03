"""Breakage discovery — adversarial prompt search (M4, novel core).

Instead of only the fixed gate suite, this pipeline searches prompt-embedding
space for the clusters where a NEW workflow version fails against the
champion, and grows the permanent test suite with those adversarial prompts.

Flow:
  1. Embed a prompt history (CLIP text embeddings; deterministic pseudo-
     embeddings in mock mode) and cluster with KMeans.
  2. Run NEW + CHAMPION on each cluster's representative prompt (the member
     nearest the centroid) x a few seeds.
  3. Per-cluster paired bootstrap (same machinery as gate.py): clusters where
     the challenger is significantly worse are FAILING clusters.
  4. Mutate/template the representative prompts inside failing clusters
     (systematic variations) and merge them into the permanent suite file
     (adversarial_prompts.txt) that gate.py loads automatically.

Usage:
  python discovery.py <workflow_id> <old_version> <new_version> [--prompts N] [--seeds N]

Env: COMFYOPS_GATEWAY, COMFYOPS_MOCK_SCORE.
Report: .gate_state/discovery-<workflow_id>.json + MLflow run.
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

import mlflow

from gate import aggregate, enqueue, fetch_image, load_champion, wait_result

sys.path.insert(0, str(Path(__file__).parent))
from app.score import score_image  # noqa: E402
from app.score import MOCK  # noqa: E402
from gate_config import PROMPTS, SEEDS, RULES  # noqa: E402
from gate import paired_bootstrap_ci  # noqa: E402

GATEWAY = os.getenv("COMFYOPS_GATEWAY", "http://127.0.0.1:8000")
STATE_DIR = Path(__file__).parent / ".gate_state"
ADVERSARIAL_FILE = Path(__file__).parent / "adversarial_prompts.txt"

N_PROMPTS = int(os.getenv("COMFYOPS_DISCOVERY_PROMPTS", "24"))
N_SEEDS = int(os.getenv("COMFYOPS_DISCOVERY_SEEDS", "3"))
N_CLUSTERS = int(os.getenv("COMFYOPS_DISCOVERY_CLUSTERS", "4"))

# prompt template mutations applied inside failing clusters
MUTATIONS = [
    "{p}, ultra detailed",
    "{p}, highly realistic",
    "{p}, low quality, blurry",
    "{p}, wide angle shot",
    "{p}, at night",
    "{p}, cartoon style",
    "a close-up of {p}",
    "{p}, symmetrical composition",
]


def embed(prompt: str) -> list[float]:
    """CLIP text embedding (real) or deterministic pseudo-embedding (mock)."""
    if not MOCK:
        from app.clip_score import _load, _tokenizer, _model
        import torch

        _load()
        with torch.no_grad():
            feat = _model.encode_text(_tokenizer([prompt]))
        feat /= feat.norm(dim=-1, keepdim=True)
        return feat[0].tolist()
    import hashlib

    h = int(hashlib.sha256(prompt.encode()).hexdigest(), 16)
    vec = []
    for i in range(32):
        vec.append(((h >> (i * 4)) & 0xF) / 15.0 - 0.5)
    return vec


def cluster_prompts(prompts: list[str], n_clusters: int) -> tuple[dict, list[list[str]]]:
    from sklearn.cluster import KMeans

    X = [embed(p) for p in prompts]
    km = KMeans(n_clusters=min(n_clusters, len(prompts)), n_init=10, random_state=7)
    labels = km.fit_predict(X)
    members: dict[int, list[str]] = {}
    for label, prompt in zip(labels, prompts):
        members.setdefault(int(label), []).append(prompt)
    centroids = km.cluster_centers_

    def dist(v1: list[float], v2) -> float:
        return sum((a - b) ** 2 for a, b in zip(v1, v2)) ** 0.5

    reps = {}
    for label, group in members.items():
        reps[label] = min(group, key=lambda p: dist(embed(p), centroids[label]))
    return reps, [members[k] for k in sorted(members)]


def run_version(workflow_id: str, version: str, prompt: str) -> dict:
    """Single generation for a version, returns per-image scores."""
    job_id = enqueue(workflow_id, version, prompt, SEEDS[0])
    job = wait_result(job_id)
    img = fetch_image(job["image_url"], Path("/tmp") / f"{job_id}.png")
    scores = score_image(str(img), prompt, version)
    scores["seed"] = SEEDS[0]
    return scores


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow_id")
    ap.add_argument("old_version")
    ap.add_argument("new_version")
    args = ap.parse_args()

    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
    mlflow.set_experiment("discovery")

    champion = load_champion(args.workflow_id)
    if not champion:
        print("no champion state; run gate.py --seed-champion first")
        return

    history = PROMPTS[:N_PROMPTS]
    reps, members = cluster_prompts(history, N_CLUSTERS)
    print(f"clustered {len(history)} prompts into {len(members)} clusters")

    failing = []
    with mlflow.start_run(run_name=f"discovery-{args.workflow_id}@{args.new_version}"):
        for label, rep in sorted(reps.items()):
            old_scores = run_version(args.workflow_id, args.old_version, rep)
            new_scores = run_version(args.workflow_id, args.new_version, rep)
            if MOCK:
                # mock: single image per version; emulate seeds by re-scoring
                old_rows = [{**old_scores, "seed": s} for s in SEEDS]
                new_rows = [{**new_scores, "seed": s} for s in SEEDS]
                for s in SEEDS[1:]:
                    old_rows[s - 1]["aesthetic_score"] = old_scores["aesthetic_score"] + 0.05 * (s % 3)
                    new_rows[s - 1]["aesthetic_score"] = new_scores["aesthetic_score"] + 0.05 * (s % 3)
            else:
                old_rows, new_rows = [], []
                for s in SEEDS:
                    old_rows.append(run_version(args.workflow_id, args.old_version, rep))
                    new_rows.append(run_version(args.workflow_id, args.new_version, rep))
            ci_lo, ci_hi = paired_bootstrap_ci(new_rows, old_rows, "aesthetic_score")
            mean_diff = round(sum(n["aesthetic_score"] - o["aesthetic_score"] for n, o in zip(new_rows, old_rows)) / len(old_rows), 4)
            tol = RULES["aesthetic_score"]["tolerance"]
            is_failing = ci_hi < 0 or mean_diff < -tol
            flag = "FAILING" if is_failing else "ok"
            print(f"  cluster {label} ({len(members[label])} prompts, rep={rep[:40]!r}): "
                  f"aesthetic diff {mean_diff:+.4f} CI95 {ci_lo}..{ci_hi} -> {flag}")
            mlflow.log_metrics({f"cluster{label}_diff": mean_diff, f"cluster{label}_ci_hi": ci_hi})
            if is_failing:
                failing.append((label, rep, members[label]))

        discovered = []
        for label, rep, group in failing:
            discovered.append(rep)
            for m in MUTATIONS:
                discovered.append(m.format(p=rep))
        discovered = list(dict.fromkeys(discovered))

        old_text = ADVERSARIAL_FILE.read_text().strip().splitlines() if ADVERSARIAL_FILE.exists() else []
        merged = list(dict.fromkeys(old_text + discovered))
        ADVERSARIAL_FILE.write_text("\n".join(merged) + "\n")
        print(f"\ndiscovered {len(discovered)} adversarial prompts from {len(failing)} failing clusters")
        print("merged into " + str(ADVERSARIAL_FILE) + f" (total {len(merged)})")
        mlflow.log_param("discovered", len(discovered))

    out = STATE_DIR / f"discovery-{args.workflow_id}.json"
    STATE_DIR.mkdir(exist_ok=True)
    out.write_text(json.dumps({"workflow_id": args.workflow_id, "old": args.old_version,
                               "new": args.new_version, "failing_clusters": len(failing),
                               "discovered_prompts": discovered, "suite_file": str(ADVERSARIAL_FILE)}, indent=2))
    print(f"report -> {out}")


if __name__ == "__main__":
    main()