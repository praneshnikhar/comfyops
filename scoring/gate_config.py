# ComfyOps quality gate — test suite (M3).
# Fixed prompt set x multiple seeds so results are comparable across
# workflow versions. 20 prompts x 5 seeds = 100 generations per gate run.
# On the 8GB Mac that is ~2-3h warm; use COMFYOPS_GATE_PROMPTS / COMFYOPS_GATE_SEEDS
# (int) to shrink for fast dev iterations. Production always runs the full set.
PROMPTS = [
    "a red apple on a wooden table",
    "a golden retriever in a park",
    "a futuristic city skyline at sunset",
    "a cup of coffee with steam",
    "a white cat sleeping on a sofa",
    "a mountain lake at dawn",
    "a red sports car on a coastal road",
    "a stack of pancakes with maple syrup",
    "a rainbow over a green valley",
    "a vintage camera on a desk",
    "a snowy pine forest at night",
    "a plate of sushi with chopsticks",
    "a hot air balloon over a desert",
    "a bookshelf full of old books",
    "a child flying a kite on a beach",
    "a glass of orange juice on a table",
    "a lighthouse during a storm",
    "a field of sunflowers",
    "a close-up of a butterfly on a flower",
    "a cozy fireplace in a cabin",
]
SEEDS = [1, 2, 3, 4, 5]
STEPS = 20

# --- per-metric gate rules (M3) -------------------------------------------
# clip_score / aesthetic_score : tolerance = max allowed mean drop vs champion.
# defect_rate                  : max absolute increase in defect fraction.
# gen_time / cost_per_image    : max relative increase (ratio) vs champion.
RULES = {
    "clip_score": {"tolerance": 0.01},
    "aesthetic_score": {"tolerance": 0.10},
    "defect_rate": {"max_abs_increase": 0.05},
    "gen_time": {"max_ratio_increase": 0.25},
    "cost_per_image": {"max_ratio_increase": 0.25},
}

# a defect = an image failing any of these per-image checks
DEFECT_CLIP_BELOW = 0.15
DEFECT_AESTHETIC_BELOW = 4.0

# cost model: cost/image = gen_time_seconds * COST_PER_SECOND (₹0 budget demo —
# pick a sane machine-hour price; the thesis just needs a *consistent* unit)
COST_PER_SECOND = 0.00002  # USD-equiv per GPU-second (~$0.07/GPU-h)

# bootstrap CIs (M3)
BOOTSTRAP_ITERATIONS = 2000
CI_LEVEL = 0.95