"""Blame analysis — automated ablation for workflow regressions (M4, novel core).

When a challenger workflow version FAILS the quality gate, this pipeline:

  1. diffs challenger vs champion workflow graphs (node-level),
  2. for each changed node, builds an *ablation* = challenger with ONLY that
     node reverted to its champion value (plus any changed nodes it references),
  3. runs the ablation on a reduced test suite,
  4. scores it and checks whether quality *recovers* to the champion level
     (paired bootstrap CI, same machinery as gate.py),
  5. outputs a blame report: node | impact | verdict.

Usage:
  python blame.py <workflow_id> <old_version> <new_version> [--prompts N] [--seeds N]

Env:
  COMFYOPS_GATEWAY, COMFYOPS_MOCK_SCORE, COMFYOPS_BLAME_PROMPTS/SEEDS.

Report: .gate_state/blame-<workflow_id>.json + MLflow run.
"""

import argparse
import copy
import json
import os
import statistics
import sys
import time
import urllib.request
from pathlib import Path

import mlflow

from gate import aggregate, enqueue, fetch_image, gate_decision, load_champion, wait_result

sys.path.insert(0, str(Path(__file__).parent))
from gate_config import PROMPTS, SEEDS, RULES  # noqa: E402
from app.score import score_image  # noqa: E402

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "workflows"
GATEWAY = os.getenv("COMFYOPS_GATEWAY", "http://127.0.0.1:8000")
STATE_DIR = Path(__file__).parent / ".gate_state"
REPORT_DIR = STATE_DIR

N_PROMPTS = int(os.getenv("COMFYOPS_BLAME_PROMPTS", "10"))
N_SEEDS = int(os.getenv("COMFYOPS_BLAME_SEEDS", "3"))


def load_workflow(name: str, version: str) -> dict:
    path = WORKFLOWS_DIR / name / f"{version}.json"
    if not path.exists():
        raise SystemExit(f"workflow {name}@{version} not found")
    return json.loads(path.read_text())["workflow"]


def diff_workflows(old: dict, new: dict) -> list[dict]:
    """Node-level diff: class_type changes and input value changes."""
    changes = []
    for nid, node in new.items():
        if nid not in old:
            changes.append({"node": nid, "class_type": node.get("class_type"), "change": "added", "old": None, "new": None})
            continue
        if node.get("class_type") != old[nid].get("class_type"):
            changes.append({"node": nid, "class_type": node.get("class_type"), "change": "class_type", "old": old[nid].get("class_type"), "new": node.get("class_type")})
            continue
        old_in, new_in = old[nid].get("inputs", {}), node.get("inputs", {})
        diffs = {k: (old_in.get(k), new_in.get(k)) for k in set(old_in) | set(new_in) if old_in.get(k) != new_in.get(k)}
        if diffs:
            changes.append({"node": nid, "class_type": node.get("class_type"), "change": "inputs", "inputs": {k: {"old": a, "new": b} for k, (a, b) in diffs.items()}})
    for nid in old:
        if nid not in new:
            changes.append({"node": nid, "class_type": old[nid].get("class_type"), "change": "removed", "old": None, "new": None})
    return changes


def revert_node(workflow: dict, node_id: str, champion_wf: dict, changed_nodes: set[str]) -> dict:
    """Challenger copy with `node_id` (and any changed nodes it references)
    restored to champion values."""
    wf = copy.deepcopy(workflow)
    wf[node_id] = copy.deepcopy(champion_wf[node_id])
    refs = _referenced_nodes(wf[node_id]) & changed_nodes
    while refs:
        nid = refs.pop()
        wf[nid] = copy.deepcopy(champion_wf[nid])
        refs |= (_referenced_nodes(wf[nid]) & changed_nodes)
    return wf


def _referenced_nodes(node: dict) -> set[str]:
    refs = set()
    for value in node.get("inputs", {}).values():
        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
            refs.add(value[0])
    return refs


