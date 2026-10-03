# Final-Year MLOps Project — Design Doc

**Date:** 2026-10-03
**Status:** LOCKED — ready for scaffolding
**Author:** Solo (praneshnikhar)
**Hardware:** MacBook M3 (ComfyUI/GPU) + Asus Vivobook i5-11th-gen Iris Xe (k3s control plane)
**Budget:** ₹0 — everything open source, self-hosted, local

---

## 0. Thesis (viva one-liner)

> "An automated testing and debugging platform for generative image workflows —
> versioning ComfyUI workflows like software, quality-gating every change with
> statistical rigor, automatically blaming the node that broke quality, discovering
> the prompts that break a model, and caching generations by prompt *meaning*."

---

## 1. What we are building (simple words)

ComfyUI is the engine that draws images. We build the **operations platform** around it:

1. **ComfyUI-as-a-Service** — upload a workflow JSON, get a scalable API endpoint ("workflow in, API out").
2. **Quality gates** — every workflow change is tested on a fixed prompt suite with multiple seeds; scored; compared against the current champion **with confidence intervals**; blocked if worse.
3. **Automated blame analysis** — when a change fails the gate, the platform re-runs the workflow swapping changed nodes back one at a time, and reports *which node* caused the regression (git-bisect for workflows).
4. **Breakage discovery** — instead of only fixed prompts, automatically search prompt-embedding space for the clusters where the new version fails, and add those adversarial prompts to the test set. Gates get smarter over time.
5. **Semantic prompt caching** — cache generations by prompt *meaning* (embedding similarity), not exact text; invalidate correctly when model versions change.
6. **Alerting/automation glue (n8n)** — gate failures auto-file GitHub issues and notify; scheduled quality reports.
7. **(Optional side-experiment) LLM serving benchmark** — vLLM vs llama.cpp vs MLX on Apple Silicon, serving a tiny free local model for the judge service. Cut if time runs out; thesis does not depend on it.

No paid services anywhere. No ChatGPT. All models are free open-license weights downloaded to local disks.

---

## 2. Architecture

### 2.1 Two-laptop overview

```
Asus Vivobook (Linux, k3s)                  MacBook M3 (native macOS)
┌──────────────────────────────────┐        ┌─────────────────────────┐
│ k3s single-node cluster          │        │ ComfyUI (headless, MPS) │
│  ┌────────────────────────────┐  │  job   │ ┌─────────────────────┐ │
│  │ FastAPI Gateway (API)      │  │ queue  │ │ Worker agent        │ │
│  │ Workflow/Model Registry    │◄─┼────────┼►│ (Python) pulls job, │ │
│  │ RabbitMQ (jobs)            │  │        │ │  runs workflow,     │ │
│  │ MinIO (images, workflows)  │  │ results│ │  uploads to MinIO   │ │
│  │ Argo Workflows (pipelines) │◄─┼────────┼─│                     │ │
│  │ Argo CD (GitOps deploys)   │  │        │ └─────────────────────┘ │
│  │ KEDA (scale on queue)      │  │        └─────────────────────────┘
│  │ MLflow (tracking)          │
│  │ Valkey (cache metadata)    │
│  │ Prometheus + Grafana       │
│  │ n8n (alerts/automation)    │
│  └────────────────────────────┘
│ Scoring services (CLIP,        │
│ aesthetic, LPIPS, face/OCR)    │  ← CPU is enough for all of these
└──────────────────────────────────┘
```

### 2.2 Job flow (user request → image)

```
Client ──POST /generate──► FastAPI Gateway
                              │
                       1. Semantic cache lookup (embed prompt, search Valkey)
                              │ hit? ──► return cached image instantly (~0s)
                              │ miss? ──►
                       2. Publish job to RabbitMQ (workflow_id, prompt, seed)
                              │
                     KEDA watches queue depth ──► scales worker replicas
                              │
                       3. Mac worker agent pulls job
                              │
                       4. ComfyUI generates image (MPS GPU)
                              │
                       5. Worker uploads result + metrics to MinIO
                              │
                       6. Gateway returns image URL; webhook optional
                              │
                       7. Background: store prompt embedding for future cache hits
```

