"""Aesthetic score metric (M2).

LAION aesthetic predictor: a linear probe trained on human ratings of image
beauty (0..10), applied on top of CLIP vision embeddings (ViT-B-32, 512-dim).
We reuse the CLIP backbone from clip_score so no extra vision model loads.

Model: sa_0_4_vit_b_32_linear.pth (LAION-AI/aesthetic-predictor, MIT).
"""

import os
from pathlib import Path

import open_clip
import torch
from PIL import Image

MODEL_NAME = "ViT-B-32"
PRETRAINED = "openai"
CACHE_DIR = os.path.join(Path(__file__).resolve().parent.parent.parent, ".model_cache")
WEIGHTS_URL = "https://github.com/LAION-AI/aesthetic-predictor/raw/main/sa_0_4_vit_b_32_linear.pth"
WEIGHTS_PATH = os.path.join(CACHE_DIR, "sa_0_4_vit_b_32_linear.pth")

_clip_model = None
_preprocess = None
_probe = None


def _ensure_weights() -> None:
    if os.path.exists(WEIGHTS_PATH):
        return
    os.makedirs(os.path.dirname(WEIGHTS_PATH), exist_ok=True)
    import urllib.request

    print(f"downloading aesthetic weights -> {WEIGHTS_PATH}")
    urllib.request.urlretrieve(WEIGHTS_URL, WEIGHTS_PATH)


def _load() -> None:
    global _clip_model, _preprocess, _probe
    if _probe is not None:
        return
    _ensure_weights()
    _clip_model, _preprocess, _ = open_clip.create_model_and_transforms(
        MODEL_NAME, pretrained=PRETRAINED, cache_dir=CACHE_DIR
    )
    _clip_model.eval()
    state = torch.load(WEIGHTS_PATH, map_location="cpu")
    _probe = torch.nn.Linear(512, 1)
    _probe.load_state_dict({"weight": state["weight"], "bias": state["bias"]})
    _probe.eval()


def aesthetic_score(image_path: str) -> float:
    _load()
    image = _preprocess(Image.open(image_path).convert("RGB")).unsqueeze(0)
    with torch.no_grad():
        feat = _clip_model.encode_image(image)
        feat /= feat.norm(dim=-1, keepdim=True)
        score = _probe(feat)
    return float(score.item())


if __name__ == "__main__":
    import sys

    print("aesthetic_score:", aesthetic_score(sys.argv[1]))