"""SQLite job store for the gateway (M1).

Tracks job lifecycle: queued -> done/failed. Later milestones swap this
for the full registry + MLflow tracking; SQLite keeps M1 dependency-free.
"""

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "comfyops.db"
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock, _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                seed INTEGER,
                status TEXT NOT NULL DEFAULT 'queued',
                cached INTEGER NOT NULL DEFAULT 0,
                image_url TEXT,
                created_at REAL NOT NULL,
                finished_at REAL
            )
            """
        )


def create_job(workflow_id: str, prompt: str, seed: int | None, cached: bool = False, image_url: str | None = None) -> dict:
    job_id = str(uuid.uuid4())
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, workflow_id, prompt, seed, status, cached, image_url, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (job_id, workflow_id, prompt, seed, "done" if cached else "queued", int(cached), image_url, time.time()),
        )
    return get_job(job_id)


def get_job(job_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def mark_done(job_id: str, image_url: str) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            "UPDATE jobs SET status='done', image_url=?, finished_at=? WHERE id=?",
            (image_url, time.time(), job_id),
        )


def to_public(job: dict) -> dict:
    return {
        "job_id": job["id"],
        "status": job["status"],
        "workflow_id": job["workflow_id"],
        "prompt": job["prompt"],
        "seed": job["seed"],
        "cached": bool(job["cached"]),
        "image_url": job["image_url"],
    }