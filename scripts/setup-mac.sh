#!/usr/bin/env bash
# M1 — Mac (worker) setup: Python venv + worker agent.
# ComfyUI is already installed at ~/coding2/comfyUI/instance1.
set -euo pipefail

cd "$(dirname "$0")/../worker"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

echo "==> Start ComfyUI:"
echo "    cd ~/coding2/comfyUI/instance1 && ./start.sh"
echo "==> Start worker:"
echo "    source .venv/bin/activate && python worker.py"