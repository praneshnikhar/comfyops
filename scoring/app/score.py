"""Scoring service — scores one image with all gate metrics (M2).

Usage: python -m app.score <image_path> <prompt>
Output: JSON with clip_score, aesthetic_score, latency_ms.
"""

import json
import sys
import time

from app.aesthetic_score import aesthetic_score
from app.clip_score import clip_score


def score_image(image_path: str, prompt: str | None = None) -> dict:
    t0 = time.monotonic()
    result = {"image": image_path}
    if prompt:
        result["clip_score"] = round(clip_score(image_path, prompt), 4)
    result["aesthetic_score"] = round(aesthetic_score(image_path), 4)
    result["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
    return result


if __name__ == "__main__":
    path = sys.argv[1]
    prompt = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(score_image(path, prompt)))