"""End-to-End Automated Smoke Test for lease-event-agent.

Executes an isolated integration walkthrough across all API endpoints in a fresh
temporary environment (temporary SQLite database, temporary Chroma collection,
and isolated audit log), verifying:
  1. System health check
  2. Batch agent trigger over in-window leases (asserts 3 pending items created)
  3. Batch deduplication (asserts 2nd trigger creates 0 new items and 3 skipped)
  4. Demo isolation (asserts demo lease excluded from batch and in-window queries)
  5. Detailed memo inspection and citation integrity
  6. Decision workflows (Approval, 409 Conflict, 422 Reject Validation, Rejection)
  7. Revision request superseding old item and spawning linked new run
  8. Prompt injection simulation & demo endpoint idempotency
  9. Full cryptographic audit log chain verification
"""

import os
import sys
import tempfile
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app.config import settings
from app.api import app
from app.db import init_db, get_connection
from app.audit import init_audit_table
from app.seed import seed_database, get_leases_in_window
from app.retrieval import get_chroma_client, index_all_in_window


def run_smoke_test():
    print("=" * 78)
    print("  LEASE-EVENT-AGENT: AUTOMATED END-TO-END SMOKE TEST (ISOLATED)")
    print("=" * 78)

    # Save original settings paths to restore after smoke test
    orig_db = settings.DB_PATH
    orig_chroma = settings.CHROMA_PERSIST_DIR
    orig_data = settings.DATA_DIR
    orig_notif = settings.NOTIFICATIONS_LOG_PATH

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        temp_dir = Path(td)
        smoke_db = temp_dir / "smoke_lease_register.db"
        smoke_chroma = temp_dir / "smoke_chroma_db"
        smoke_data = temp_dir / "data"
        smoke_data.mkdir(parents=True, exist_ok=True)
        smoke_notif = temp_dir / "notifications.log"

        # Override settings and environment for strict isolation
        settings.DB_PATH = smoke_db
        settings.CHROMA_PERSIST_DIR = smoke_chroma
        settings.DATA_DIR = smoke_data
        settings.NOTIFICATIONS_LOG_PATH = smoke_notif
        os.environ["DB_PATH"] = str(smoke_db)
        os.environ["CHROMA_PERSIST_DIR"] = str(smoke_chroma)
        os.environ["DATA_DIR"] = str(smoke_data)
        os.environ["NOTIFICATIONS_LOG_PATH"] = str(smoke_notif)

        try:
            print(f"\n[Setup] Initializing isolated test environment in {temp_dir}...")
            init_db(smoke_db)
            init_audit_table(smoke_db)
            seed_database(db_path=smoke_db, data_dir=smoke_data)
            chroma_client = get_chroma_client(smoke_chroma)
            index_all_in_window(db_path=smoke_db, client=chroma_client)

            client = TestClient(app)

            # Step 1: Health check
            print("\n[Step 1/9] Checking system health endpoint...")
            resp = client.get("/health")
            assert resp.status_code == 200, f"Health check failed: {resp.text}"
            health = resp.json()
            print(f"  --> Health status: {health['status']}, LLM Mode: {health['llm_mode']}")
            assert health["status"] in ("healthy", "ok")

            # Step 2: Trigger agent batch run #1
            print("\n[Step 2/9] Triggering first agent batch run for all in-window leases...")
            resp = client.post("/agent/runs")
            assert resp.status_code == 201, f"Agent trigger failed: {resp.text}"
            runs_res = resp.json()
            print(f"  --> Triggered runs: {runs_res['triggered']}, Skipped: {len(runs_res.get('skipped', []))}")
            assert runs_res["triggered"] == 3, f"Expected exactly 3 triggered runs, got {runs_res['triggered']}"
            assert len(runs_res.get("skipped", [])) == 0, f"Expected 0 skipped on first run, got {len(runs_res['skipped'])}"

            # Step 3: Query pending inbox items (must be exactly 3 non-demo items)
            print("\n[Step 3/9] Verifying pending approvals in inbox after 1st batch...")
            resp = client.get("/inbox")
            assert resp.status_code == 200, f"Inbox fetch failed: {resp.text}"
            items = resp.json()
            print(f"  --> Pending items in inbox: {len(items)}")
            assert len(items) == 3, f"Expected exactly 3 pending items after first run, found {len(items)}"
            for it in items:
                assert not it.get("is_demo", False), f"Demo lease leaked into standard inbox: {it['lease_id']}"
                print(f"      - Run `{it['run_id'][:8]}...` | {it['lease_id']} ({it['event_type']}) | Tenant: {it['tenant']}")

            # Step 4: Trigger second batch run (must create ZERO new items)
            print("\n[Step 4/9] Triggering second batch run to test event-level deduplication...")
            resp2 = client.post("/agent/runs")
            assert resp2.status_code == 201, f"Second agent trigger failed: {resp2.text}"
            runs_res_2 = resp2.json()
            print(f"  --> Second run triggered: {runs_res_2['triggered']}, Skipped: {len(runs_res_2.get('skipped', []))}")
            assert runs_res_2["triggered"] == 0, f"Expected 0 triggered on duplicate run, got {runs_res_2['triggered']}"
            assert len(runs_res_2.get("skipped", [])) == 3, f"Expected 3 skipped on duplicate run, got {len(runs_res_2['skipped'])}"

            # Confirm inbox count remains exactly 3
            resp_inbox2 = client.get("/inbox")
            items2 = resp_inbox2.json()
            assert len(items2) == 3, f"Inbox count changed after second batch trigger! Expected 3, got {len(items2)}"
            print("  --> Verified: 0 new items created; all 3 active leases correctly skipped.")

            # Step 5: Detailed memo inspection on Item 1
            item1 = items[0]
            run_id_1 = item1["run_id"]
            print(f"\n[Step 5/9] Inspecting detailed cited memo for run `{run_id_1[:8]}...` ({item1['lease_id']})...")
            resp = client.get(f"/inbox/{run_id_1}")
            assert resp.status_code == 200, f"Item detail fetch failed: {resp.text}"
            detail1 = resp.json()
            memo1 = detail1["memo"]
            print(f"  --> Tenant Name: {memo1['tenant_name']['value']} (Cited: {memo1['tenant_name']['source_chunk_id']})")
            print(f"  --> Passing Rent: £{memo1['passing_rent']['amount']:,.2f} (Cited: {memo1['passing_rent']['source_chunk_id']})")
            print(f"  --> Cited Chunks: {len(detail1['cited_chunks'])} document passages loaded")
            assert detail1["cited_chunks"], "Expected cited chunks in memo detail"

            # Step 6: Approve Item 1 & verify 409 conflict
            print(f"\n[Step 6/9] Approving memo 1 and verifying double-decision 409 conflict...")
            resp = client.post(f"/inbox/{run_id_1}/approve", json={"approver_id": "AM-JANE-DOE", "comment": "Terms confirmed."})
            assert resp.status_code == 200, f"Approval failed: {resp.text}"
            print(f"  --> Memo 1 approved successfully by AM-JANE-DOE")

            resp_conflict = client.post(f"/inbox/{run_id_1}/approve", json={"approver_id": "AM-JANE-DOE"})
            assert resp_conflict.status_code == 409, f"Expected 409 conflict, got {resp_conflict.status_code}"
            print(f"  --> Verified 409 Conflict on duplicate approval attempt")

            # Step 7: Reject validation (422) & Reject Item 2
            item2 = items[1]
            run_id_2 = item2["run_id"]
            print(f"\n[Step 7/9] Testing reject validation (422) and rejecting memo 2 ({item2['lease_id']})...")
            resp_empty_rej = client.post(f"/inbox/{run_id_2}/reject", json={"approver_id": "AM-ALEX-SMITH", "comment": "   "})
            assert resp_empty_rej.status_code == 422, f"Expected 422 on empty comment, got {resp_empty_rej.status_code}"
            print(f"  --> Verified 422 Unprocessable Entity on empty rejection comment")

            resp_rej = client.post(f"/inbox/{run_id_2}/reject", json={"approver_id": "AM-ALEX-SMITH", "comment": "Surveyor required."})
            assert resp_rej.status_code == 200, f"Rejection failed: {resp_rej.text}"
            print(f"  --> Memo 2 rejected successfully with mandatory comment recorded")

            # Step 8: Revision Request on Item 3 (supersede old item, spawn new run)
            item3 = items[2]
            run_id_3 = item3["run_id"]
            print(f"\n[Step 8/9] Requesting revision for memo 3 ({item3['lease_id']}) and verifying supersede linkage...")
            resp_rev = client.post(
                f"/inbox/{run_id_3}/revise",
                json={"approver_id": "AM-MORGAN-TAYLOR", "comment": "Check if statutory extension was served."},
            )
            assert resp_rev.status_code == 200, f"Revision request failed: {resp_rev.text}"
            rev_data = resp_rev.json()
            new_run_id = rev_data["new_run_id"]
            print(f"  --> Old run `{run_id_3[:8]}...` superseded; spawned linked new run `{new_run_id[:8]}...`")

            # Verify old item is marked revision_requested
            resp_old = client.get(f"/inbox/{run_id_3}")
            assert resp_old.status_code == 200
            assert resp_old.json()["status"] == "revision_requested"

            # Verify new item is pending in inbox
            resp_new = client.get(f"/inbox/{new_run_id}")
            assert resp_new.status_code == 200
            assert resp_new.json()["status"] == "pending_approval"
            print("  --> Verified: Old item superseded (revision_requested); new item pending.")

            # Step 9: Prompt Injection Demo Isolation & Idempotency
            print("\n[Step 9/9] Testing prompt injection demo isolation, idempotency, and audit chain...")
            # Verify demo lease is excluded from in-window query
            in_window = get_leases_in_window(db_path=smoke_db)
            assert all(l["lease_id"] != "LSE-DEMO-INJ-001" for l in in_window), "Demo lease leaked into get_leases_in_window!"

            # Run demo #1
            resp_inj = client.post("/demo/injection")
            assert resp_inj.status_code == 200, f"Injection demo failed: {resp_inj.text}"
            inj_data = resp_inj.json()
            print(f"  --> Adversarial injection lease `{inj_data['demo_lease_id']}` processed.")
            assert len(inj_data["quarantined_chunk_ids"]) > 0, "No chunks quarantined in injection demo!"

            # Check demo item in inbox has is_demo=True
            demo_items = [it for it in client.get("/inbox").json() if it.get("is_demo") is True]
            assert len(demo_items) == 1, f"Expected 1 demo item in inbox, found {len(demo_items)}"
            assert demo_items[0]["lease_id"] == "LSE-DEMO-INJ-001"

            # Run demo #2 (Idempotency test: replaces prior demo item rather than duplicating)
            resp_inj_2 = client.post("/demo/injection")
            assert resp_inj_2.status_code == 200, f"Second injection demo failed: {resp_inj_2.text}"
            demo_items_2 = [it for it in client.get("/inbox").json() if it.get("is_demo") is True]
            assert len(demo_items_2) == 1, f"Expected exactly 1 demo item after re-run, found {len(demo_items_2)}"
            print("  --> Verified: Demo endpoint is idempotent and isolated.")

            # Cryptographic audit ledger verification
            resp_audit = client.get("/audit/export")
            assert resp_audit.status_code == 200, f"Audit export failed: {resp_audit.text}"
            audit_data = resp_audit.json()
            chain = audit_data["chain_verification"]
            print(f"  --> Total Cryptographic Audit Entries: {audit_data['entry_count']}")
            print(f"  --> Hash Chain Status: {'VALID (Untampered)' if chain['valid'] else 'INVALID'}")
            assert chain["valid"] is True, f"Cryptographic audit chain broken! {chain}"

            print("\n" + "=" * 78)
            print("  ALL SMOKE TEST ASSERTIONS PASSED SUCCESSFULLY IN ISOLATED ENVIRONMENT!")
            print("=" * 78 + "\n")

        finally:
            # Restore settings
            settings.DB_PATH = orig_db
            settings.CHROMA_PERSIST_DIR = orig_chroma
            settings.DATA_DIR = orig_data
            settings.NOTIFICATIONS_LOG_PATH = orig_notif
            os.environ["DB_PATH"] = str(orig_db)
            os.environ["CHROMA_PERSIST_DIR"] = str(orig_chroma)
            os.environ["DATA_DIR"] = str(orig_data)
            os.environ["NOTIFICATIONS_LOG_PATH"] = str(orig_notif)


if __name__ == "__main__":
    try:
        run_smoke_test()
    except Exception as e:
        print(f"\n[FATAL] Smoke test failed: {e}", file=sys.stderr)
        sys.exit(1)
