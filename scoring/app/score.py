"""Scoring service — scores one image with all gate metrics (M2/M3).

Usage: python -m app.score <image_path> <prompt> [version]
Output: JSON with clip_score, aesthetic_score, latency_ms.

COMFYOPS_MOCK_SCORE=1 enables a deterministic mock scorer (no torch/models):
synthetic scores calibrated to the real M2 results (champion clip ~0.31 /
aesthetic ~6.26; challenger 1.1.0 aesthetic ~-0.22). Lets the full gate /
blame / discovery pipeline run and demo without the Mac worker.
"""

import hashlib
import json
import os
import sys
import time

from app.aesthetic_score import aesthetic_score
from app.clip_score import clip_score

MOCK = os.getenv("COMFYOPS_MOCK_SCORE") == "1"


def _hash(*parts: str) -> float:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest(), 16) / 2**256


def _mock_score(image_path: str, prompt: str, version: str | None) -> dict:
    """Deterministic synthetic scores calibrated to real M2 numbers."""
    clip = 0.28 + 0.06 * _hash(prompt)
    aesthetic = 5.8 + 0.8 * _hash("a", prompt)
    noise_c = 0.01 * _hash("c", prompt, os.path.basename(image_path))
    noise_a = 0.15 * _hash("n", prompt, os.path.basename(image_path))
    gen_time = 82.0 + 10.0 * _hash("t", prompt, os.path.basename(image_path))
    if version == "1.1.0":  # the known-bad challenger (matches real M2 results)
        clip += 0.001
        aesthetic -= 0.22
        gen_time += 6.0
    return {
        "clip_score": round(clip + noise_c, 4),
        "aesthetic_score": round(aesthetic + noise_a, 4),
        "gen_time": round(gen_time, 1),
    }


def score_image(image_path: str, prompt: str | None = None, version: str | None = None) -> dict:
    t0 = time.monotonic()
    result = {"image": image_path}
    if MOCK:
        result.update(_mock_score(image_path, prompt or "", version))
    else:
        if prompt:
            result["clip_score"] = round(clip_score(image_path, prompt), 4)
        result["aesthetic_score"] = round(aesthetic_score(image_path), 4)
    result["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
    return result


if __name__ == "__main__":
    path = sys.argv[1]
    prompt = sys.argv[2] if len(sys.argv) > 2 else None
    version = sys.argv[3] if len(sys.argv) > 3 else None
    print(json.dumps(score_image(path, prompt, version)))