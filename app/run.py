"""Standalone CLI Runner for lease-event-agent.

Executes `python -m app.run` across all in-window leases, outputs audit trails
and persists pending inbox items, rendering a clean summary table to stdout.
"""

import sys
from datetime import date
from app.db import init_db
from app.audit import init_audit_table, verify_chain
from app.seed import seed_database
from app.retrieval import index_all_in_window
from app.scheduler import run_in_window_leases


def main():
    print("=" * 78)
    print("  LEASE-EVENT-AGENT: IN-WINDOW RUNNER (Part 2)")
    print("=" * 78)

    # 1. Ensure DB and audit tables are ready
    init_db()
    init_audit_table()

    # 2. Seed database & index documents if not already indexed
    seed_database()
    index_all_in_window()

    # 3. Execute agent on in-window leases (default deduplication, bypass with --force)
    force = "--force" in sys.argv
    print(f"\nScanning lease register for upcoming events (180-day window, force={force})...")
    results = run_in_window_leases(days=180, force=force)

    # 4. Print clean summary table
    print("\n" + "-" * 78)
    print(f"{'LEASE ID':<13} {'EVENT':<12} {'TENANT':<26} {'DAYS/DATE':<14} {'STATUS'}")
    print("-" * 78)

    for r in results:
        lid = r["lease_id"]
        ev = r["event_type"]
        tenant = r["tenant"][:24]
        dt = r["expiry_date"]
        st = r["status"]
        print(f"{lid:<13} {ev:<12} {tenant:<26} {dt:<14} {st}")

    print("-" * 78)

    # 5. Verify cryptographic audit chain
    chain_res = verify_chain()
    print(f"\nAudit Log Integrity: {'VALID' if chain_res['valid'] else 'INVALID'} "
          f"({chain_res['checked']} entries verified, first_bad: {chain_res['first_bad_entry']})")
    print(f"Approvals Inbox: items ready for review via UI or REST API.")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    main()