### 2.3 Quality gate pipeline (Argo Workflows)

```
Git push (workflow change)
        │
        ▼
Argo Workflows pipeline:
  1. Build/validate workflow JSON (node/lora/model versions resolved)
  2. Run NEW version on test suite: 20 prompts × 5 seeds (SD1.5, 512×512)
  3. Run CHAMPION version on same prompts × seeds (reference)
  4. Score all images: CLIP, aesthetic, LPIPS-vs-champion, face/OCR defect rate,
     generation time, memory, cost/image
  5. Statistical comparison: bootstrapped confidence intervals per metric
  6. Gate decision: PASS / BLOCK (per-metric rules, e.g. "defect rate +2% max")
  7. PASS ──► mark workflow_version=challenger, ready for canary rollout
     BLOCK ──► trigger blame analysis (2.4)
  8. Log everything to MLflow (params, images, metrics, decision)
```

### 2.4 Blame analysis (automated ablation)

```
BLOCKED release ──► changed_nodes = diff(workflow_v2, workflow_v1)
                        │
    For each changed node (checkpoint, LoRA, sampler, upscaler, ...):
        ├─ revert ONLY that node to v1 version
        ├─ run test suite (reduced: 10 prompts × 3 seeds for speed)
        ├─ score + compare vs v1 baseline
        └─ quality recovered? ──► blame = this node
                        │
    Output: blame report (table, not prose):
        node         | impact | verdict
        checkpoint A→B| -18%   | BLAMED
        sampler      |  -1%   | ok
        LoRA         |  +2%   | ok
    n8n files GitHub issue with report attached
```

### 2.5 Breakage discovery (adversarial prompt search)

```
1. Embed production prompt history (CLIP embeddings) → cluster
2. Run new + champion model on cluster centroids
3. Find clusters where NEW scores significantly worse (statistical test)
4. Mutate/template prompts inside those clusters (systematic variations)
5. Add discovered failure prompts to the permanent test suite
   → next gate run tests them automatically
```

### 2.6 Semantic prompt caching

```
1. Every generated image stored in MinIO + its prompt embedding in Valkey
2. New request → embed prompt → similarity search over cached entries
3. sim ≥ threshold (tunable, e.g. 0.95) AND confidence gate passes
   → return cached image (0 GPU seconds)
4. sim < threshold → generate
5. Model version change (new champion) → invalidate affected cache entries
   (a cached image generated by model v1 must not serve model v2 traffic)
6. Monitored: hit-rate, cache accuracy (audit sample), staleness
```

---

## 3. Stack & licenses (open-source check)

| Component | Role | License | Notes |
|---|---|---|---|
| ComfyUI | Image generation engine (headless API) | GPL-3.0 | Native on macOS MPS |
| k3s | Lightweight K8s on Asus | Apache-2.0 | |
| Docker | Containers everywhere | Apache-2.0 | |
| FastAPI | API gateway | MIT | |
| RabbitMQ | Job queue | MPL-2.0 | |
| KEDA | Scale workers on queue depth | Apache-2.0 | |
| Argo Workflows | Pipeline engine (quality gates, blame, discovery) | Apache-2.0 | |
| Argo CD | GitOps deploys of platform + workflows | Apache-2.0 | |
| MinIO → **SeaweedFS** | Object storage (images, workflows, models) | Apache-2.0 | **MinIO open-source archived Oct 2026** (Docker Hub/quay images gone) — SeaweedFS replaces it, same S3 API |
| Valkey | Cache metadata + embeddings | BSD-3 | Redis fork (Redis license changed 2024) |
| MLflow | Experiment tracking, registry | Apache-2.0 | |
| Prometheus / Grafana | Metrics + dashboards | Apache-2.0 / AGPL-3.0 | Grafana free self-host |
| n8n | Alerting/automation glue | Sustainable Use License | NOT OSI "open source" — fair-code, free self-host; glue only |
| CLIP / LAION aesthetic / LPIPS / insightface / tesseract | Scoring models | MIT / MIT / BSD / MIT / Apache-2.0 | CPU-scored on Asus |
| SD 1.5 / SDXL | Base models | CreativeML OpenRAIL-M | Fine for academic project; list in report |
| vLLM (optional) | LLM serving benchmark | Apache-2.0 | Experimental on Apple Silicon; side-experiment only |

