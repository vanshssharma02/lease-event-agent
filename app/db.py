"""Database management module for lease-event-agent."""

import sqlite3
from pathlib import Path
from typing import Optional, Union
from app.config import settings


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS asset_register (
    asset_id TEXT PRIMARY KEY,
    asset_name TEXT NOT NULL,
    holding_spv TEXT NOT NULL,
    portfolio TEXT NOT NULL,
    asset_manager TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lease_register (
    lease_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    tenant TEXT NOT NULL,
    expiry_date TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('EXPIRY', 'BREAK', 'RENT_REVIEW')),
    passing_rent REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'GBP',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    is_demo INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (asset_id) REFERENCES asset_register(asset_id)
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    lease_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    FOREIGN KEY (lease_id) REFERENCES lease_register(lease_id)
);

CREATE INDEX IF NOT EXISTS idx_lease_expiry ON lease_register(expiry_date);
CREATE INDEX IF NOT EXISTS idx_lease_asset ON lease_register(asset_id);
CREATE INDEX IF NOT EXISTS idx_docs_lease ON documents(lease_id);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    lease_id TEXT NOT NULL,
    status TEXT NOT NULL,
    memo_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    parent_run_id TEXT
);

CREATE TABLE IF NOT EXISTS inbox_items (
    run_id TEXT PRIMARY KEY,
    lease_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    memo_json TEXT NOT NULL,
    cited_chunks_json TEXT NOT NULL,
    quarantined_json TEXT NOT NULL DEFAULT '[]',
    urgency TEXT NOT NULL,
    confidence REAL NOT NULL,
    low_confidence INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending_approval' CHECK(status IN ('pending_approval', 'approved', 'rejected', 'revision_requested')),
    created_at TEXT NOT NULL,
    decided_by TEXT,
    decision_comment TEXT,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    notif_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    lease_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    channel TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_lease ON agent_runs(lease_id);
CREATE INDEX IF NOT EXISTS idx_inbox_status ON inbox_items(status);
CREATE INDEX IF NOT EXISTS idx_inbox_lease ON inbox_items(lease_id);
"""


def get_connection(db_path: Optional[Union[str, Path]] = None) -> sqlite3.Connection:
    """Obtain a SQLite connection with row factory configured to Row objects."""
    path = Path(db_path) if db_path else settings.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[Union[str, Path]] = None) -> None:
    """Initialize the SQLite database schema if tables do not exist."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.executescript(SCHEMA_SQL)
            # Safe migration for existing databases missing is_demo column
            try:
                conn.execute("ALTER TABLE lease_register ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0;")
            except sqlite3.OperationalError:
                pass  # Column already exists
    finally:
        conn.close()
