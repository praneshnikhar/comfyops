"""Workflow registry (M2).

Workflows are versioned JSON files in git (workflows/<name>/<version>.json).
The registry loads them at startup, validates structure, and resolves
`workflow_id` (+ optional version) to an API-format graph with prompt/seed
injected.
"""

import json
import re
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "workflows"

# node ids that carry the prompt / seed and how to inject them
PROMPT_NODE = "6"          # CLIPTextEncode positive
SEED_NODE = "3"            # KSampler
PROMPT_PLACEHOLDER = "{{PROMPT}}"

_registry: dict[str, dict] = {}


def _validate(graph: dict) -> list[str]:
    errors = []
    if PROMPT_NODE not in graph:
        errors.append(f"workflow missing positive CLIPTextEncode node '{PROMPT_NODE}'")
    if SEED_NODE not in graph:
        errors.append(f"workflow missing KSampler node '{SEED_NODE}'")
    for nid, node in graph.items():
        if not isinstance(node, dict) or "class_type" not in node or "inputs" not in node:
            errors.append(f"node {nid}: must have class_type and inputs")
    return errors


def load_registry() -> dict[str, dict]:
    """Load all workflows/<name>/<version>.json into {id: metadata}."""
    global _registry
    _registry = {}
    for wf in sorted(WORKFLOWS_DIR.glob("*/")):
        name = wf.name
        versions = sorted(wf.glob("*.json"))
        if not versions:
            continue
        latest = versions[-1]
        meta = json.loads(latest.read_text())
        errors = _validate(meta.get("workflow", {}))
        _registry[name] = {
            "name": name,
            "version": meta.get("version", latest.stem),
            "description": meta.get("description", ""),
            "models": meta.get("models", []),
            "versions": [v.stem for v in versions],
            "valid": not errors,
            "errors": errors,
            "workflow_file": str(latest),
        }
    return _registry


def resolve(name: str, version: str | None = None) -> tuple[dict, str]:
    """Return (workflow_json_with_prompt_placeholder, version_string)."""
    if name not in _registry:
        raise KeyError(f"unknown workflow '{name}'")
    if version is None:
        version = _registry[name]["version"]
    path = WORKFLOWS_DIR / name / f"{version}.json"
    if not path.exists():
        raise KeyError(f"workflow '{name}' has no version {version}")
    meta = json.loads(path.read_text())
    errors = _validate(meta.get("workflow", {}))
    if errors:
        raise ValueError(f"workflow '{name}' invalid: {errors}")
    return meta["workflow"], version


def instantiate(workflow: dict, prompt: str, seed: int) -> dict:
    """Fill the prompt placeholder and seed into a graph copy."""
    import copy

    wf = copy.deepcopy(workflow)
    # positive CLIPTextEncode: text may be a placeholder or a fixed string
    if wf.get(PROMPT_NODE, {}).get("inputs", {}).get("text") == PROMPT_PLACEHOLDER:
        wf[PROMPT_NODE]["inputs"]["text"] = prompt
    wf[SEED_NODE]["inputs"]["seed"] = seed
    return wf