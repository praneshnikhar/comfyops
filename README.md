# ComfyOps

Automated testing and debugging platform for generative image workflows.

Versioning ComfyUI workflows like software — quality gates with statistical rigor,
automated blame analysis, breakage discovery, and semantic prompt caching.

See `design-doc-2026-10-03.md` for the full design.

## Architecture

```
Asus Vivobook (k3s control plane)          MacBook M3 (ComfyUI worker)
  FastAPI gateway, RabbitMQ, MinIO,          worker agent (Python)
  Argo Workflows/CD, KEDA, MLflow,           runs ComfyUI natively (MPS)
  Valkey, Prometheus, Grafana, n8n
```

## Layout

```
gateway/       FastAPI API — workflows, jobs, results, cache
worker/        Mac worker agent — pulls jobs from RabbitMQ, runs ComfyUI
scoring/       Quality metrics — CLIP, aesthetic, LPIPS, face/OCR defects
pipelines/     Argo Workflows — quality gate, blame analysis, breakage discovery
infra/         k3s manifests + Helm values (MinIO, RabbitMQ, Valkey, Argo, ...)
scripts/       setup scripts (asus, mac, image builds)
tests/         tests
docs/          docs
```

## Status

M0 — scaffolding. Milestones in the design doc.