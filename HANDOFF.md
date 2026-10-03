# ComfyOps — Handoff / Resume Document (Asus)

**Purpose:** this repo was developed on the MacBook M3 (arm64). This document lets a
fresh opencode session (e.g., on the Asus Vivobook) resume the project with zero
context loss. Read `design-doc-2026-10-03.md` for the full design, then this file.

**Repo:** https://github.com/praneshnikhar/comfyops (private)
**Branch:** main — everything is pushed.

---

## 1. What this project is (one paragraph)

ComfyOps is an automated testing and debugging platform for generative image
workflows. ComfyUI (running natively on the Mac, MPS GPU) is the generation
engine. A FastAPI gateway (on the Asus k3s cluster in production) accepts
`POST /generate`, resolves a versioned workflow from a git registry, enqueues
jobs on RabbitMQ; a Python worker agent on the Mac pulls jobs, runs them in
ComfyUI, uploads PNGs to S3-compatible storage (SeaweedFS), and notifies the
gateway. A quality gate (`scoring/gate.py`) runs every workflow version on a
fixed prompt set, scores images (CLIP + LAION aesthetic), compares against the
stored champion with tolerances, and returns PASS/BLOCK. MLflow tracks every
run. Future milestones (M3-M5) add statistical confidence intervals, blame
analysis, breakage discovery, and semantic prompt caching (see design doc).

---

## 2. Architecture & hardware split

```
Asus Vivobook (LINUX, k3s — PRODUCTION)     MacBook M3 (native macOS — GENERATION)
  gateway (FastAPI, NodePort :31000)          ComfyUI headless :8188 (--lowvram)
  rabbitmq :5672 (:31567 mgmt)                worker agent (pulls RabbitMQ jobs)
  valkey :6379                                4.3GB SD1.5 checkpoint (downloaded)
  seaweedfs S3 :9000                          dev-only: docker compose dev env
  mlflow :5000 (also local on Mac dev)
  prometheus/grafana (M2 leftover)
  argo workflows + argo cd (M2/M3)
```

**Dev setup (works TODAY on the Mac):** everything runs locally — gateway + MLflow
natively (venvs), RabbitMQ/Valkey/SeaweedFS in Docker Desktop (`docker-compose.dev.yml`).
**Prod:** the same services as k3s manifests (`infra/k3s/`) on the Asus; the Mac worker
only needs env vars pointing at the Asus IP.

---

## 3. Current state — DONE (M1 + M2 core)

### M1 — Foundations ✅ (verified end-to-end)
- `gateway/` FastAPI: `POST /generate`, `GET /jobs/{id}`, `GET /images/{job}/{file}`
  (S3 proxy), `GET /workflows`, reconnect-safe RabbitMQ publisher
  (`app/core/rabbit.py`), SQLite job store (`app/core/jobs.py` — `gateway/app/comfyops.db`)
- `worker/` agent: pulls RabbitMQ `generation-jobs`, runs workflow in ComfyUI
  (`comfy_client.py`, polling /history), uploads to S3, auto-completes the job
  via gateway. `workflow_builder.py` fallback txt2img graph
- `docker-compose.dev.yml` — RabbitMQ (ECR mirror), Valkey (GHCR), SeaweedFS
  (Docker Hub `chrislusf/seaweedfs:latest`) — verified working
- `infra/k3s/` — manifests: namespace, seaweedfs (PVC 50Gi + s3 config),
  rabbitmq (NodePort 31567), valkey, gateway (NodePort 31000)
- `scripts/` — setup-asus.sh, setup-mac.sh, build-images.sh (multi-arch push to GHCR)
- SD1.5 checkpoint downloaded to
  `~/coding2/comfyUI/instance1/ComfyUI/models/checkpoints/v1-5-pruned-emaonly.safetensors`
  (4,265,146,304 bytes — verified complete, matches server Content-Length)
- ComfyUI headless: `cd ~/coding2/comfyUI/instance1/ComfyUI && ./.venv/bin/python main.py --listen 127.0.0.1 --port 8188 --lowvram`
- Default ComfyUI workflow replaced with SD1.5 txt2img graph
  (`user/default/workflows/comfyops_sd15.json` + `Comfy.DefaultWorkflow` setting)
  so the browser UI shows no Qwen/Z-Image errors

### M2 — Registry + Quality Gate ✅ (verified end-to-end)
- `workflows/txt2img-sd15/1.0.0.json` — versioned workflow (API format) with
  `{{PROMPT}}` placeholder + `{{seed}}` in KSampler; `1.1.0.json` is a
  deliberately-worse challenger (8 steps, heun sampler) used for testing the gate
