"""Unit and integration tests for Milestone 7: FastAPI Approvals Backend."""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import init_db
from app.audit import init_audit_table
from app.seed import seed_database
from app.retrieval import get_chroma_client, index_all_in_window
from app.api import app


@pytest.fixture
def client_env(tmp_path: Path):
    """Setup test client with populated database and indexed vector store."""
    db_file = tmp_path / "test_api.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    chroma_dir = tmp_path / "chroma_db"
    chroma_dir.mkdir(parents=True, exist_ok=True)

    # Point settings to temp dirs
    settings.DB_PATH = db_file
    settings.DATA_DIR = data_dir
    settings.CHROMA_PERSIST_DIR = chroma_dir

    init_db(db_file)
    init_audit_table(db_file)
    seed_database(db_path=db_file, data_dir=data_dir)

    chroma_client = get_chroma_client(chroma_dir)
    index_all_in_window(db_path=db_file, client=chroma_client, collection_name="lease_documents")

    client = TestClient(app)
    return client, db_file


def test_health_check(client_env):
    client, _ = client_env
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "llm_mode" in data


def test_trigger_and_inbox_flow(client_env):
    client, _ = client_env

    # 1. Trigger run for single lease
    resp = client.post("/agent/runs", json={"lease_id": "LSE-EXP-001"})
    assert resp.status_code == 201
    run_data = resp.json()
    assert run_data["triggered"] == 1
    run_id = run_data["runs"][0]["run_id"]
    assert run_id is not None

    # 2. Get inbox items
    inbox_resp = client.get("/inbox")
    assert inbox_resp.status_code == 200
    items = inbox_resp.json()
    assert len(items) >= 1
    matched = next((i for i in items if i["run_id"] == run_id), None)
    assert matched is not None
    assert matched["lease_id"] == "LSE-EXP-001"
    assert matched["status"] == "pending_approval"

    # 3. Get item detail
    detail_resp = client.get(f"/inbox/{run_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert "memo" in detail
    assert "cited_chunks" in detail
    assert len(detail["cited_chunks"]) > 0
    assert detail["memo"]["tenant_name"]["value"] == "Apex Logistics Ltd"


def test_approve_flow_and_double_decision_conflict(client_env):
    client, _ = client_env

    # Trigger run
    run_resp = client.post("/agent/runs", json={"lease_id": "LSE-BRK-002"})
    run_id = run_resp.json()["runs"][0]["run_id"]

    # Approve item
    appr_resp = client.post(
        f"/inbox/{run_id}/approve",
        json={"approver_id": "AM_JANE_DOE", "comment": "Approved following lease terms verification."},
    )
    assert appr_resp.status_code == 200
    assert appr_resp.json()["status"] == "approved"

    # Double decision returns 409 Conflict
    conflict_resp = client.post(
        f"/inbox/{run_id}/approve",
        json={"approver_id": "AM_JANE_DOE"},
    )
    assert conflict_resp.status_code == 409

    # Rejection on decided item also returns 409
    reject_conflict = client.post(
        f"/inbox/{run_id}/reject",
        json={"approver_id": "AM_JANE_DOE", "comment": "Too late"},
    )
    assert reject_conflict.status_code == 409


def test_reject_validation_and_flow(client_env):
    client, _ = client_env

    # Trigger run
    run_resp = client.post("/agent/runs", json={"lease_id": "LSE-REV-003"})
    run_id = run_resp.json()["runs"][0]["run_id"]

    # Missing comment returns 422 Unprocessable Entity
    bad_resp = client.post(
        f"/inbox/{run_id}/reject",
        json={"approver_id": "AM_ALEX_SMITH", "comment": "   "},
    )
    assert bad_resp.status_code == 422

    # Valid rejection with comment
    good_resp = client.post(
        f"/inbox/{run_id}/reject",
        json={"approver_id": "AM_ALEX_SMITH", "comment": "Rent review figures need surveyor reassessment."},
    )
    assert good_resp.status_code == 200
    assert good_resp.json()["status"] == "rejected"


def test_revise_creates_linked_new_run(client_env):
    client, _ = client_env

    # Trigger initial run
    run_resp = client.post("/agent/runs", json={"lease_id": "LSE-EXP-001"})
    old_run_id = run_resp.json()["runs"][0]["run_id"]

    # Request revision with comment
    revise_resp = client.post(
        f"/inbox/{old_run_id}/revise",
        json={"approver_id": "AM_MORGAN_TAYLOR", "comment": "Please check whether tenant requested an extension."},
    )
    assert revise_resp.status_code == 200
    data = revise_resp.json()
    assert data["status"] == "revision_requested"
    assert data["old_run_id"] == old_run_id
    new_run_id = data["new_run_id"]
    assert new_run_id is not None
    assert new_run_id != old_run_id

    # Verify old item marked revision_requested
    old_detail = client.get(f"/inbox/{old_run_id}").json()
    assert old_detail["status"] == "revision_requested"


def test_audit_export_and_chain_verification_endpoint(client_env):
    client, _ = client_env

    # Trigger run to add entries to audit log
    client.post("/agent/runs", json={"lease_id": "LSE-EXP-001"})

    resp = client.get("/audit/export")
    assert resp.status_code == 200
    export_data = resp.json()

    assert export_data["chain_verification"]["valid"] is True
    assert export_data["entry_count"] > 0
    assert len(export_data["trail"]) == export_data["entry_count"]


def test_demo_injection_endpoint_produces_quarantine(client_env):
    client, _ = client_env

    resp = client.post("/demo/injection")
    assert resp.status_code == 200
    data = resp.json()

    assert data["demo_lease_id"] == "LSE-DEMO-INJ-001"
    run_id = data["run_id"]
    assert run_id is not None

    # Verify quarantine flags are present
    assert len(data["quarantined_chunk_ids"]) > 0

    # Verify detail in inbox shows quarantined chunk and details
    detail = client.get(f"/inbox/{run_id}").json()
    assert len(detail["quarantined_chunks"]) > 0
    assert any("role reassignment" in str(q["reasons"]).lower() or "override" in str(q["reasons"]).lower() for q in detail["quarantined_chunks"])
