"""
Integration Service datastore.

A single SQLite file (own database, per NFR/spec: the Integration Service
must have its own datastore, never touch SIS/LMS databases directly).

Tables
------
id_mapping        Student <-> LMS User, Section <-> LMS Course mapping (NFR-05)
processed_events  idempotency ledger keyed by (event_id, source)        (NFR-01)
pending_queue      events waiting for retry / waiting on a dependency    (NFR-02/03)
audit_log          human-readable trail of every processing step        (NFR-04)
checkpoints        last polled timestamp per source, for polling mode
"""
from __future__ import annotations
import sqlite3
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from .config import settings

_DB_PATH = settings.INTEGRATION_DB_URL.replace("sqlite:///", "", 1)
# support both sqlite:////abs/path and sqlite:///rel/path
if settings.INTEGRATION_DB_URL.startswith("sqlite:////"):
    _DB_PATH = "/" + _DB_PATH.lstrip("/")
Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def init_db() -> None:
    with _lock, get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS id_mapping (
                entity_type TEXT NOT NULL,
                tenant TEXT NOT NULL,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (entity_type, tenant, source_id)
            );

            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT NOT NULL,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                payload TEXT,
                first_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                next_retry_at TEXT,
                PRIMARY KEY (event_id, source)
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT,
                event_type TEXT,
                source TEXT,
                target TEXT,
                int_code TEXT,
                action TEXT,
                status TEXT,
                detail TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checkpoints (
                source TEXT PRIMARY KEY,
                last_occurred_at TEXT
            );
            """
        )
        conn.commit()


# ---------------------------------------------------------------- mapping --
def get_mapping(entity_type: str, tenant: str, source_id: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT target_id FROM id_mapping WHERE entity_type=? AND tenant=? AND source_id=?",
            (entity_type, tenant, source_id),
        ).fetchone()
        return row["target_id"] if row else None


def set_mapping(entity_type: str, tenant: str, source_id: str, target_id: str) -> None:
    with _lock, get_conn() as conn:
        conn.execute(
            """INSERT INTO id_mapping(entity_type, tenant, source_id, target_id, updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(entity_type, tenant, source_id)
               DO UPDATE SET target_id=excluded.target_id, updated_at=excluded.updated_at""",
            (entity_type, tenant, source_id, str(target_id), now_iso()),
        )
        conn.commit()


def all_mappings(entity_type: Optional[str] = None) -> list[dict]:
    with get_conn() as conn:
        if entity_type:
            rows = conn.execute("SELECT * FROM id_mapping WHERE entity_type=?", (entity_type,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM id_mapping").fetchall()
        return [dict(r) for r in rows]


# ------------------------------------------------------------ idempotency --
def get_event(event_id: str, source: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM processed_events WHERE event_id=? AND source=?", (event_id, source)
        ).fetchone()


def upsert_event(
    event_id: str,
    source: str,
    event_type: str,
    status: str,
    payload: dict,
    retry_count: int = 0,
    last_error: Optional[str] = None,
    next_retry_at: Optional[str] = None,
) -> None:
    with _lock, get_conn() as conn:
        existing = conn.execute(
            "SELECT event_id FROM processed_events WHERE event_id=? AND source=?", (event_id, source)
        ).fetchone()
        ts = now_iso()
        if existing:
            conn.execute(
                """UPDATE processed_events
                   SET status=?, retry_count=?, last_error=?, updated_at=?, next_retry_at=?
                   WHERE event_id=? AND source=?""",
                (status, retry_count, last_error, ts, next_retry_at, event_id, source),
            )
        else:
            conn.execute(
                """INSERT INTO processed_events
                   (event_id, source, event_type, status, retry_count, last_error, payload,
                    first_seen_at, updated_at, next_retry_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (event_id, source, event_type, status, retry_count, last_error,
                 json.dumps(payload, default=str), ts, ts, next_retry_at),
            )
        conn.commit()


def pending_events(limit: int = 200) -> list[sqlite3.Row]:
    """Events in PENDING status whose next_retry_at has passed (or is null)."""
    with get_conn() as conn:
        ts = now_iso()
        return conn.execute(
            """SELECT * FROM processed_events
               WHERE status='PENDING' AND (next_retry_at IS NULL OR next_retry_at <= ?)
               ORDER BY updated_at ASC LIMIT ?""",
            (ts, limit),
        ).fetchall()


# -------------------------------------------------------------- audit log --
def audit(
    event_id: Optional[str],
    event_type: Optional[str],
    source: Optional[str],
    target: Optional[str],
    int_code: Optional[str],
    action: str,
    status: str,
    detail: str = "",
) -> None:
    with _lock, get_conn() as conn:
        conn.execute(
            """INSERT INTO audit_log(event_id, event_type, source, target, int_code, action, status, detail, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (event_id, event_type, source, target, int_code, action, status, detail, now_iso()),
        )
        conn.commit()


def list_audit(limit: int = 200, event_id: Optional[str] = None, int_code: Optional[str] = None) -> list[dict]:
    with get_conn() as conn:
        q = "SELECT * FROM audit_log"
        clauses, args = [], []
        if event_id:
            clauses.append("event_id=?"); args.append(event_id)
        if int_code:
            clauses.append("int_code=?"); args.append(int_code)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]


# -------------------------------------------------------------- checkpoint --
def get_checkpoint(source: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute("SELECT last_occurred_at FROM checkpoints WHERE source=?", (source,)).fetchone()
        return row["last_occurred_at"] if row else None


def set_checkpoint(source: str, value: str) -> None:
    with _lock, get_conn() as conn:
        conn.execute(
            """INSERT INTO checkpoints(source, last_occurred_at) VALUES(?,?)
               ON CONFLICT(source) DO UPDATE SET last_occurred_at=excluded.last_occurred_at""",
            (source, value),
        )
        conn.commit()


def stats() -> dict[str, Any]:
    with get_conn() as conn:
        def count(q, *a):
            return conn.execute(q, a).fetchone()[0]
        return {
            "mappings": count("SELECT COUNT(*) FROM id_mapping"),
            "events_done": count("SELECT COUNT(*) FROM processed_events WHERE status='DONE'"),
            "events_pending": count("SELECT COUNT(*) FROM processed_events WHERE status='PENDING'"),
            "events_failed": count("SELECT COUNT(*) FROM processed_events WHERE status='FAILED'"),
            "audit_entries": count("SELECT COUNT(*) FROM audit_log"),
        }