- `gateway/app/core/registry.py` — loads/validates/resolves/instantiates workflows
- `scoring/` service (CPU-only): `app/clip_score.py` (open_clip ViT-B-32 "openai",
  cached in `scoring/.model_cache/`), `app/aesthetic_score.py` (LAION
  `sa_0_4_vit_b_32_linear.pth` linear probe), `app/score.py` CLI
- `scoring/gate_config.py` — 6 test prompts x 1 seed (8GB-Mac sized; bump to 20 for prod)
- `scoring/gate.py` — suite runner + aggregator + PASS/BLOCK with tolerances
  (clip tolerance 0.01, aesthetic tolerance 0.10) + MLflow logging
- **Results already produced (viva evidence):**
  - Champion seeded: clip_mean 0.3097 (std 0.0323), aesthetic_mean 6.2619 (std 0.5066), n=6
  - Challenger 1.1.0 BLOCKED: clip 0.3101, aesthetic 6.0471 → `BLOCK: aesthetic -0.2148`
  - State file: `scoring/.gate_state/txt2img-sd15.json`
  - MLflow runs visible at http://127.0.0.1:5000 (experiment `quality-gate`)

### Measured performance on M3 (for the report)
- Generation warm: ~75-90s/image (512x512, 20 steps, --lowvram)
- Cold start (model load): ~12 min under swap pressure
- Scoring: ~100ms/image after CLIP model load (CPU)

---

## 4. Running the stack (dev, on the Mac — as of last session)

```bash
# 1) Docker services
cd ~/coding2/final-year-project && docker compose -f docker-compose.dev.yml up -d

# 2) ComfyUI headless (MPS)
cd ~/coding2/comfyUI/instance1/ComfyUI && ./.venv/bin/python main.py --listen 127.0.0.1 --port 8188 --lowvram &

# 3) Gateway
cd ~/coding2/final-year-project/gateway && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 &

# 4) MLflow
cd ~/coding2/final-year-project/scoring && .venv/bin/mlflow server --host 127.0.0.1 --port 5000 &

# 5) Worker (ONLY ONE — kill duplicates first: pkill -f "python worker.py")
cd ~/coding2/final-year-project/worker && .venv/bin/python worker.py &

# 6) Gate run (champion seed first, then compare)
cd ~/coding2/final-year-project/scoring && .venv/bin/python gate.py txt2img-sd15 1.0.0 --seed-champion
.venv/bin/python gate.py txt2img-sd15 1.1.0
```

**Verify:** `curl localhost:8000/workflows`, `curl -X POST localhost:8000/generate -d '{"workflow_id":"txt2img-sd15","prompt":"a red apple","seed":1}'`
→ job id → poll `GET /jobs/{id}` until `done` → image at `image_url`.

---

## 5. Gotchas / hard-won lessons (IMPORTANT — read before touching anything)

1. **MinIO is DEAD** — archived Oct 2026, images removed from Docker Hub/quay.
   Use **SeaweedFS** (`chrislusf/seaweedfs:latest` on Docker Hub). GHCR seaweedfs
   images have broken manifests (no platform) — do not use them.
2. **Docker Hub partially blocked** (India): `minio/minio` gone, but library
   images work. RabbitMQ pulled from `public.ecr.aws/docker/library/rabbitmq:3-management`;
   Valkey from `ghcr.io/valkey-io/valkey:8`. Same images pinned in k3s manifests.
3. **8GB RAM Mac is the bottleneck.** Keep ComfyUI `--lowvram`. Expect heavy swap;
   first job after idle can take ~12 min, warm jobs ~75-90s. Never run the gate
   suite while ComfyUI is cold. Docker Desktop VM was reduced + Docker AI disabled.
4. **ComfyUI Desktop app conflicts on :8188** — kill it (`pkill -f main.py` and any
   Comfy Desktop processes) and run the headless instance instead.
5. **Worker duplicates**: `pkill -f "python worker.py"` before restarting (older
   `pkill -f "worker/.venv/..."` patterns did NOT match the relative cmdline).
6. **NEVER commit `scoring/.model_cache/`** (577MB CLIP blobs — GitHub rejects
   >100MB; pre-receive hook declines). `.gitignore` has `scoring/.model_cache/`
   and `scoring/.gate_state/`. Check with `git ls-files | grep model_cache`.
7. **`.gitignore` corruption lesson**: `printf >> .gitignore` merged with a
   non-newline-terminated previous line (`images/` + pattern). Always ensure the
   file ends with a newline before appending.
8. Gateway/worker defaults point at `127.0.0.1` (dev). Production overrides via
   env vars: `COMFYOPS_RABBITMQ_URL`, `COMFYOPS_MINIO_ENDPOINT`, `COMFYOPS_REDIS_URL`,
   `COMFYOPS_GATEWAY` (see `gateway/app/core/config.py`, `worker/worker.py`).
