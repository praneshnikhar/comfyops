# ComfyOps scoring service — quality metrics for the gate.
# All CPU-only, runs in the Asus cluster.

# M2 (gate v1): CLIP score (prompt match)
# M3: bootstrapped confidence intervals over multi-seed runs
# M3+: aesthetic predictor, LPIPS-vs-champion, face/OCR defect rate
from abc import ABC, abstractmethod


class Metric(ABC):
    name: str

    @abstractmethod
    def score(self, image_path: str, prompt: str | None = None) -> float:
        ...


# M2:
# class CLIPScore(Metric): ...
# class AestheticScore(Metric): ...
# M3:
# class LPIPSSimilarity(Metric): ...
# class DefectRate(Metric): face + OCR checks