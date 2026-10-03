# ComfyOps quality gate — test prompts (M2).
# Runs on a fixed prompt set with fixed seeds so results are comparable
# across workflow versions. Small set for the 8GB dev Mac; expand in prod.
PROMPTS = [
    "a red apple on a wooden table",
    "a golden retriever in a park",
    "a futuristic city skyline at sunset",
    "a cup of coffee with steam",
    "a white cat sleeping on a sofa",
    "a mountain lake at dawn",
]
SEEDS = [42]
STEPS = 20