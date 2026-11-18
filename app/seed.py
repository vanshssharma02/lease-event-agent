"""Seed script for lease-event-agent.

Generates 12 synthetic leases across 4 fictional assets and 2 portfolios.
Computes dates relative to runtime execution date such that exactly 3 leases fall
within the 180-day window (one EXPIRY, one BREAK, one RENT_REVIEW) and the other 9
fall outside it. Generates 3 multi-page PDFs in data/ for the in-window leases.
"""

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

from app.config import settings
from app.db import init_db, get_connection
from app.pdfgen import generate_all_synthetic_pdfs


def get_synthetic_assets() -> List[Dict[str, str]]:
    """Define 4 synthetic commercial assets across 2 portfolios."""
    return [
        {
            "asset_id": "AST-MERIDIAN-01",
            "asset_name": "Meridian Industrial Park",
            "holding_spv": "Meridian Propco 1 Ltd",
            "portfolio": "UK Logistics Portfolio",
            "asset_manager": "Morgan Taylor",
        },
        {
            "asset_id": "AST-SOLSTICE-02",
            "asset_name": "Solstice Commercial Tower",
            "holding_spv": "Solstice Offices Propco Ltd",
            "portfolio": "Regional Core Office Portfolio",
            "asset_manager": "Jane Doe",
        },
        {
            "asset_id": "AST-BOREALIS-03",
            "asset_name": "Borealis Distribution Hub",
            "holding_spv": "Borealis Asset SPV Ltd",
            "portfolio": "UK Logistics Portfolio",
            "asset_manager": "Alex Smith",
        },
        {
            "asset_id": "AST-ORION-04",
            "asset_name": "Orion Technology Centre",
            "holding_spv": "Orion Innovation Propco Ltd",
            "portfolio": "Regional Core Office Portfolio",
            "asset_manager": "Jordan Lee",
        },
    ]


