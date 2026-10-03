#!/usr/bin/env bash
# Build the gateway image for BOTH architectures (Mac is arm64, Asus is
# x86) and push to GHCR. Requires a GHCR auth token:
#   echo $TOKEN | docker login ghcr.io -u praneshnikhar --password-stdin
set -euo pipefail

cd "$(dirname "$0")/../gateway"

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t ghcr.io/praneshnikhar/comfyops-gateway:latest \
  --push \
  .

echo "pushed ghcr.io/praneshnikhar/comfyops-gateway:latest (amd64+arm64)"