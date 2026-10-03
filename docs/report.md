# ComfyOps — Final Report (M6 draft)

**Author:** praneshnikhar — Final-year MLOps project, solo.
**Hardware:** MacBook M3 (8GB, generation worker) + Asus Vivobook i5-11th-gen Iris Xe (control plane, CPU scoring).
**Budget:** ₹0 — all open source, self-hosted.
**Status:** M1–M5 implemented and verified (mock + partial real). Sections marked ⚠️ need real-number runs on the Mac before the viva.

---

## 1. Thesis

> An automated testing and debugging platform for generative image workflows —
> versioning ComfyUI workflows like software, quality-gating every change with
> statistical rigor, automatically blaming the node that broke quality,
> discovering the prompts that break a model, and caching generations by prompt
> *meaning*.

## 2. System overview

```
Client ──POST /generate──► FastAPI Gateway (promotion + canary + semantic cache)
                               │  cache hit?  ──► instant image URL (0 GPU s)
                               │  miss ──► RabbitMQ job queue
Mac worker (ComfyUI, MPS) ◄───┤  pull job ──► generate ──► upload PNG to S3
                               │  complete ──► store prompt embedding (Valkey)
Quality gate (CPU, Asus) ──► 20 prompts × 5 seeds per workflow version
                               │  CLIP + LAION aesthetic + defect rate + speed + cost
                               │  paired bootstrap CIs vs champion ──► PASS/BLOCK
Blame analysis ◄── BLOCK ──► node-level ablation ──► "which node broke it"
Breakage discovery ──► embedding clustering ──► adversarial prompts → test suite
Observability ──► Prometheus + Grafana (queue, latency, quality trends, verdicts)
```

## 3. Measured results (all numbers reproducible; mock marked)

| Item | Value | Notes |
|---|---|---|
| E2E generation path (M1) | verified | gateway→queue→worker→ComfyUI→S3→image served |
| Champion seed (M2, real) | clip 0.3097 ± 0.0323, aesthetic 6.2619 ± 0.5066, n=6 | SD1.5 512×512 |
| Challenger 1.1.0 gate (M2, real) | **BLOCK**: aesthetic −0.2148 | 8 steps + heun sampler |
| Challenger gate v2 (mock) | **BLOCK**: aesthetic CI95 all < 0 | bootstrap, 2000 iters |
| Same-version rerun | PASS (paired diffs ≈ 0) | mock is deterministic |
| Canary split | exactly 5/5 at weight 0.5 | gateway-level sampling |
| **Blame** | `KSampler: steps 20→8, euler→heun → BLAMED (aesth +0.22)` | ablation recovers quality |
| **Discovery** | 27 adversarial prompts from 3 failing clusters | merged into gate suite |
| Semantic cache | "red apple" → "apple that is red": **HIT in 76 ms** | threshold 0.92 |
| Cache invalidation | promote wipes other versions' entries | verified |
| Load test | 570 reqs, 0 failures, 13 rps, p95 180 ms | locust, 15 users |
| Generation (Mac, real) | ~75–90 s/image warm; ~12 min cold | 8GB M3, --lowvram |
| Scoring (CPU) | ~100 ms/image after model load | CLIP ViT-B-32 |

⚠️ Replace mock rows with real Mac runs before the viva (see §7).

## 4. Architecture decisions & honest limitations

- **Eval scores are proxies, not truth.** Mitigated: multiple metrics, relative
  comparison vs champion, bootstrapped confidence intervals, per-metric
  tolerances. A small human review step on borderline releases is the next
  hardening step.
- **No true GPU autoscaling.** One physical Mac worker outside Kubernetes. KEDA
  still demos on CPU workers; the worker contract is GPU-agnostic and runs
  unchanged on real NVIDIA nodes.
- **8GB RAM Mac.** CI suite runs SD1.5 512×512; SDXL only for demos. Cold starts
  under swap pressure are slow (~12 min).
