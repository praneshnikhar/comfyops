#!/usr/bin/env bash
# M1 — Asus (control plane) setup: Ubuntu dual-boot assumed.
# Install k3s, MinIO, RabbitMQ, Valkey. Run as root or with sudo.
set -euo pipefail

echo "==> Installing k3s"
curl -sfL https://get.k3s.io | sh -

echo "==> k3s status"
sudo k3s kubectl get nodes

echo "==> Next: apply infra/k3s/*.yaml manifests (MinIO, RabbitMQ, Valkey, ...)"
echo "    kubectl apply -f infra/k3s/"