**License stance for the report:** core stack is OSI-approved open source; n8n and MinIO flagged honestly with alternatives (a Python alert service / SeaweedFS) if the examiner presses.

---

## 4. Hardware plan

| Task | Machine | Why |
|---|---|---|
| ComfyUI generation | MacBook M3 (MPS) | GPU acceleration; Docker/K8s pods CANNOT use the Mac GPU → ComfyUI runs native, outside K8s |
| k3s cluster (everything else) | Asus (Linux) | x86, proper Linux host; Iris Xe unusable for diffusion but fine for CPU scoring |
| Scoring (CLIP, aesthetic, LPIPS, face/OCR) | Asus cluster | Light, CPU-only |
| CI-style test-suite runs | Mac (via worker) | Generation must be fast → MPS |
| Dashboard viewing | Either | Grafana web UI |

**Asus Linux setup:** dual-boot Ubuntu recommended (k3s + Docker networking is cleaner than WSL2). WSL2 works but adds friction.

**Honest limit:** no true GPU autoscaling — the Mac is one physical worker outside K8s. KEDA still demos correctly (scales CPU workers / replica counts on queue depth); the worker contract is GPU-agnostic and works unchanged on real NVIDIA nodes. This is stated in the report as a design property, not a flaw.

---

## 5. Milestones & timeline (5–6 months, solo)

### M1 — Foundations (weeks 1–4)
- [ ] Asus: dual-boot Ubuntu, install k3s, Docker, local registry
- [ ] MinIO, RabbitMQ, Valkey deployed on k3s
- [ ] ComfyUI headless running on Mac (SD1.5, 512×512 baseline)  ← already installed ✅
- [ ] Worker agent: pull job → run ComfyUI → upload result to MinIO
- [ ] FastAPI gateway: `POST /generate`, queue publish, result fetch
- [ ] First end-to-end: API → queue → Mac → image back to client

### M2 — Workflow-as-code + registry + gates v1 (weeks 5–8)
- [ ] Workflow JSONs in Git; resolver validates node/model/LoRA versions
- [ ] Argo CD deploys platform components (GitOps)
- [ ] MLflow tracking wired
- [ ] Quality gate v1: fixed 20 prompts × 1 seed, CLIP + aesthetic, champion comparison
- [ ] Gate PASS/BLOCK decision + MLflow report
- [ ] Grafana v1: job latency, queue depth, generation time

### M3 — Statistical rigor + full pipeline (weeks 9–12)
- [ ] Multi-seed runs (20 × 5) + bootstrapped confidence intervals
- [ ] Per-metric gate rules (defect rate, speed, cost) — configurable
- [ ] Champion/challenger promotion flow (manual approve → challenger)
- [ ] Canary rollout of workflow versions (traffic split via gateway)
- [ ] Dashboards v2: quality trends, gate history

### M4 — Blame analysis + breakage discovery (weeks 13–16)  ← the novel core
- [ ] Workflow diffing (node-level) + partial revert executor
- [ ] Blame pipeline in Argo Workflows + blame report table
- [ ] Breakage discovery: embedding clustering + mutation search
- [ ] Discovered prompts merged into permanent test suite
- [ ] n8n: gate failure → GitHub issue + notification; weekly quality report

