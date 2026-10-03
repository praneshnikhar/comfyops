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
2. **Grafana v1 dashboards — DONE (2026-10-03, dev compose on Asus)** —
   see §10.
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

## 10. M2 leftover done: Grafana v1 observability (dev compose, on Asus 2026-10-03)

- **Gateway `/metrics`** (`prometheus_client` in `gateway/app/core/metrics.py`):
  `comfyops_jobs_total{status}`, `comfyops_job_latency_seconds` (hist, enqueue→complete),
  `comfyops_generation_time_seconds` (hist, worker-reported), `comfyops_rabbitmq_queue_depth`
  (gauge, polled from RabbitMQ mgmt API by a background thread).
- **Worker**: same histogram + `comfyops_worker_jobs_total`, metrics on `:9100`
  (`COMFYOPS_WORKER_METRICS_PORT`); `complete_job` now POSTs a JSON body
  `{image_url, generation_time}` (query-param form still accepted).
- **Stack**: `infra/prometheus/prometheus.yml`, `infra/grafana/provisioning/`
  (datasource `uid: Prometheus` + dashboard provider), dashboard
  `infra/grafana/dashboards/comfyops-v1.json` (7 panels: queue depth stat+series,
  job latency p50/p95, generation time p50/p95, throughput, jobs total, failures).
  Grafana admin `admin`/`comfyops`, http://localhost:3000, Prometheus :9090.
- **Asus quirk (IMPORTANT)**: a host firewall drops docker-bridge → host traffic,
  so Prometheus/Grafana run with `network_mode: host` in dev compose and scrape
  `127.0.0.1`. On Mac Docker Desktop this also works (published ports reach macOS
  loopback), but if not, revert to `ports:` + `extra_hosts: host-gateway` +
  `host.docker.internal` targets.
- **Python 3.14 quirk**: `urllib` rejects userinfo-in-URL (`http://user:pass@host`)
  — always strip auth into an `Authorization: Basic` header (see `_mgmt_url`/`_mgmt_headers`
  in `metrics.py`). gateway/worker requirements now include `prometheus-client`.
- **Ops gotchas**: killing uvicorn with `pkill -f "uvicorn app.main"` also kills the
  invoking shell (pattern matches its own cmdline) — use `pkill -f "uvicorn app[.]main"`.
  Start gateway detached with plain `nohup ... &` (`setsid` hangs the shell tool).

---

## 11. M3 + M4 + M5 DONE (Asus session, 2026-10-03) — viva evidence available

### M3 — statistical rigor ✅
- `scoring/gate_config.py`: 20 prompts × 5 seeds; per-metric rules (clip/aesthetic
  tolerance, defect-rate +0.05 max, gen-time/cost +25% max); cost model
  `COST_PER_SECOND`; bootstrap settings.
- `scoring/gate.py` v2: batch enqueue → poll → score; `paired_bootstrap_ci`
  (pure Python, 2000 iters); BLOCK when CI95 entirely < 0 or beyond tolerance;
  `--seed-champion` / `--promote` (promotion also calls the gateway promote API);
  pushes `comfyops_gate_metric{workflow,version,metric}` + `comfyops_gate_verdict`
  to pushgateway (:9091) for dashboards v2; per-image rows stored in champion
  state for proper paired bootstrap. **Measured: champion seeded; challenger
  1.1.0 BLOCKED (aesthetic CI95 all < 0, matching real M2 numbers).**
- **Gateway promotion + canary** (`app/core/promotion.py`): `POST /workflows/{name}/promote`
  (unversioned /generate then defaults to the promoted version, NOT the newest
  file), `POST|GET|DELETE /workflows/{name}/canary` (weight 0..1 traffic split).
  Verified: 50% canary → exactly 5/5 split; promote → default routes to 1.0.0.
- `infra/grafana/dashboards/comfyops-v2.json` — quality trends (clip/aesthetic/
  defect/gen-time/cost per version + verdict stats).
