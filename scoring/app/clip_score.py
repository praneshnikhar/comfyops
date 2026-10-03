"""CLIP score metric (M2).

Rates how well a generated image matches its prompt:
  prompt -> CLIP text embedding
  image  -> CLIP vision embedding
  score  = cosine similarity (0..1)

Model: open_clip ViT-B-32 (OpenAI), cached in .model_cache.
"""

import open_clip
import torch
from PIL import Image

MODEL_NAME = "ViT-B-32"
PRETRAINED = "openai"
CACHE_DIR = "/Users/pranesh/coding2/final-year-project/scoring/.model_cache"

_model = None
_preprocess = None
_tokenizer = None
_device = "cpu"


def _load() -> None:
    global _model, _preprocess, _tokenizer, _device
    if _model is not None:
        return
    _model, _preprocess, _ = open_clip.create_model_and_transforms(
        MODEL_NAME, pretrained=PRETRAINED, cache_dir=CACHE_DIR
    )
    _tokenizer = open_clip.get_tokenizer(MODEL_NAME)
    _model.eval()
    _device = "cpu"


def clip_score(image_path: str, prompt: str) -> float:
    _load()
    image = _preprocess(Image.open(image_path).convert("RGB")).unsqueeze(0)
    tokens = _tokenizer([prompt])
    with torch.no_grad():
        img_feat = _model.encode_image(image)
        txt_feat = _model.encode_text(tokens)
    img_feat /= img_feat.norm(dim=-1, keepdim=True)
    txt_feat /= txt_feat.norm(dim=-1, keepdim=True)
    return float((img_feat @ txt_feat.T).item())


if __name__ == "__main__":
    import sys

    print("clip_score:", clip_score(sys.argv[1], sys.argv[2]))