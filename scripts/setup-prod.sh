#!/usr/bin/env bash
# ComfyOps PRODUCTION setup on the Asus (k3s single-node).
# Everything here needs sudo (k3s install + cluster operations).
# Run once, in order, from the repo root.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/7] k3s install (single node, traefik disabled — NodePorts used)"
curl -sfL https://get.k3s.io | sh -s - --disable traefik
K="sudo k3s kubectl"
$K get nodes

echo "==> [2/7] base services (namespace, SeaweedFS, RabbitMQ, Valkey)"
$K apply -f infra/k3s/namespace.yaml
$K apply -f infra/k3s/seaweedfs.yaml infra/k3s/rabbitmq.yaml infra/k3s/valkey.yaml
$K rollout status deployment -n comfyops --timeout=300s

echo "==> [3/7] gateway image (native amd64 build + import, no registry needed)"
if ! docker image inspect comfyops-gateway:latest >/dev/null 2>&1; then
  docker build -t comfyops-gateway:latest gateway/
fi
docker save comfyops-gateway:latest | sudo k3s ctr images import -
# point the manifest at the local image
sed -i 's|image: ghcr.io/praneshnikhar/comfyops-gateway:latest|image: comfyops-gateway:latest|; s|imagePullPolicy:.*|imagePullPolicy: IfNotPresent|' infra/k3s/gateway.yaml
$K apply -f infra/k3s/gateway.yaml
$K rollout status deployment/gateway -n comfyops --timeout=300s

echo "==> [4/7] observability (Prometheus, pushgateway, Grafana)"
$K apply -f infra/k3s/observability.yaml
$K rollout status deployment/prometheus deployment/grafana -n comfyops --timeout=300s

echo "==> [5/7] Argo CD (GitOps)"
$K create namespace argocd || true
$K apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
$K apply -f infra/argo/comfyops-app.yaml

echo "==> [6/7] Mac worker wiring (edit the IP, then run ON THE MAC):"
echo "    COMFYOPS_RABBITMQ=<ASUS_IP> COMFYOPS_MINIO=<ASUS_IP>:9000 \\"
echo "    COMFYOPS_GATEWAY=http://<ASUS_IP>:31000 COMFYOPS_WORKER_METRICS_PORT=9100 \\"
echo "    python worker.py"
echo "    (prometheus scrape target for the worker: infra/k3s/observability.yaml, replace 192.168.1.50)"

echo "==> [7/7] verify"
$K get pods -n comfyops
echo "    gateway:   http://<ASUS_IP>:31000/health"
echo "    rabbitmq:  http://<ASUS_IP>:31567  (guest/guest)"
echo "    grafana:   http://<ASUS_IP>:3000   (admin/comfyops)"
echo "    prometheus: http://<ASUS_IP>:30090"
echo "    argocd:    sudo k3s kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
echo "    (assign a static LAN IP to the Asus — the Mac needs a stable address)"