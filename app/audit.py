"""Append-only, hash-chained cryptographic audit log for lease-event-agent.

Maintains an immutable ledger in SQLite with tamper-evident SHA-256 hash chaining,
atomic exclusive append transactions, and SQLite triggers blocking UPDATE/DELETE.
"""

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Union

from app.config import settings
from app.db import get_connection

GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

AUDIT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    seq_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id TEXT UNIQUE NOT NULL,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN (
        'TRIGGER', 'RETRIEVE', 'INJECT_GUARD', 'INFER',
        'VALIDATE', 'ROUTE', 'NOTIFY', 'HUMAN_DECISION'
    )),
    run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    model_version TEXT,
    prompt_hash TEXT,
    input_hash TEXT,
    output_hash TEXT,
    user_id TEXT,
    decision TEXT CHECK(decision IS NULL OR decision IN ('APPROVED', 'REJECTED', 'REVISION_REQUESTED')),
    detail TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_log(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_entry_hash ON audit_log(entry_hash);

CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'UPDATE operations are strictly prohibited on append-only audit_log.');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'DELETE operations are strictly prohibited on append-only audit_log.');
END;
"""


def init_audit_table(db_path: Optional[Union[str, Path]] = None) -> None:
    """Initialize the audit_log schema and protection triggers."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.executescript(AUDIT_SCHEMA_SQL)
    finally:
        conn.close()


def hash_payload(data: Any) -> Optional[str]:
    """Helper to compute deterministic SHA-256 for string, dict, or Pydantic models."""
    if data is None:
        return None
    if isinstance(data, str):
        content = data
    elif hasattr(data, "model_dump"):
        content = json.dumps(data.model_dump(), sort_keys=True, separators=(",", ":"))
    elif isinstance(data, (dict, list)):
        content = json.dumps(data, sort_keys=True, separators=(",", ":"))
    else:
        content = str(data)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def compute_canonical_entry_hash(
    entry_id: str,
    prev_hash: str,
    timestamp: str,
    event_type: str,
    run_id: str,
    agent_id: str,
    model_version: Optional[str],
    prompt_hash: Optional[str],
    input_hash: Optional[str],
    output_hash: Optional[str],
    user_id: Optional[str],
    decision: Optional[str],
    detail: Union[str, Dict[str, Any]],
) -> str:
    """Compute canonical SHA-256 over all fields including prev_hash."""
    if isinstance(detail, str):
        try:
            detail_obj = json.loads(detail)
        except Exception:
            detail_obj = {"raw": detail}
    elif isinstance(detail, dict):
        detail_obj = detail
    else:
        detail_obj = {"raw": str(detail)}

    canonical = {
        "agent_id": agent_id,
        "decision": decision,
        "detail": detail_obj,
        "entry_id": entry_id,
        "event_type": event_type,
        "input_hash": input_hash,
        "model_version": model_version,
        "output_hash": output_hash,
        "prev_hash": prev_hash,
        "prompt_hash": prompt_hash,
        "run_id": run_id,
        "timestamp": timestamp,
        "user_id": user_id,
    }
    canonical_bytes = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


