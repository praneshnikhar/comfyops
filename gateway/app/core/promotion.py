"""Promotion + canary rollout state for workflow versions (M3).

The champion baseline lives in `scoring/.gate_state` (gate pipeline output).
The gateway mirrors the *promoted* version per workflow so that:

  - POST /generate without a version uses the promoted (champion) version,
    NOT the newest file in the registry (a challenger must never serve
    production traffic silently).
  - A canary (challenger_version + weight) splits live traffic
    champion/challenger until the challenger is promoted or rolled back.

Storage: SQLite table `promotion`.
"""

import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "comfyops.db"
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_promotion() -> None:
    with _lock, _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS promotion (
                workflow_id TEXT PRIMARY KEY,
                promoted_version TEXT NOT NULL,
                canary_version TEXT,
                canary_weight REAL
            )
            """
        )


def get_state(workflow_id: str) -> dict:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM promotion WHERE workflow_id = ?", (workflow_id,)
        ).fetchone()
    if row is None:
        return {"workflow_id": workflow_id, "promoted_version": None, "canary": None}
    return {
        "workflow_id": workflow_id,
        "promoted_version": row["promoted_version"],
        "canary": (
            {"version": row["canary_version"], "weight": row["canary_weight"]}
            if row["canary_version"]
            else None
        ),
    }


def set_promoted(workflow_id: str, version: str) -> None:
    """Promote a version to champion. Also cancels any active canary."""
    with _lock, _conn() as conn:
        conn.execute(
            """
            INSERT INTO promotion (workflow_id, promoted_version, canary_version, canary_weight)
            VALUES (?, ?, NULL, NULL)
            ON CONFLICT(workflow_id) DO UPDATE SET
                promoted_version = excluded.promoted_version,
                canary_version = NULL,
                canary_weight = NULL
            """,
            (workflow_id, version),
        )


def set_canary(workflow_id: str, version: str, weight: float) -> None:
    weight = max(0.0, min(1.0, weight))
    with _lock, _conn() as conn:
        conn.execute(
            """
            INSERT INTO promotion (workflow_id, promoted_version, canary_version, canary_weight)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(workflow_id) DO UPDATE SET
                canary_version = excluded.canary_version,
                canary_weight = excluded.canary_weight
            """,
            (workflow_id, get_state(workflow_id)["promoted_version"] or "", version, weight),
        )


def clear_canary(workflow_id: str) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            "UPDATE promotion SET canary_version = NULL, canary_weight = NULL WHERE workflow_id = ?",
            (workflow_id,),
        )


def resolve_version(workflow_id: str, requested: str | None, default_version: str) -> tuple[str, str | None]:
    """Return (version_to_run, canary_routed).

    - requested version wins (explicit user override, no canary).
    - no request: promoted version if set, else registry default.
    - canary active: probabilistically route `weight` of unversioned traffic
      to the challenger (sampled here, at the gateway).
    """
    if requested:
        return requested, None
    import random

    state = get_state(workflow_id)
    if state["canary"] and random.random() < state["canary"]["weight"]:
        return state["canary"]["version"], state["canary"]["version"]
    return state["promoted_version"] or default_version, None