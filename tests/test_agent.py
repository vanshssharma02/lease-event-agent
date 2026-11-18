"""Unit tests for Milestone 6: LangGraph Agent, Storage, Retry Loop, and Notifications."""

import json
from pathlib import Path
import pytest

from app.config import settings
from app.db import init_db, get_connection
from app.audit import init_audit_table, get_run_trail, verify_chain
from app.seed import seed_database
from app.retrieval import get_chroma_client, index_all_in_window
from app.agent import run_agent, AgentState
from app.llm import generate_mock_memo


@pytest.fixture
def agent_test_env(tmp_path: Path):
    """Isolated environment with seeded database and indexed ChromaDB collection."""
    db_file = tmp_path / "test_agent.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    chroma_dir = tmp_path / "chroma_db"
    chroma_dir.mkdir(parents=True, exist_ok=True)

    init_db(db_file)
    init_audit_table(db_file)
    seed_database(db_path=db_file, data_dir=data_dir)

    client = get_chroma_client(chroma_dir)
    index_all_in_window(db_path=db_file, client=client, collection_name="test_agent_col")

    return db_file, data_dir, chroma_dir


def test_agent_happy_path(agent_test_env):
    db_file, _, chroma_dir = agent_test_env
    state = run_agent(
        lease_id="LSE-EXP-001",
        db_path=db_file,
        chroma_dir=chroma_dir,
        collection_name="test_agent_col",
    )

    assert state["status"] == "ROUTED_PENDING_APPROVAL"
    run_id = state["run_id"]

    # Verify inbox_items table
    conn = get_connection(db_file)
    cur = conn.cursor()
    cur.execute("SELECT * FROM inbox_items WHERE run_id = ?;", (run_id,))
    item = cur.fetchone()
    assert item is not None
    assert item["lease_id"] == "LSE-EXP-001"
    assert item["status"] == "pending_approval"
    assert item["low_confidence"] == 0

    # Verify agent_runs table
    cur.execute("SELECT * FROM agent_runs WHERE run_id = ?;", (run_id,))
    run_rec = cur.fetchone()
    assert run_rec is not None
    assert run_rec["status"] == "ROUTED_PENDING_APPROVAL"
    conn.close()

    # Verify audit trail sequence
    trail = get_run_trail(run_id, db_path=db_file)
    events = [e["event_type"] for e in trail]
    assert events == ["TRIGGER", "RETRIEVE", "INJECT_GUARD", "INFER", "VALIDATE", "ROUTE", "NOTIFY"]

    # Verify cryptographic integrity
    chain_res = verify_chain(db_path=db_file)
    assert chain_res["valid"] is True


def test_agent_validation_retry_loop_recovers(agent_test_env):
    """Inject a mock generator that fails validation on attempt 1, then succeeds on attempt 2."""
    db_file, _, chroma_dir = agent_test_env

    def mock_override_with_one_retry(prompt, ctx, attempt=1):
        if attempt == 1:
            # Generate memo with hallucinated rent (£999,999) to force validation failure
            memo_str = generate_mock_memo(prompt, ctx)
            data = json.loads(memo_str)
            data["passing_rent"]["amount"] = 999999.0
            return json.dumps(data)
        else:
            # Succeed on attempt 2
            return generate_mock_memo(prompt, ctx)

    state = run_agent(
        lease_id="LSE-BRK-002",
        db_path=db_file,
        chroma_dir=chroma_dir,
        collection_name="test_agent_col",
        mock_override_fn=mock_override_with_one_retry,
    )

    assert state["status"] == "ROUTED_PENDING_APPROVAL"
    assert state["attempt_count"] == 2

    # Check that audit log has two INFER and two VALIDATE entries
    trail = get_run_trail(state["run_id"], db_path=db_file)
    event_counts = {}
    for e in trail:
        event_counts[e["event_type"]] = event_counts.get(e["event_type"], 0) + 1

    assert event_counts["INFER"] == 2
    assert event_counts["VALIDATE"] == 2
    assert event_counts["ROUTE"] == 1


def test_agent_validation_rejection_on_retry_exhaustion(agent_test_env):
    """Inject a mock generator that always fails validation, leading to REJECTED_BY_VALIDATOR."""
    db_file, _, chroma_dir = agent_test_env

    def always_bad_mock(prompt, ctx, attempt=1):
        memo_str = generate_mock_memo(prompt, ctx)
        data = json.loads(memo_str)
        data["passing_rent"]["amount"] = 888888.0  # Invalid rent
        return json.dumps(data)

    state = run_agent(
        lease_id="LSE-EXP-001",
        db_path=db_file,
        chroma_dir=chroma_dir,
        collection_name="test_agent_col",
        mock_override_fn=always_bad_mock,
    )

    assert state["status"] == "REJECTED_BY_VALIDATOR"
    assert state["attempt_count"] == 2

    conn = get_connection(db_file)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM inbox_items WHERE run_id = ?;", (state["run_id"],))
    assert cur.fetchone()["c"] == 0

    cur.execute("SELECT status FROM agent_runs WHERE run_id = ?;", (state["run_id"],))
    assert cur.fetchone()["status"] == "REJECTED_BY_VALIDATOR"
    conn.close()


def test_agent_low_confidence_path(agent_test_env):
    """Test routing with low confidence flags (<0.6) and auto-notify suppression."""
    db_file, _, chroma_dir = agent_test_env

    def low_conf_mock(prompt, ctx, attempt=1):
        memo_str = generate_mock_memo(prompt, ctx)
        data = json.loads(memo_str)
        data["confidence_score"] = 0.45  # Low confidence
        return json.dumps(data)

    state = run_agent(
        lease_id="LSE-REV-003",
        db_path=db_file,
        chroma_dir=chroma_dir,
        collection_name="test_agent_col",
        mock_override_fn=low_conf_mock,
    )

    assert state["status"] == "ROUTED_PENDING_APPROVAL"
    assert state["low_confidence"] is True
    assert state["no_auto_notify"] is True

    # Check inbox item record
    conn = get_connection(db_file)
    cur = conn.cursor()
    cur.execute("SELECT low_confidence, confidence FROM inbox_items WHERE run_id = ?;", (state["run_id"],))
    row = cur.fetchone()
    assert row["low_confidence"] == 1
    assert row["confidence"] == 0.45
    conn.close()

    # Check audit log NOTIFY entry was skipped due to low confidence
    trail = get_run_trail(state["run_id"], db_path=db_file)
    notify_entries = [e for e in trail if e["event_type"] == "NOTIFY"]
    assert len(notify_entries) == 1
    assert notify_entries[0]["detail"]["status"] == "SKIPPED_LOW_CONFIDENCE"