def append_entry(
    event_type: str,
    run_id: str,
    agent_id: str = "lease-event-agent-v1",
    model_version: Optional[str] = None,
    prompt_hash: Optional[str] = None,
    input_hash: Optional[str] = None,
    output_hash: Optional[str] = None,
    user_id: Optional[str] = None,
    decision: Optional[str] = None,
    detail: Optional[Union[Dict[str, Any], str]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Atomically append a hash-chained entry to the audit log under an exclusive transaction."""
    init_audit_table(db_path)
    entry_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    detail_str = (
        json.dumps(detail, sort_keys=True, separators=(",", ":"))
        if isinstance(detail, (dict, list))
        else (detail or "{}")
    )

    conn = get_connection(db_path)
    try:
        # Acquire immediate exclusive lock to prevent chain forks
        conn.execute("BEGIN IMMEDIATE;")
        cur = conn.cursor()

        # Fetch hash of latest entry in chain
        cur.execute("SELECT entry_hash FROM audit_log ORDER BY seq_id DESC LIMIT 1;")
        last_row = cur.fetchone()
        prev_hash = last_row["entry_hash"] if last_row else GENESIS_HASH

        entry_hash = compute_canonical_entry_hash(
            entry_id=entry_id,
            prev_hash=prev_hash,
            timestamp=timestamp,
            event_type=event_type,
            run_id=run_id,
            agent_id=agent_id,
            model_version=model_version,
            prompt_hash=prompt_hash,
            input_hash=input_hash,
            output_hash=output_hash,
            user_id=user_id,
            decision=decision,
            detail=detail_str,
        )

        query = """
            INSERT INTO audit_log (
                entry_id, prev_hash, entry_hash, timestamp, event_type,
                run_id, agent_id, model_version, prompt_hash,
                input_hash, output_hash, user_id, decision, detail
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        cur.execute(
            query,
            (
                entry_id,
                prev_hash,
                entry_hash,
                timestamp,
                event_type,
                run_id,
                agent_id,
                model_version,
                prompt_hash,
                input_hash,
                output_hash,
                user_id,
                decision,
                detail_str,
            ),
        )
        conn.commit()

        return {
            "entry_id": entry_id,
            "prev_hash": prev_hash,
            "entry_hash": entry_hash,
            "timestamp": timestamp,
            "event_type": event_type,
            "run_id": run_id,
            "agent_id": agent_id,
            "model_version": model_version,
            "prompt_hash": prompt_hash,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "user_id": user_id,
            "decision": decision,
            "detail": json.loads(detail_str),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_run_trail(run_id: str, db_path: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]:
    """Retrieve full audit log history for a specific run_id ordered by insertion."""
    init_audit_table(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM audit_log WHERE run_id = ? ORDER BY seq_id ASC;",
            (run_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            try:
                r["detail"] = json.loads(r["detail"])
            except Exception:
                pass
        return rows
    finally:
        conn.close()


def export_all(db_path: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]:
    """Export the entire audit log ordered from genesis to head."""
    init_audit_table(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM audit_log ORDER BY seq_id ASC;")
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            try:
                r["detail"] = json.loads(r["detail"])
            except Exception:
                pass
        return rows
    finally:
        conn.close()


def verify_chain(db_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Verify cryptographic integrity of the entire audit log chain.

    Validates:
      1. First entry links to GENESIS_HASH.
      2. Every subsequent entry's prev_hash matches the preceding entry's entry_hash.
      3. Every entry's canonical SHA-256 matches its recorded entry_hash.

    Returns:
      {
        "valid": bool,
        "checked": int,
        "first_bad_entry": Optional[str],
        "reason": Optional[str]
      }
    """
    init_audit_table(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM audit_log ORDER BY seq_id ASC;")
        rows = cur.fetchall()

        if not rows:
            return {"valid": True, "checked": 0, "first_bad_entry": None, "reason": "Chain empty"}

        expected_prev = GENESIS_HASH
        for idx, row in enumerate(rows):
            entry_id = row["entry_id"]
            row_prev = row["prev_hash"]
            row_hash = row["entry_hash"]

            # 1. Verify prev_hash linkage
            if row_prev != expected_prev:
                return {
                    "valid": False,
                    "checked": idx,
                    "first_bad_entry": entry_id,
                    "reason": f"Hash linkage broken at entry '{entry_id}': expected prev_hash '{expected_prev}', found '{row_prev}'",
                }

            # 2. Verify canonical content hash
            computed = compute_canonical_entry_hash(
                entry_id=entry_id,
                prev_hash=row_prev,
                timestamp=row["timestamp"],
                event_type=row["event_type"],
                run_id=row["run_id"],
                agent_id=row["agent_id"],
                model_version=row["model_version"],
                prompt_hash=row["prompt_hash"],
                input_hash=row["input_hash"],
                output_hash=row["output_hash"],
                user_id=row["user_id"],
                decision=row["decision"],
                detail=row["detail"],
            )

            if computed != row_hash:
                return {
                    "valid": False,
                    "checked": idx,
                    "first_bad_entry": entry_id,
                    "reason": f"Content tampering detected at entry '{entry_id}': recorded '{row_hash}', computed '{computed}'",
                }

            expected_prev = row_hash

        return {"valid": True, "checked": len(rows), "first_bad_entry": None, "reason": None}
    finally:
        conn.close()
