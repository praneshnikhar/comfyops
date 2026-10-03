"""Minimal ComfyUI API client (headless server).

Submit a workflow (API-format JSON graph), wait for completion by polling
/history, download the output images. Polling is used instead of the
websocket so the worker has no extra dependency; streaming progress via
websocket is a later improvement.
"""

import time
import uuid

import requests

POLL_INTERVAL = 0.5
DEFAULT_TIMEOUT = 300  # seconds; SD1.5 @ 512x512 ~ 10-30s on MPS


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188"):
        self.base_url = base_url

    def generate(self, workflow: dict, timeout: float = DEFAULT_TIMEOUT) -> list[bytes]:
        client_id = str(uuid.uuid4())
        resp = requests.post(
            f"{self.base_url}/prompt",
            json={"prompt": workflow, "client_id": client_id},
            timeout=10,
        )
        resp.raise_for_status()
        prompt_id = resp.json().get("prompt_id")
        if not prompt_id:
            raise ComfyError(f"no prompt_id in response: {resp.text}")

        deadline = time.monotonic() + timeout
        images = None
        while time.monotonic() < deadline:
            history = requests.get(f"{self.base_url}/history/{prompt_id}", timeout=10).json()
            entry = history.get(prompt_id)
            if entry is None:
                time.sleep(POLL_INTERVAL)
                continue
            if entry.get("status", {}).get("status_str") == "error":
                msgs = entry.get("status", {}).get("messages", [])
                raise ComfyError(f"execution error: {msgs}")
            outputs = entry.get("outputs", {})
            for node_out in outputs.values():
                images = [img for img in node_out.get("images", [])]
            if images is not None:
                break
            time.sleep(POLL_INTERVAL)
        if images is None:
            raise ComfyError(f"timed out after {timeout}s (prompt_id={prompt_id})")

        payloads = []
        for img in images:
            r = requests.get(
                f"{self.base_url}/view",
                params={
                    "filename": img["filename"],
                    "subfolder": img.get("subfolder", ""),
                    "type": img.get("type", "output"),
                },
                timeout=120,  # generous: 8GB Mac under swap pressure is slow
            )
            r.raise_for_status()
            payloads.append(r.content)
        return payloads