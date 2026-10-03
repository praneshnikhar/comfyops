"""Locust load test for the ComfyOps gateway (M5).

Exercises /generate with a small prompt pool (repeated prompts exercise the
semantic cache; novel prompts exercise the queue path) and polls job status.

Run:
  pip install locust
  locust -f loadtest/locustfile.py --host http://127.0.0.1:8000 \
         --headless -u 20 -r 5 -t 60s --csv=/tmp/opencode/locust

Metrics to watch: request latency, job queue depth, cache hit rate
(comfyops_cache_hits_total vs misses in Prometheus).
"""

import random
import time

from locust import HttpUser, between, task

PROMPTS = [
    "a red apple on a wooden table",
    "a golden retriever in a park",
    "a futuristic city skyline at sunset",
    "a cup of coffee with steam",
    "a white cat sleeping on a sofa",
    "a mountain lake at dawn",
    "a red sports car on a coastal road",
    "a stack of pancakes with maple syrup",
    "an apple that is red and ripe",
    "a red sneaker on a street",
    "a blue car in a garage",
    "a dog running in a park",
]

WORKFLOW = "txt2img-sd15"


class GenerationUser(HttpUser):
    wait_time = between(0.5, 2.0)

    @task(3)
    def generate(self):
        prompt = random.choice(PROMPTS)  # pool reuse -> cache hits
        with self.client.post(
            "/generate",
            json={"workflow_id": WORKFLOW, "prompt": prompt, "seed": random.randint(0, 1000)},
            name="/generate",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                job = resp.json()
                if job.get("cached"):
                    resp.success()  # instant semantic cache hit
                else:
                    resp.success()
            else:
                resp.failure(f"status {resp.status_code}")

    @task(1)
    def novel_prompt(self):
        # fresh prompts -> cache miss -> queue path
        self.client.post(
            "/generate",
            json={
                "workflow_id": WORKFLOW,
                "prompt": f"a unique scene number {random.randint(0, 10**6)}",
                "seed": random.randint(0, 1000),
            },
            name="/generate (novel)",
        )

    @task(2)
    def poll_job(self):
        job_id = self.ensure_job()
        if job_id:
            self.client.get(f"/jobs/{job_id}", name="/jobs/{id}")

    def ensure_job(self):
        # keep a handle on the most recent job for polling
        job_id = getattr(self, "_last_job", None)
        if job_id is None or random.random() < 0.3:
            try:
                resp = self.client.post(
                    "/generate",
                    json={"workflow_id": WORKFLOW, "prompt": random.choice(PROMPTS), "seed": random.randint(0, 1000)},
                    name="/generate (poll feeder)",
                )
                if resp.status_code == 200:
                    job_id = resp.json()["job_id"]
                    self._last_job = job_id
            except Exception:
                return None
        return job_id