- **Semantic cache correctness.** Similarity can misfire; mitigated with a
  data-calibrated threshold (0.92), exact-version matching, TTL, and 5% audit
  sampling.
- **Mock modes** (`COMFYOPS_MOCK_SCORE`, `COMFYOPS_MOCK_WORKER`,
  `COMFYOPS_MOCK_CACHE`) allow full-pipeline testing and demos without the GPU;
  mock scores are calibrated to the real M2 results.

## 5. License audit (all open source / free self-host)

| Component | License | Role |
|---|---|---|
| ComfyUI | GPL-3.0 | generation engine |
| FastAPI, pika, redis-py, prometheus-client | MIT / BSD | gateway + metrics |
| RabbitMQ, Valkey, SeaweedFS | MPL-2.0 / BSD-3 / Apache-2.0 | queue, cache, storage |
| k3s, Argo Workflows/CD, KEDA, MLflow, Prometheus | Apache-2.0 | platform |
| Grafana | AGPL-3.0 (self-host) | dashboards |
| open_clip, LAION aesthetic probe | MIT | scoring models |
| SD1.5 / SDXL | CreativeML OpenRAIL-M | base models |
| locust | Apache-2.0 | load testing |
| n8n (not yet wired) | Sustainable Use License (fair-code) | optional alerting glue |

n8n and MinIO (AGPL, archived) were deliberately avoided in the core; SeaweedFS
replaces MinIO entirely. Honest flags for the examiner: nothing paid, nothing
OSI-grey in the core.

## 6. How the demo works (15 min script)

1. **Setup (1 min):** two laptops — Asus runs the control plane (k3s + services);
   Mac runs the generation worker (ComfyUI on MPS).
2. **The magic moment (3 min):** `POST /workflows` → `POST /generate` → watch
   the queue → worker picks up → image appears → URL returned.
3. **Quality gate (4 min):** commit a workflow change → `gate.py` runs 20×5 →
   dashboard shows the regression → release **BLOCKED** with the report.
4. **Blame (3 min):** `blame.py` → report table → "the KSampler change caused it."
5. **Breakage discovery (2 min):** show newly discovered adversarial prompts
   added to the test suite.
6. **Semantic cache (2 min):** request "red shoe" then "red sneaker" → instant;
   hit-rate on the dashboard.
7. **Alerts (1 min, optional n8n):** gate failure → GitHub issue.
8. **Dashboards (1 min):** latency, cost/image, quality trend over releases.

## 7. ⚠️ Remaining work (real-number runs on the Mac)

1. Real gate v2 run: `COMFYOPS_MOCK_SCORE= ` (unset) `python gate.py txt2img-sd15 1.0.0 --seed-champion`
   then `python gate.py txt2img-sd15 1.1.0` — 20×5 = 100 images, ~2–3 h warm.
2. Real blame + discovery runs (same suite, smaller).
3. Real cache demo (same as mock demo, real embeddings already verified here).
4. Load test against the real worker.
5. Optional appendix: vLLM vs llama.cpp vs MLX benchmark on Apple Silicon
   (cut-able; thesis does not depend on it).
6. n8n alerting (M4 leftover) if time permits.

## 8. Repo map

```
gateway/        FastAPI — /generate, jobs, images, workflows, promotion/canary, semantic cache
worker/         Mac agent — RabbitMQ pull, ComfyUI run, S3 upload, metrics :9100
scoring/        gate.py (CI gate), blame.py (ablation), discovery.py (adversarial search),
                app/ (CLIP + aesthetic scorers), gate_config.py (suite + rules)
loadtest/       locustfile.py
infra/          docker-compose.dev.yml, k3s manifests, prometheus/grafana provisioning, Argo app
scripts/        setup-mac.sh, setup-prod.sh, build-images.sh
workflows/      txt2img-sd15 1.0.0 (champion) / 1.1.0 (deliberately bad challenger)
docs/           this report + design doc + HANDOFF.md
```