def build_synthetic_leases(today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Build 12 synthetic leases with dates strictly relative to today.

    Exactly 3 fall within 1..180 days:
      - 1 EXPIRY (T + 60 days)
      - 1 BREAK (T + 90 days)
      - 1 RENT_REVIEW (T + 120 days)
    The other 9 are outside the window (>180 days or past).
    """
    if today is None:
        today = date.today()

    leases = [
        # ================= IN-WINDOW LEASES (Exactly 3) =================
        {
            "lease_id": "LSE-EXP-001",
            "asset_id": "AST-MERIDIAN-01",
            "tenant": "Apex Logistics Ltd",
            "expiry_date": (today + timedelta(days=60)).isoformat(),
            "event_type": "EXPIRY",
            "passing_rent": 240000.0,
            "currency": "GBP",
            "status": "ACTIVE",
            "in_window": True,
            # Document specifics for PDF generator
            "premises": "Unit 4, Meridian Industrial Park, North Way, Sector 7",
            "sqft": "32,500",
            "term_years": 5,
            "commencement_date": (today + timedelta(days=60) - timedelta(days=365 * 5)).isoformat(),
            "contractual_expiry_date": (today + timedelta(days=60)).isoformat(),
            "event_date": (today + timedelta(days=60)).isoformat(),
            "service_charge_cap": 18500.0,
            "rent_review_date": (today + timedelta(days=60) - timedelta(days=365 * 2)).isoformat(),
            "rent_review_mechanism": "Upward-only open market review conducted quinquennially; current reviewed passing rent confirmed at £240,000 per annum.",
            "break_clause_summary": "Tenant Year 3 break option expired unexercised; the pending milestone is contractual lease expiry on the Expiry Date.",
            "break_notice_served_status": "No renewal notice served under statutory procedures; expiration notification active.",
            "break_notice_months": 6,
            "reinstatement_obligation": "Tenant covenants to remove all high-bay pallet racking, dismantle mezzanine office structures, and yield up the warehouse slab cleaned and unencumbered.",
            "dilapidations_estimate": 42500.0,
            "bilingual": False,
        },
        {
            "lease_id": "LSE-BRK-002",
            "asset_id": "AST-SOLSTICE-02",
            "tenant": "Horizon Tech Systems",
            "expiry_date": (today + timedelta(days=90)).isoformat(),
            "event_type": "BREAK",
            "passing_rent": 385000.0,
            "currency": "GBP",
            "status": "ACTIVE",
            "in_window": True,
            # Document specifics for PDF generator
            "premises": "Suite 800, 8th Floor, Solstice Commercial Tower, Central Avenue",
            "sqft": "14,800",
            "term_years": 10,
            "commencement_date": (today + timedelta(days=90) - timedelta(days=365 * 5)).isoformat(),
            "contractual_expiry_date": (today + timedelta(days=90) + timedelta(days=365 * 5)).isoformat(),
            "event_date": (today + timedelta(days=90)).isoformat(),
            "service_charge_cap": 32000.0,
            "rent_review_date": (today + timedelta(days=90)).isoformat(),
            "rent_review_mechanism": "Upward-only to higher of open market rental value and RPI indexation at the 5th anniversary.",
            "break_clause_summary": "Mutual 5th anniversary break option exercisable by Tenant subject to 6 months prior written notice and strict condition compliance.",
            "break_notice_served_status": "Tenant formal break notice was served on landlord agents 6 months prior to Break Date.",
            "break_notice_months": 6,
            "reinstatement_obligation": "Removal of all tenant communications cabling, demountable glass office pods, and restoration of raised acoustic floor tiles to original layout.",
            "dilapidations_estimate": 68000.0,
            "bilingual": False,
        },
        {
            "lease_id": "LSE-REV-003",
            "asset_id": "AST-BOREALIS-03",
            "tenant": "Al-Noor Trade & Logistics",
            "expiry_date": (today + timedelta(days=120)).isoformat(),
            "event_type": "RENT_REVIEW",
            "passing_rent": 195000.0,
            "currency": "GBP",
            "status": "ACTIVE",
            "in_window": True,
            # Document specifics for PDF generator (Bilingual English/Arabic)
            "premises": "Bay 3, Borealis Distribution Hub, East Gateway",
            "sqft": "26,000",
            "term_years": 10,
            "commencement_date": (today + timedelta(days=120) - timedelta(days=365 * 5)).isoformat(),
            "contractual_expiry_date": (today + timedelta(days=120) + timedelta(days=365 * 5)).isoformat(),
            "event_date": (today + timedelta(days=120)).isoformat(),
            "service_charge_cap": 14000.0,
            "rent_review_date": (today + timedelta(days=120)).isoformat(),
            "rent_review_mechanism": "Upward-only open market review according to RICS Guidance Notes, time not of the essence, projected market ERV at £225,000 p.a.",
            "break_clause_summary": "Tenant rolling break exercisable at Year 7 upon 6 months notice; no break operative at current 5-year review milestone.",
            "break_notice_served_status": "No break notice operative at current review juncture.",
            "break_notice_months": 6,
            "reinstatement_obligation": "Full tenant repair covenant requiring loading bay shutter overhaul, removal of tenant modular welfare unit, and lighting reinstatement.",
            "dilapidations_estimate": 28000.0,
            "bilingual": True,
        },
        # ================= OUT-OF-WINDOW LEASES (Exactly 9) =================
        {
            "lease_id": "LSE-OUT-004",
            "asset_id": "AST-MERIDIAN-01",
            "tenant": "Zenith Global Freight Ltd",
            "expiry_date": (today + timedelta(days=240)).isoformat(),
            "event_type": "EXPIRY",
            "passing_rent": 310000.0,
            "currency": "GBP",
            "status": "ACTIVE",
            "in_window": False,
        },
        {
            "lease_id": "LSE-OUT-005",
            "asset_id": "AST-SOLSTICE-02",
            "tenant": "Starlight Media Group",
            "expiry_date": (today + timedelta(days=365)).isoformat(),
            "event_type": "BREAK",
            "passing_rent": 420000.0,
            "currency": "GBP",
            "status": "ACTIVE",
            "in_window": False,
        },
        {
            "lease_id": "LSE-OUT-006",
            "asset_id": "AST-BOREALIS-03",
            "tenant": "Silverline Cold Storage Ltd",
            "expiry_date": (today + timedelta(days=420)).isoformat(),
            "event_type": "RENT_REVIEW",
            "passing_rent": 280000.0,
            "currency": "GBP",
            "status": "ACTIVE",
            "in_window": False,
        },
        {
            "lease_id": "LSE-OUT-007",
            "asset_id": "AST-ORION-04",
            "tenant": "Quantum BioLabs Ltd",
            "expiry_date": (today + timedelta(days=550)).isoformat(),
            "event_type": "EXPIRY",
            "passing_rent": 510000.0,
            "currency": "GBP",
            "status": "ACTIVE",
            "in_window": False,
        },
        {
            "lease_id": "LSE-OUT-008",
            "asset_id": "AST-MERIDIAN-01",
            "tenant": "Beacon Engineering Works",
            "expiry_date": (today + timedelta(days=700)).isoformat(),
            "event_type": "BREAK",
            "passing_rent": 175000.0,
            "currency": "GBP",
            "status": "ACTIVE",
            "in_window": False,
        },
        {
            "lease_id": "LSE-OUT-009",
            "asset_id": "AST-SOLSTICE-02",
            "tenant": "Pinnacle Financial Advisory",
            "expiry_date": (today + timedelta(days=850)).isoformat(),
            "event_type": "RENT_REVIEW",
            "passing_rent": 630000.0,
            "currency": "GBP",
            "status": "ACTIVE",
            "in_window": False,
        },
        {
            "lease_id": "LSE-OUT-010",
            "asset_id": "AST-ORION-04",
            "tenant": "Vanguard Microelectronics Ltd",
            "expiry_date": (today - timedelta(days=45)).isoformat(),  # Historical/expired
            "event_type": "EXPIRY",
            "passing_rent": 340000.0,
            "currency": "GBP",
            "status": "EXPIRED",
            "in_window": False,
        },
        {
            "lease_id": "LSE-OUT-011",
            "asset_id": "AST-BOREALIS-03",
            "tenant": "Nordic Cargo Logistics",
            "expiry_date": (today + timedelta(days=290)).isoformat(),
            "event_type": "BREAK",
            "passing_rent": 220000.0,
            "currency": "GBP",
            "status": "ACTIVE",
            "in_window": False,
        },
        {
            "lease_id": "LSE-OUT-012",
            "asset_id": "AST-ORION-04",
            "tenant": "Crestline Software Systems",
            "expiry_date": (today + timedelta(days=480)).isoformat(),
            "event_type": "RENT_REVIEW",
            "passing_rent": 295000.0,
            "currency": "GBP",
            "status": "ACTIVE",
            "in_window": False,
        },
    ]
    return leases


def seed_database(
    db_path: Optional[Union[str, Path]] = None,
    data_dir: Optional[Union[str, Path]] = None,
    today: Optional[date] = None,
) -> None:
    """Populate database and generate synthetic PDFs idempotently."""
    if today is None:
        today = date.today()

    target_db = Path(db_path) if db_path else settings.DB_PATH
    target_data_dir = Path(data_dir) if data_dir else settings.DATA_DIR

    init_db(target_db)
    assets = get_synthetic_assets()
    leases = build_synthetic_leases(today)

    # Attach asset info to leases for PDF rendering
    asset_map = {a["asset_id"]: a for a in assets}
    for l in leases:
        aid = l["asset_id"]
        if aid in asset_map:
            l["asset_name"] = asset_map[aid]["asset_name"]
            l["holding_spv"] = asset_map[aid]["holding_spv"]
            l["portfolio"] = asset_map[aid]["portfolio"]
            l["asset_manager"] = asset_map[aid]["asset_manager"]

    conn = get_connection(target_db)
    try:
        with conn:
            # 1. Insert Assets
            for a in assets:
                conn.execute(
                    """
                    INSERT INTO asset_register (asset_id, asset_name, holding_spv, portfolio, asset_manager)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(asset_id) DO UPDATE SET
                        asset_name=excluded.asset_name,
                        holding_spv=excluded.holding_spv,
                        portfolio=excluded.portfolio,
                        asset_manager=excluded.asset_manager;
                    """,
                    (a["asset_id"], a["asset_name"], a["holding_spv"], a["portfolio"], a["asset_manager"]),
                )

            # 2. Insert Leases
            for l in leases:
                conn.execute(
                    """
                    INSERT INTO lease_register (lease_id, asset_id, tenant, expiry_date, event_type, passing_rent, currency, status, is_demo)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(lease_id) DO UPDATE SET
                        asset_id=excluded.asset_id,
                        tenant=excluded.tenant,
                        expiry_date=excluded.expiry_date,
                        event_type=excluded.event_type,
                        passing_rent=excluded.passing_rent,
                        currency=excluded.currency,
                        status=excluded.status,
                        is_demo=excluded.is_demo;
                    """,
                    (
                        l["lease_id"],
                        l["asset_id"],
                        l["tenant"],
                        l["expiry_date"],
                        l["event_type"],
                        l["passing_rent"],
                        l["currency"],
                        l["status"],
                        l.get("is_demo", 0),
                    ),
                )

            # 3. Generate PDFs for the 3 in-window leases
            in_window_leases = [l for l in leases if l.get("in_window")]
            generated_pdf_paths = generate_all_synthetic_pdfs(in_window_leases, target_data_dir)

            # 4. Insert Document Records
            for l, path in zip(in_window_leases, generated_pdf_paths):
                doc_id = f"DOC-{l['lease_id']}"
                filename = path.name
                conn.execute(
                    """
                    INSERT INTO documents (doc_id, lease_id, filename, path)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(doc_id) DO UPDATE SET
                        lease_id=excluded.lease_id,
                        filename=excluded.filename,
                        path=excluded.path;
                    """,
                    (doc_id, l["lease_id"], filename, str(path)),
                )
    finally:
        conn.close()


def get_leases_in_window(
    days: int = 180,
    db_path: Optional[Union[str, Path]] = None,
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Query SQLite for active leases with an event occurring within 1..days window relative to today."""
    if today is None:
        today = date.today()

    start_date = (today + timedelta(days=1)).isoformat()
    end_date = (today + timedelta(days=days)).isoformat()

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        query = """
            SELECT
                l.lease_id,
                l.asset_id,
                l.tenant,
                l.expiry_date,
                l.event_type,
                l.passing_rent,
                l.currency,
                l.status,
                a.asset_name,
                a.holding_spv,
                a.portfolio,
                a.asset_manager,
                d.doc_id,
                d.filename,
                d.path AS doc_path
            FROM lease_register l
            JOIN asset_register a ON l.asset_id = a.asset_id
            LEFT JOIN documents d ON l.lease_id = d.lease_id
            WHERE l.status = 'ACTIVE'
              AND (l.is_demo = 0 OR l.is_demo IS NULL)
              AND l.expiry_date >= ?
              AND l.expiry_date <= ?
            ORDER BY l.expiry_date ASC;
        """
        cur.execute(query, (start_date, end_date))
        rows = [dict(row) for row in cur.fetchall()]
        return rows
    finally:
        conn.close()


if __name__ == "__main__":
    print("Executing synthetic database seeding...")
    seed_database()
    in_window = get_leases_in_window(days=180)
    print(f"Seeding completed successfully. Found {len(in_window)} in-window leases:")
    for lease in in_window:
        print(f" - [{lease['event_type']}] {lease['lease_id']}: {lease['tenant']} at {lease['asset_name']} (Event Date: {lease['expiry_date']})")
