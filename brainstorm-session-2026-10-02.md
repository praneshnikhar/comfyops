# Final-Year MLOps Project — Brainstorm Session Notes

**Date:** 2026-10-02
**Status:** Idea exploration in progress — no final pick yet
**Next step:** Pick one of the four "level-up" options (D15), then design doc

---

## 1. User profile (constraints that shaped everything)

- **Goal:** Production-level, advanced MLOps project for final year
- **Constraint:** Everything must be open source
- **Hardware:** MacBook M3 (Apple Silicon, no CUDA — MPS/MLX/Metal path)
- **Team/time:** Solo, 5-6 months
- **ML theory:** Rusty ("strong at software/backend, ML needs refreshing")
- **Wants:** Something visible, useful, meaningful to the teacher/examiner, "next level"
- **GitHub:** `praneshnikhar` — 100 repos, advanced hacker (see section 4)

---

## 2. The exploration journey (what was considered and why it was dropped)

### Round 1 — Project archetypes (dropped)
1. Drift-adaptive fraud detection — **dropped**: user already built `selfHealingRetrainTrigger`
2. Conformal time-series forecasting — dropped: math-heavy, user wanted "next level"
3. LLM RAG with evals — dropped: too common for user's level
4. Compressed on-device vision — dropped

### Round 2 — Research-grade platforms (dropped)
1. Mini-Modyn (continuous training platform, SIGMOD'25) — dropped: user said "don't limit to retrain"
2. Champion/Challenger production platform — dropped: already built similar
3. LLMOps observability — dropped

### Round 3 — Company production systems (dropped)
1. Feature store platform (Feast pattern) — considered
2. ML platform (Metaflow pattern) — dropped
3. LLM serving platform (vLLM pattern) — considered, became final option

### Round 4 — Novel ideas from named unsolved problems (dropped)
1. Feature parity verifier (ACM Queue unsolved problem)
2. AgentOps observability (2026 frontier)
3. ML technical-debt detector
4. Baseline-preserving canary

### Round 5 — Visible product ideas (dropped)
1. CareerPulse (placement/skills platform) — **dropped**: user already built `Sage` (scraper + MLflow + Prefect pipeline)
2. Canteen forecast dashboard — dropped: too simple for user's level

### Round 6 — CURRENT: Level-up options (not yet picked)

---

## 3. Key research findings (the gold)

### Named unsolved problems (ACM Queue, "Unsolved Problems in MLOps")
- Bounding model stochasticism for testing
- **Canarying for quality control across multiple models + preserving a baseline**
- Model provenance/versioning
- Monitoring (single largest problem category — half of practitioners don't monitor)
- Efficiency/cost management (query routing, stranded GPU capacity)
- Data leakage/injection/security with LLMs

### Reference implementations worth studying (all open source)
| Repo | What it is | Ideas to steal |
|---|---|---|
| `eth-easl/modyn` (MIT) | ETH Zurich continuous-training platform, **SIGMOD'25**: triggering policies (time/volume/performance/drift) + data selection policies (sample-level) + composite-model evaluation | Policy comparison methodology; research platform framing |
| `var1914/mlops-boilerplate` | Most complete end-to-end reference pipeline: Airflow 3 + MLflow 3, 60 models, @champion promotion, FastAPI auto-reload, Grafana dashboards, Docker Compose + Helm | Architecture blueprint: ETL → nightly training → registry → serving |
| `Shrinet82/MLOPS-Full-Data-Pipeline` | Fraud pipeline: DVC + GitHub Actions + CML (model report in PRs), OpenTelemetry, load testing, SHAP/Fairlearn/Evidently | CML for ML CI/CD, fairness analysis, load testing |
| `MLflow 3.x` | Now an LLM platform: tracing, evals, prompt registry, AI gateway | LLMOps base layer |
| `Langfuse` (MIT) | Self-hosted LLM observability: traces, LLM-as-judge, prompt versioning | LLM observability reference |
| `OpenMLDB` (SIGMOD'25) | Real-time feature computation: **one unified query plan for offline+online** (consistency by construction), pre-aggregation, sub-50ms lookups. Deployed in 100+ scenarios | The consistency problem solved at engine level |
| `FlorDB` (VLDB'25) | "Hindsight logging": add logging statements post-hoc, retroactive replay | Metadata-later concept |
| `Magnus` (ByteDance, PVLDB'25) | Data management for large recommendation/multimodal models, Git-like metadata branching | Scale data mgmt |
| `Metaflow` (Netflix) | Human-centric workflow platform; used at Netflix (3000+ projects), Amazon, DoorDash, Goldman Sachs | Platform design |
| `Feast` | Open-source feature store; used by Uber, DoorDash (100K req/s), Lyft, Spotify, Swiggy, Robinhood, Netflix | Feature store reference |
| `vLLM` | PagedAttention serving engine; 24x throughput vs TGI; **now supports Apple Silicon** | Serving engine reference |

### 2026 trends
- **AgentOps** is the new frontier (MLOps → LLMOps → AgentOps). Databricks "Big Book of AgentOps" (Sept 2026). Agent market $7.8B → $52.6B by 2030.
- Agents break the MLOps paradigm: must watch decisions/tool-calls, not accuracy. Documented gaps: agent registries, behavioral baselines + anomaly detection, session replay, tool governance, compliance drift.
- Feature stores = hottest MLOps skill (LinkedIn 2025: MLOps Engineer 3rd fastest-growing role, 80% of listings mention feature stores).
- Licensing notes: Arize Phoenix = ELv2 (not OSI), Seldon Core = BSL. Clean picks: MIT/Apache (MLflow, Feast, Langfuse, Modyn, Metaflow, vLLM).

---

## 4. GitHub portfolio analysis (`praneshnikhar` — what's ALREADY built)

**Do NOT suggest these again:**
- `selfHealingRetrainTrigger` — drift → auto-retrain → champion comparison ✅ (kills all "retraining loop" ideas)
- `driftAlerting` — Evidently + Slack/GitHub Issues/n8n alerts ✅ (kills drift-monitoring ideas)
- `Sage` — scraper + ML price prediction + Prefect + MLflow ✅ (kills scraper+pipeline ideas)
- `diode-watch` — streaming ML threat detection on mirrored traffic ✅
- `Self-Healing-RAG` — RAG with failure detection/fixing ✅
- `MeshFLow` (Go) — decentralized DAG orchestration, no SPOF ✅
- Agent fleet repos: `hermes-agent`, `agentswarm`, `commandFlow`, `agent-orchestrator`, `codePilot`, `FixLoop`, `Titan`, `Agentic-EDA-tool`, `contract-reviewer`, `ticket-genie` (Android agent), `recoverflow` ✅
- `GRIT` (Rust) — git reimplementation from scratch ✅
- `Termium` (Rust) — Chromium-based terminal browser ✅
- `LLM-From-Scratch` — GPT-style transformer in PyTorch ✅
- `MacDeck` (Swift) — macOS app ✅
- Forks of `llama.cpp`, `BitNet` — interested in inference internals
- K8s: `ChaosExperiment` (Go), `DockStore`, `k8s-simple-project` ✅
- `NEAT`, `DeepRL`, `ML_implementations` — learning repos

**Real gaps (never touched across 100 repos):**
1. **Feature stores** (Feast) + train/serve consistency verification
2. **Model compression CI/CD + on-device deployment** (distill/quantize/CoreML/CI benchmarks/OTA)
3. **Behavioral observability for agents** (session replay, anomaly baselines, tool governance)
4. **LLM serving engine internals** (continuous batching, KV cache, scheduler — only wrapped models before)
5. **Real-time feature computation engine** (windowed SQL, offline/online unified plans)
6. **Distributed training** (Ray-style)
7. **Production benchmark suites** (MLPerf-style rulebooks)

---

## 5. Current options on the table (D15 — not yet answered)

### Option 1 — LLM Serving Platform ("vLLM-lite") *(recommended: most employable)*
- **What:** Building the serving layer, not wrapping models (their `LLMs_on_FastAPI` just wraps):
  - Scheduler with **continuous batching**
  - **Quantization switching** (INT4/INT8 via MLX/llama.cpp)
  - Model versioning + **canary routing** between models
  - **OpenAI-compatible API**
  - Load-test harness + throughput/latency dashboards (Grafana)
- **Why fits:** forked llama.cpp + BitNet already; Rust/Go background; runs on M3 Metal/MLX
- **Risk:** systems depth; ambitious for 5 months
- **Employability:** highest — inference infra is the hottest AI skill

### Option 2 — Real-Time Feature Computation Engine ("OpenMLDB-lite") *(most research-impressive)*
- **What:** Compact version of SIGMOD'25 OpenMLDB:
  - Extended-SQL dialect for windowed features ("avg transaction over 30d")
  - **One query plan compiled for offline batch AND online real-time** — train/serve consistency by construction
  - Pre-aggregation for long windows, sub-50ms point lookups
  - Benchmark vs Spark/pandas
- **Why fits:** nothing in repo is a data engine; viva examiner recognizes SIGMOD lineage
- **Risk:** hardest idea here

### Option 3 — Model Compression CI/CD → Real Mac App *(most visible)*
- **What:** train → distill → quantize (INT8) → CoreML/MLX export → **CI auto-benchmarks accuracy/latency/size per version** → Swift app ships winner
- **Why fits:** Swift (MacDeck) + BitNet/llama.cpp curiosity; nothing like it in repo
- **Risk:** lowest — compression is well-trodden; novelty is the CI/CD-for-compression angle

### Option 4 — Agent Observability & Governance Platform (AgentOps) *(most frontier)*
- **What:** Ops layer for agent fleets:
  - OpenTelemetry tracing (GenAI spans)
  - **Session replay UI**
  - Behavioral baselines + **anomaly alerts**
  - Tool-permission governance, per-session cost attribution
- **Why fits:** built many agents, never the ops layer; 2026 frontier (Databricks Big Book of AgentOps, Sept 2026)
- **Risk:** forked `opik` (Comet's LLM observability) — must clearly out-build it

### Honorable mentions (not in final 4)
- Distributed training platform (Ray-lite) — needs a 2nd machine
- Production benchmark suite (MLPerf-lite) — methodology-first, least "system"

---

## 6. Constraints to respect in the design

- **All open source, all self-hosted** (no managed cloud). M3-native: MLX/MPS/Metal, llama.cpp, Postgres, Redis, MinIO, Docker; local K8s via Docker Desktop/Minikube/OrbStack if needed
- **Solo, 5-6 months** — pick one deep, defensible contribution over three shallow ones
- **Visible result** — user needs something "that can be seen": live demo, dashboard, app, or benchmark charts
- **Meaningful to teacher** — one-sentence thesis statement, defensible for 20-min viva
- **Nothing already in the 100-repo portfolio**

---

## 7. Next steps

1. Pick one of the four options (D15)
2. I write the full design doc: architecture, stack, milestones, 5-month timeline, viva demo script
3. Decide K8s involvement (user asked "can we use k8s?" — yes: local single-node cluster via Docker Desktop/OrbStack; K8s is substrate, not thesis)
4. Then scaffold the repo

---

## 8. User's stated preferences (verbatim signals)

- "it should be production level, advanced, everything open source"
- "something which can be seen or idk is useful"
- "create some meaning to my teacher"
- "suggest me more better projects that what i did, dont limit it to retrain"
- "completely new idea, but presentable and meaningful, as if we are solving any problem"