- Mock modes for no-GPU machines: `COMFYOPS_MOCK_SCORE=1` (deterministic
  synthetic scores, noise keyed on prompt ONLY so identical versions compare
  equal), `COMFYOPS_MOCK_WORKER=1` (placeholder PNG, no ComfyUI). The full
  gateway→queue→worker→S3→gate pipeline runs on a model-less box.

### M4 — blame analysis + breakage discovery ✅ (novel core)
- `scoring/blame.py`: node-level `diff_workflows` (class_type + input changes),
  `revert_node` (reverts changed node + any changed nodes it references),
  ablation runs via gateway `workflow_json` override (new `POST /generate` field),
  verdict = recovering the *failing metrics* (CI95 upper ≥ 0 vs champion).
  **Measured: 1.1.0 BLOCKed → ablation of KSampler (steps 20→8, euler→heun)
  recovers → "3 | KSampler | inputs | -0.0010 | +0.2200 | BLAMED".** Report →
  `.gate_state/blame-*.json` + MLflow experiment `blame`.
- `scoring/discovery.py`: CLIP text embeddings (pseudo-embeddings in mock),
  KMeans clustering, per-cluster paired bootstrap new-vs-champion, mutations of
  failing cluster representatives, merged into `scoring/adversarial_prompts.txt`
  which `gate.py` loads into every run. **Measured: 27 adversarial prompts
  discovered from 3 failing clusters; next gate run includes them.**
- Gateway: `GenerateRequest.workflow_json` — ad-hoc graphs for ablation/experiments.

### M5 — semantic prompt caching + load tests ✅
- `gateway/app/core/cache.py`: open_clip ViT-B-32 text embeddings (lazy; shared
  repo-level `.model_cache/`, see note below), entries in Valkey keyed
  `comfyops:cache:v<version>`, cosine lookup, `SIM_THRESHOLD=0.92` (calibrated on
  real embeddings: paraphrase hits ≥0.94, near-misses ~0.88, unrelated ≤0.78),
  TTL 86400, audit sampling 5% (`comfyops:cache:audit`), `invalidate()` on
  promote (wipes other versions' entries — verified).
  **Measured: "a red apple" miss → "an apple that is red" HIT in 76ms; unrelated
  prompt misses.**
- `loadtest/locustfile.py` + locust: **570 requests / 0 failures / 13 rps,
  /generate p95 180ms, /jobs p50 3ms** (headless run command in the file).
- **Model cache moved to repo root** `.model_cache/` (shared by scoring + gateway
  CLIP). Updated `scoring/app/clip_score.py`, `aesthetic_score.py` paths +
  `.gitignore` (`scoring/.model_cache/` → `.model_cache/`). NEVER commit it.
- **Gateway venv now has torch cpu + open_clip** (needed for real embeddings;
  ~700MB). `gateway/requirements.txt` is the light prod set — if you want the
  gateway container to serve real cache hits it needs torch/open_clip too (for
  now prod cache defaults to pseudo-embeddings unless installed).

### Asus prod prep (partially done — k3s install is YOUR sudo action)
- `scripts/setup-prod.sh` — full k3s + manifests + Argo CD + verification steps
  (run with sudo on this machine).
- `infra/k3s/gateway.yaml` updated (rabbitmq mgmt URL env), new
  `infra/k3s/observability.yaml` (Prometheus/Grafana/pushgateway on hostNetwork,
  dashboards as ConfigMaps), `infra/argo/comfyops-app.yaml` (GitOps app).
- Gateway image builds clean (`comfyops-gateway:latest`, smoke-tested boot).

---

## 9. Contact/identity

- GitHub: praneshnikhar — all repos private where noted; comfyops is private.
- Final year solo project; hardware budget: MacBook M3 (8GB, generation worker) +
  Asus Vivobook i5-11th-gen Iris Xe (k3s control plane, CPU scoring).
- Constraint: everything open source / self-hosted, ₹0 budget. No paid LLMs.