9. S3 creds (dev and prod manifests): `comfyops` / `comfyops`.
10. The aesthetic probe is a 512-dim linear probe (`sa_0_4_vit_b_32_linear.pth`)
    — NOT the l14 MLP from improved-aesthetic-predictor (that one expects 768-dim).

---

## 6. What's LEFT in M2 (do these on the Asus)

1. **Argo CD (GitOps)** — install on k3s, point at comfyops repo, auto-deploy
   `infra/k3s/` manifests. 20-30 min.
2. **Grafana v1 dashboards** — job latency, queue depth, generation time.
   Add a Prometheus `/metrics` endpoint to gateway + worker (prometheus_client),
   run Prometheus+Grafana in the cluster, build the dashboard. (Local dev
   equivalent was not built either.)
3. **Prod 20-prompt suite** — set `scoring/gate_config.py` PROMPTS to ~20 when
   the Asus does the scoring (CPU is fine).

## 7. Milestone roadmap (from design doc)

- **M3 (weeks 9-12):** multi-seed runs (20x5) + bootstrapped confidence intervals;
  per-metric gate rules; champion/challenger promotion flow; canary rollout of
  workflow versions (traffic split in gateway); dashboards v2 (quality trends).
- **M4 (13-16): THE NOVEL CORE** — blame analysis (workflow diffing, partial node
  revert, blame report), breakage discovery (embedding clustering + adversarial
  prompt search, merge into test suite), n8n alerting (gate fail → GitHub issue).
- **M5 (17-20):** semantic prompt caching (Valkey embeddings + similarity +
  confidence gate + invalidation on model change), load-testing (locust).
- **M6 (21-24):** report, README, demo script dry-runs, optional vLLM vs MLX
  vs llama.cpp benchmark appendix.

---

## 8. ASUS SETUP — exact steps (the main reason this doc exists)

Precondition: Ubuntu installed (dual-boot recommended; WSL2 adds friction with k3s).

```bash
# 1. k3s single-node cluster (on the Asus)
curl -sfL https://get.k3s.io | sh -
sudo k3s kubectl get nodes            # should show Ready

# 2. Clone the repo
git clone https://github.com/praneshnikhar/comfyops.git && cd comfyops

# 3. Deploy base services
sudo k3s kubectl apply -f infra/k3s/namespace.yaml
sudo k3s kubectl apply -f infra/k3s/seaweedfs.yaml infra/k3s/rabbitmq.yaml infra/k3s/valkey.yaml
sudo k3s kubectl get pods -n comfyops   # all Running

# 4. Gateway image — build on the Asus (native amd64), two options:
#    a) push to GHCR (needs token):  gh auth login && echo $TOKEN | docker login ghcr.io -u praneshnikhar --password-stdin
#       then: bash scripts/build-images.sh
#    b) or build+load locally: cd gateway && docker build -t comfyops-gateway:latest . && sudo docker save comfyops-gateway:latest | sudo k3s ctr images import -
#       (then edit infra/k3s/gateway.yaml image to comfyops-gateway:latest / imagePullPolicy: IfNotPresent)
sudo k3s kubectl apply -f infra/k3s/gateway.yaml

# 5. Static IP for the Asus (router DHCP reservation, e.g. 192.168.1.50) —
#    the Mac worker needs one stable address.

# 6. Argo CD (M2 leftover)
sudo k3s kubectl create namespace argocd
sudo k3s kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
# then: point at the comfyops repo, path infra/k3s/, namespace comfyops (GitOps)

# 7. Point the Mac worker at the Asus (on the MAC):
COMFYOPS_RABBITMQ=192.168.1.50 COMFYOPS_MINIO=192.168.1.50:9000 \
COMFYOPS_GATEWAY=http://192.168.1.50:31000 .venv/bin/python worker.py
# Verify: queue depth on RabbitMQ mgmt :31567, images land in SeaweedFS, gateway returns them.

# 8. MLflow + Prometheus + Grafana + n8n — later milestones; MLflow: ghcr.io/mlflow/mlflow image or pip install.
```

**Network notes:** Mac pulls jobs (outbound only — no inbound ports needed on the Mac).
Ports the Asus must listen on: 5672 (AMQP), 9000 (S3), 31000 (gateway NodePort),
31567 (RabbitMQ mgmt), 5000 (MLflow), 3000 (Grafana, later).

---

## 9. Contact/identity

- GitHub: praneshnikhar — all repos private where noted; comfyops is private.
- Final year solo project; hardware budget: MacBook M3 (8GB, generation worker) +
  Asus Vivobook i5-11th-gen Iris Xe (k3s control plane, CPU scoring).
- Constraint: everything open source / self-hosted, ₹0 budget. No paid LLMs.