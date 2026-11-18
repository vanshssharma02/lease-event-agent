"""Unit and integration tests for Milestone 9 bug fixes and isolation rules.

Verifies:
  1. Event deduplication via API and batch runner
  2. Force override on deduplication
  3. Supersede-on-revise workflow and run linkage
  4. Demo lease isolation from in-window queries and standard batch runs
  5. Demo endpoint idempotency
  6. Temporary environment isolation
"""

import os
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import init_db, get_connection
from app.audit import init_audit_table
from app.seed import seed_database, get_leases_in_window
from app.retrieval import get_chroma_client, index_all_in_window
from app.scheduler import check_active_event_exists, run_in_window_leases
from app.api import app


@pytest.fixture
def isolated_env():
    """Create a completely isolated temporary DB, chroma store, and data dir."""
    orig_db = settings.DB_PATH
    orig_chroma = settings.CHROMA_PERSIST_DIR
    orig_data = settings.DATA_DIR
    orig_notif = settings.NOTIFICATIONS_LOG_PATH

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        temp_dir = Path(td)
        test_db = temp_dir / "test_lease_register.db"
        test_chroma = temp_dir / "test_chroma_db"
        test_data = temp_dir / "data"
        test_data.mkdir(parents=True, exist_ok=True)
        test_notif = temp_dir / "notifications.log"

        settings.DB_PATH = test_db
        settings.CHROMA_PERSIST_DIR = test_chroma
        settings.DATA_DIR = test_data
        settings.NOTIFICATIONS_LOG_PATH = test_notif
        os.environ["DB_PATH"] = str(test_db)
        os.environ["CHROMA_PERSIST_DIR"] = str(test_chroma)
        os.environ["DATA_DIR"] = str(test_data)
        os.environ["NOTIFICATIONS_LOG_PATH"] = str(test_notif)

        init_db(test_db)
        init_audit_table(test_db)
        seed_database(db_path=test_db, data_dir=test_data)
        chroma_client = get_chroma_client(test_chroma)
        index_all_in_window(db_path=test_db, client=chroma_client)

        client = TestClient(app)

        yield {
            "client": client,
            "db_path": test_db,
            "chroma_dir": test_chroma,
            "data_dir": test_data,
        }

        # Restore settings
        settings.DB_PATH = orig_db
        settings.CHROMA_PERSIST_DIR = orig_chroma
        settings.DATA_DIR = orig_data
        settings.NOTIFICATIONS_LOG_PATH = orig_notif
        os.environ["DB_PATH"] = str(orig_db)
        os.environ["CHROMA_PERSIST_DIR"] = str(orig_chroma)
        os.environ["DATA_DIR"] = str(orig_data)
        os.environ["NOTIFICATIONS_LOG_PATH"] = str(orig_notif)


def test_batch_and_api_deduplication(isolated_env):
    """Verify duplicate runs for the same lease event are skipped across batch and single runs."""
    client = isolated_env["client"]

    # 1. First batch run triggers 3 leases
    resp1 = client.post("/agent/runs")
    assert resp1.status_code == 201
    data1 = resp1.json()
    assert data1["triggered"] == 3
    assert len(data1["skipped"]) == 0

    # 2. Second batch run triggers 0 and skips all 3
    resp2 = client.post("/agent/runs")
    assert resp2.status_code == 201
    data2 = resp2.json()
    assert data2["triggered"] == 0
    assert len(data2["skipped"]) == 3
    assert all("Active item already exists" in s["reason"] for s in data2["skipped"])

    # 3. Targeted run for an active lease without force is skipped
    resp3 = client.post("/agent/runs", json={"lease_id": "LSE-EXP-001", "force": False})
    assert resp3.status_code == 201
    data3 = resp3.json()
    assert data3["triggered"] == 0
    assert len(data3["skipped"]) == 1

    # 4. Targeted run with force: true bypasses deduplication check
    resp4 = client.post("/agent/runs", json={"lease_id": "LSE-EXP-001", "force": True})
    assert resp4.status_code == 201
    data4 = resp4.json()
    assert data4["triggered"] == 1
    assert len(data4["skipped"]) == 0


def test_supersede_on_revise_workflow(isolated_env):
    """Verify revision request marks old item revision_requested and creates linked new item."""
    client = isolated_env["client"]

    # Trigger batch run
    client.post("/agent/runs")

    # Get pending items
    items = client.get("/inbox").json()
    assert len(items) >= 1
    target = items[0]
    run_id = target["run_id"]
    lease_id = target["lease_id"]

    # Request revision
    resp_rev = client.post(
        f"/inbox/{run_id}/revise",
        json={"approver_id": "AM-TESTER", "comment": "Review Dilapidations figure."},
    )
    assert resp_rev.status_code == 200
    rev_data = resp_rev.json()
    assert rev_data["status"] == "revision_requested"
    assert rev_data["old_run_id"] == run_id
    new_run_id = rev_data["new_run_id"]
    assert new_run_id is not None
    assert new_run_id != run_id

    # Verify old item status
    old_detail = client.get(f"/inbox/{run_id}").json()
    assert old_detail["status"] == "revision_requested"
    assert old_detail["decided_by"] == "AM-TESTER"

    # Verify new item is pending
    new_detail = client.get(f"/inbox/{new_run_id}").json()
    assert new_detail["status"] == "pending_approval"
    assert new_detail["lease_id"] == lease_id


def test_demo_isolation_from_in_window_and_batch(isolated_env):
    """Verify demo lease LSE-DEMO-INJ-001 is completely excluded from in-window and batch queries."""
    client = isolated_env["client"]
    db_path = isolated_env["db_path"]

    # Run demo endpoint to insert demo lease
    resp_demo = client.post("/demo/injection")
    assert resp_demo.status_code == 200

    # Verify get_leases_in_window excludes it
    in_window = get_leases_in_window(days=180, db_path=db_path)
    assert len(in_window) == 3
    assert all(l["lease_id"] != "LSE-DEMO-INJ-001" for l in in_window)

    # Verify run_in_window_leases excludes it
    batch_res = run_in_window_leases(days=180, force=True, db_path=db_path)
    assert len(batch_res) == 3
    assert all(r["lease_id"] != "LSE-DEMO-INJ-001" for r in batch_res)


def test_demo_endpoint_idempotency(isolated_env):
    """Verify multiple executions of /demo/injection replace rather than duplicate demo inbox items."""
    client = isolated_env["client"]

    # Run 1
    resp1 = client.post("/demo/injection")
    assert resp1.status_code == 200
    demo_items1 = [it for it in client.get("/inbox").json() if it.get("is_demo") is True]
    assert len(demo_items1) == 1

    # Run 2
    resp2 = client.post("/demo/injection")
    assert resp2.status_code == 200
    demo_items2 = [it for it in client.get("/inbox").json() if it.get("is_demo") is True]
    assert len(demo_items2) == 1
    assert demo_items2[0]["lease_id"] == "LSE-DEMO-INJ-001"