def run_suite_custom(workflow_json: dict, version_label: str) -> list[dict]:
    """Run (prompt, seed) pairs with a custom workflow graph via the gateway."""
    results = []
    for prompt in PROMPTS[:N_PROMPTS]:
        for seed in SEEDS[:N_SEEDS]:
            body = json.dumps(
                {"workflow_id": "custom", "version": version_label,
                 "prompt": prompt, "seed": seed, "workflow_json": workflow_json}
            ).encode()
            req = urllib.request.Request(f"{GATEWAY}/generate", data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                job_id = json.load(r)["job_id"]
            job = wait_result(job_id)
            img = fetch_image(job["image_url"], Path("/tmp") / f"{job_id}.png")
            scores = score_image(str(img), prompt, version_label)
            scores.update({"prompt": prompt, "seed": seed, "job_id": job_id})
            results.append(scores)
            print(f"  [{prompt[:38]}] clip={scores['clip_score']:.3f} aesthetic={scores['aesthetic_score']:.3f}", flush=True)
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow_id")
    ap.add_argument("old_version")
    ap.add_argument("new_version")
    args = ap.parse_args()

    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
    mlflow.set_experiment("blame")

    old_wf = load_workflow(args.workflow_id, args.old_version)
    new_wf = load_workflow(args.workflow_id, args.new_version)
    changes = diff_workflows(old_wf, new_wf)
    if not changes:
        print(f"no node differences between {args.old_version} and {args.new_version}")
        return

    print(f"changed nodes ({len(changes)}):")
    for c in changes:
        if c["change"] == "inputs":
            print(f"  {c['node']} ({c['class_type']}): " + ", ".join(f"{k}: {v['old']}->{v['new']}" for k, v in c["inputs"].items()))
        else:
            print(f"  {c['node']} ({c['class_type']}): {c['change']}")

    champion = load_champion(args.workflow_id)
    if not champion:
        print("no champion state; run gate.py --seed-champion first")
        return

    changed_ids = {c["node"] for c in changes}

    # baseline: the full challenger on the reduced suite
    print(f"\nbaseline challenger {args.new_version} ({N_PROMPTS} x {N_SEEDS}):")
    challenger_rows = run_suite_custom(new_wf, args.new_version)
    challenger_agg = aggregate(challenger_rows)
    _, challenger_reason, challenger_gd = gate_decision(challenger_rows, champion, challenger_agg)
    failing_metrics = [
        m for m in ("clip_score", "aesthetic_score")
        if challenger_gd[m]["ci95"][1] < 0 or challenger_agg[f"{m.split('_')[0]}_mean"] - champion[f"{m.split('_')[0]}_mean"] < -RULES[m]["tolerance"]
    ]
    print(f"challenger verdict: {challenger_reason} | failing metrics: {failing_metrics or 'none'}")

    report = {"workflow_id": args.workflow_id, "old_version": args.old_version,
              "new_version": args.new_version, "changes": changes,
              "challenger": challenger_agg, "ablations": [], "verdict": "PASS"}
    with mlflow.start_run(run_name=f"blame-{args.workflow_id}@{args.new_version}"):
        mlflow.log_params({"workflow_id": args.workflow_id, "old": args.old_version, "new": args.new_version})
        mlflow.log_metrics({"challenger_aesthetic_mean": challenger_agg["aesthetic_mean"],
                            "challenger_clip_mean": challenger_agg["clip_mean"]})

        for c in changes:
            ablation = revert_node(new_wf, c["node"], old_wf, changed_ids)
            label = f"abl-{c['node']}"
            print(f"\nablation: revert node {c['node']} ({c['class_type']}) -> {label}")
            rows = run_suite_custom(ablation, label)
            agg = aggregate(rows)
            _, reason, gd = gate_decision(rows, champion, agg)
            # impact vs full challenger on the reduced suite (same rows count)
            impact = {m: round(agg[f"{m.split('_')[0]}_mean"] - challenger_agg[f"{m.split('_')[0]}_mean"], 4)
                      for m in ("clip_score", "aesthetic_score")}
            recovered = bool(failing_metrics) and all(gd[m]["ci95"][1] >= 0 for m in failing_metrics)
            print(f"  ablation vs champion: clip CI95 {gd['clip_score']['ci95']}, "
                  f"aesthetic CI95 {gd['aesthetic_score']['ci95']}")
            verdict = "BLAMED" if recovered else "ok"
            entry = {"node": c["node"], "class_type": c["class_type"], "change": c["change"],
                     "impact": impact, "verdict": verdict,
                     "ablation": {k: agg[k] for k in ("clip_mean", "aesthetic_mean", "defect_rate")}}
            report["ablations"].append(entry)
            print(f"  impact: {impact}  verdict: {verdict}")

        blamed = [e for e in report["ablations"] if e["verdict"] == "BLAMED"]
        report["verdict"] = "BLAMED: " + ", ".join(f"{e['node']} ({e['class_type']})" for e in blamed) if blamed else "no single node fully explains the regression"
        mlflow.log_param("verdict", report["verdict"])

    REPORT_DIR.mkdir(exist_ok=True)
    out = REPORT_DIR / f"blame-{args.workflow_id}.json"
    out.write_text(json.dumps(report, indent=2))
    print("\n== blame report ==")
    print(f"{'node':<6}{'class':<24}{'change':<12}{'clip Δ':>8}{'aesth Δ':>9}  verdict")
    for e in report["ablations"]:
        print(f"{e['node']:<6}{e['class_type']:<24}{e['change']:<12}"
              f"{e['impact']['clip_score']:>+8.4f}{e['impact']['aesthetic_score']:>+9.4f}  {e['verdict']}")
    print(f"\n{report['verdict']}")
    print(f"report -> {out}")


if __name__ == "__main__":
    main()