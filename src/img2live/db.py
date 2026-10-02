"""SQLite job store shared by the API and the GPU worker (WAL, one writer at a time)."""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  started_at REAL,
  finished_at REAL,
  delete_after REAL,
  status TEXT NOT NULL,            -- queued | running | done | failed | deleted
  stage TEXT NOT NULL DEFAULT 'queued',
  progress REAL NOT NULL DEFAULT 0,
  message TEXT NOT NULL DEFAULT '',
  prompt TEXT NOT NULL DEFAULT '',
  resolution INTEGER NOT NULL DEFAULT 1280,
  seed INTEGER NOT NULL DEFAULT 42,
  ip_hash TEXT NOT NULL DEFAULT '',
  gate_json TEXT,
  timings_json TEXT,
  result_json TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_ip ON jobs(ip_hash, created_at);
"""

JSON_COLS = ("gate_json", "timings_json", "result_json")


def new_job_id() -> str:
    return secrets.token_urlsafe(16)  # 128 bits: the id is the capability to view the job


class DB:
    def __init__(self, path: Path):
        self.path = str(path)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
        finally:
            c.close()

    @staticmethod
    def _row(r: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if r is None:
            return None
        d = dict(r)
        for k in JSON_COLS:
            if d.get(k):
                d[k] = json.loads(d[k])
        return d

    # -------------------------------------------------------------- API side
    def create(self, job_id: str, prompt: str, resolution: int, seed: int, ip_hash: str, gate: dict,
               retention_hours: float) -> None:
        now = time.time()
        with self._conn() as c:
            c.execute(
                "INSERT INTO jobs(id,created_at,updated_at,status,stage,prompt,resolution,seed,ip_hash,gate_json,delete_after)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, now, now, "queued", "queued", prompt, resolution, seed, ip_hash, json.dumps(gate),
                 now + retention_hours * 3600))

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            return self._row(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def queue_position(self, job_id: str) -> Optional[int]:
        """0 = running or next; None if not queued/running."""
        with self._conn() as c:
            r = c.execute("SELECT status, created_at FROM jobs WHERE id=?", (job_id,)).fetchone()
            if r is None or r["status"] not in ("queued", "running"):
                return None
            if r["status"] == "running":
                return 0
            n = c.execute("SELECT COUNT(*) FROM jobs WHERE (status='queued' AND created_at<?) OR status='running'",
                          (r["created_at"],)).fetchone()[0]
            return int(n)

    def counts(self) -> Dict[str, int]:
        with self._conn() as c:
            rows = c.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    def recent_by_ip(self, ip_hash: str, since: float) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM jobs WHERE ip_hash=? AND created_at>=? AND status!='deleted'",
                                 (ip_hash, since)).fetchone()[0])

    def active_count(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0])

    def mark_deleted(self, job_id: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE jobs SET status='deleted', updated_at=?, prompt='', ip_hash='', gate_json=NULL WHERE id=?",
                      (time.time(), job_id))

    def recent_durations(self, n: int = 5) -> List[float]:
        with self._conn() as c:
            rows = c.execute("SELECT started_at, finished_at FROM jobs WHERE status='done' AND started_at IS NOT NULL"
                             " AND finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT ?", (n,)).fetchall()
        return [r["finished_at"] - r["started_at"] for r in rows]

    # -------------------------------------------------------------- worker side
    def claim_next(self) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            r = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if r is None:
                c.execute("COMMIT")
                return None
            now = time.time()
            c.execute("UPDATE jobs SET status='running', stage='starting', started_at=?, updated_at=?, progress=0 WHERE id=?",
                      (now, now, r["id"]))
            c.execute("COMMIT")
            return self._row(c.execute("SELECT * FROM jobs WHERE id=?", (r["id"],)).fetchone())

    def update(self, job_id: str, **fields) -> None:
        for k in JSON_COLS:
            if k in fields and not isinstance(fields[k], (str, type(None))):
                fields[k] = json.dumps(fields[k], ensure_ascii=False)
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._conn() as c:
            c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))

    def requeue_stale(self, older_than_s: float = 3600 * 3) -> int:
        """Jobs left 'running' by a crashed worker go back to the queue (called at worker start)."""
        with self._conn() as c:
            cur = c.execute("UPDATE jobs SET status='queued', stage='queued', progress=0, message='worker restarted'"
                            " WHERE status='running'")
            return cur.rowcount

    def expired(self) -> List[str]:
        with self._conn() as c:
            rows = c.execute("SELECT id FROM jobs WHERE status IN ('done','failed') AND delete_after<?",
                             (time.time(),)).fetchall()
        return [r["id"] for r in rows]