### M5 — Semantic caching + hardening (weeks 17–20)
- [ ] Prompt embedding storage (Valkey) + similarity lookup
- [ ] Confidence gate for cache hits; threshold tuning
- [ ] Cache invalidation on model version change
- [ ] Hit-rate / accuracy / staleness monitoring on dashboard
- [ ] Load-test API (locust) — throughput, latency, failure behavior

### M6 — Polish + viva (weeks 21–24)
- [ ] Report: architecture, limitations (eval proxies, no real GPU scaling), license audit
- [ ] README + docs; reproducible setup scripts
- [ ] Demo script dry-runs (15 min), fallback paths if Mac/network misbehaves
- [ ] Optional: vLLM vs llama.cpp vs MLX benchmark as appendix

**Cut list if behind schedule:** vLLM experiment → breakage discovery v1 (keep blame + fixed suite) → semantic caching stays (it is simple and demo-worthy).

---

## 6. Viva demo script (~15 min)

1. **Setup (1 min):** two laptops, one sentence each — "Asus runs the control plane (k3s); Mac runs the generation worker (ComfyUI on the GPU)."
2. **The magic moment (3 min):** upload a workflow via `POST /workflow`, then `POST /generate` → watch queue → worker picks up → image appears in MinIO → URL returned.
3. **Quality gate (4 min):** git commit changing the sampler → Argo pipeline auto-runs → dashboard shows regression → release BLOCKED with report.
4. **Blame (3 min):** click "blame" → pipeline reverts nodes one by one → report: "the new checkpoint caused it."
5. **Breakage discovery (2 min):** show newly discovered failure prompts added to the test suite.
6. **Semantic cache (2 min):** request "red shoe" then "red sneaker" → second returns instantly; hit-rate on dashboard.
7. **Alerts (1 min):** n8n GitHub issue created from the blocked release.
8. **Dashboards (1 min):** latency, cost/image, quality trend over releases.

---

## 7. Risks & honest limitations (state these in the report)

- **Eval scores are proxies, not truth** — mitigated: multiple metrics, relative change vs champion, confidence intervals, (optional) small human review step on borderline releases. This honesty strengthens credibility.
- **No real GPU autoscaling** — one Mac worker; KEDA demos on CPU workers; worker contract is GPU-agnostic.
- **M3 RAM limits** — SDXL is heavy on 8 GB; CI suite runs SD1.5 512×512 (minutes, not hours); SDXL optional for demos only.
- **Semantic cache correctness** — similarity can misfire (cat ≠ dog); confidence gate + tunable threshold + audit sampling.
- **Windows laptop k3s** — needs Linux; dual boot chosen over WSL2 for networking sanity.
- **Novel parts (blame, discovery) are the risky scope** — scheduled early (M4), cut list defined.
- **Licenses** — n8n (fair-code), MinIO (AGPL): flagged with alternatives in the report.

---

## 8. Decision log

| # | Decision | Choice |
|---|---|---|
| D1 | Project type | ComfyUI testing/debugging platform (locked) |
| D2 | Novel features | Blame analysis + breakage discovery + semantic caching (locked) |
| D3 | Hardware split | Mac = generation worker, Asus = k3s control plane (locked) |
| D4 | Pipeline engine | Argo Workflows (not Airflow/n8n) — K8s-native, open source |
| D5 | n8n role | Alerting/automation glue only (fair-code, not core) |
| D6 | Base model for CI | SD1.5 @ 512×512 (speed); SDXL optional for demos |
| D7 | Cache store | Valkey (Redis license change) |
| D8 | LLM usage | None required; optional local vLLM/MLX benchmark (cut-able) |

---

## 9. Next steps

1. Scaffold repo: `comfyops/` — gateway, worker, pipelines, infra (k3s manifests), docs
2. M1 kickoff: Asus Linux + k3s + MinIO/RabbitMQ/Valkey + ComfyUI on Mac (already installed ✅)
3. Weekly commits; every milestone ends with a working demo