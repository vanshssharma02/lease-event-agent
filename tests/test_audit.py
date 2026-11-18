"""Unit tests for Milestone 5: Append-only hash-chained audit log."""

import sqlite3
from pathlib import Path
import pytest

from app.audit import (
    init_audit_table,
    append_entry,
    get_run_trail,
    export_all,
    verify_chain,
    GENESIS_HASH,
)


@pytest.fixture
def temp_audit_db(tmp_path: Path) -> Path:
    """Fixture providing a temporary SQLite database for audit log testing."""
    db_file = tmp_path / "test_audit.db"
    init_audit_table(db_file)
    return db_file


def test_append_and_chain_linkage(temp_audit_db):
    # Append first entry (genesis link)
    e1 = append_entry(
        event_type="TRIGGER",
        run_id="run-001",
        detail={"lease_id": "LSE-EXP-001"},
        db_path=temp_audit_db,
    )
    assert e1["prev_hash"] == GENESIS_HASH
    assert len(e1["entry_hash"]) == 64

    # Append second entry
    e2 = append_entry(
        event_type="RETRIEVE",
        run_id="run-001",
        input_hash=e1["entry_hash"],
        detail={"chunks_count": 5},
        db_path=temp_audit_db,
    )
    assert e2["prev_hash"] == e1["entry_hash"]

    # Append third entry (different run)
    e3 = append_entry(
        event_type="TRIGGER",
        run_id="run-002",
        detail={"lease_id": "LSE-BRK-002"},
        db_path=temp_audit_db,
    )
    assert e3["prev_hash"] == e2["entry_hash"]

    # Verify chain
    result = verify_chain(temp_audit_db)
    assert result["valid"] is True
    assert result["checked"] == 3
    assert result["first_bad_entry"] is None


def test_blocked_update_and_delete_by_triggers(temp_audit_db):
    append_entry(
        event_type="TRIGGER",
        run_id="run-001",
        detail={"status": "initial"},
        db_path=temp_audit_db,
    )

    conn = sqlite3.connect(str(temp_audit_db))
    # Test blocked UPDATE
    with pytest.raises(sqlite3.DatabaseError, match="UPDATE operations are strictly prohibited"):
        conn.execute("UPDATE audit_log SET detail = '{\"status\": \"tampered\"}';")

    # Test blocked DELETE
    with pytest.raises(sqlite3.DatabaseError, match="DELETE operations are strictly prohibited"):
        conn.execute("DELETE FROM audit_log WHERE run_id = 'run-001';")

    conn.close()


def test_tamper_detection_flags_exact_entry(temp_audit_db):
    e1 = append_entry(event_type="TRIGGER", run_id="run-001", db_path=temp_audit_db)
    e2 = append_entry(event_type="INFER", run_id="run-001", db_path=temp_audit_db)
    e3 = append_entry(event_type="ROUTE", run_id="run-001", db_path=temp_audit_db)

    # Chain initially valid
    assert verify_chain(temp_audit_db)["valid"] is True

    # Drop trigger in fresh connection to simulate malicious low-level DB tampering
    conn = sqlite3.connect(str(temp_audit_db))
    conn.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_update;")
    conn.execute(
        "UPDATE audit_log SET detail = '{\"tampered\": true}' WHERE entry_id = ?;",
        (e2["entry_id"],),
    )
    conn.commit()
    conn.close()

    # verify_chain must detect tampering and flag e2
    result = verify_chain(temp_audit_db)
    assert result["valid"] is False
    assert result["first_bad_entry"] == e2["entry_id"]
    assert "Content tampering detected" in result["reason"]


def test_get_run_trail_and_export_all(temp_audit_db):
    append_entry(event_type="TRIGGER", run_id="run-A", db_path=temp_audit_db)
    append_entry(event_type="INFER", run_id="run-A", db_path=temp_audit_db)
    append_entry(event_type="TRIGGER", run_id="run-B", db_path=temp_audit_db)

    trail_a = get_run_trail("run-A", db_path=temp_audit_db)
    assert len(trail_a) == 2
    assert [e["event_type"] for e in trail_a] == ["TRIGGER", "INFER"]

    all_entries = export_all(temp_audit_db)
    assert len(all_entries) == 3
