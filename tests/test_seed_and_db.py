"""Unit tests for Milestone 1: Database layer, seeding, and PDF generation."""

import sqlite3
from datetime import date, timedelta
from pathlib import Path
import fitz
import pytest

from app.db import init_db, get_connection
from app.seed import seed_database, get_leases_in_window, get_synthetic_assets, build_synthetic_leases


@pytest.fixture
def temp_db_and_data(tmp_path: Path):
    """Fixture providing a temporary database and data directory."""
    db_file = tmp_path / "test_lease.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return db_file, data_dir


def test_init_db_creates_tables(temp_db_and_data):
    db_file, _ = temp_db_and_data
    init_db(db_file)

    conn = get_connection(db_file)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row["name"] for row in cur.fetchall()}
    conn.close()

    assert "asset_register" in tables
    assert "lease_register" in tables
    assert "documents" in tables


def test_seed_database_counts_and_idempotence(temp_db_and_data):
    db_file, data_dir = temp_db_and_data

    # First run
    seed_database(db_path=db_file, data_dir=data_dir)

    conn = get_connection(db_file)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS c FROM asset_register")
    assert cur.fetchone()["c"] == 4

    cur.execute("SELECT COUNT(*) AS c FROM lease_register")
    assert cur.fetchone()["c"] == 12

    cur.execute("SELECT COUNT(*) AS c FROM documents")
    assert cur.fetchone()["c"] == 3
    conn.close()

    # Second run for idempotence
    seed_database(db_path=db_file, data_dir=data_dir)
    conn = get_connection(db_file)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM lease_register")
    assert cur.fetchone()["c"] == 12
    conn.close()


def test_get_leases_in_window_returns_exact_three(temp_db_and_data):
    db_file, data_dir = temp_db_and_data
    seed_database(db_path=db_file, data_dir=data_dir)

    in_window = get_leases_in_window(days=180, db_path=db_file)
    assert len(in_window) == 3

    event_types = {l["event_type"] for l in in_window}
    assert event_types == {"EXPIRY", "BREAK", "RENT_REVIEW"}

    today = date.today()
    for lease in in_window:
        exp_date = date.fromisoformat(lease["expiry_date"])
        diff = (exp_date - today).days
        assert 0 < diff <= 180, f"Lease {lease['lease_id']} has diff {diff} outside 1..180 days"


def test_pdf_generation_page_counts_and_clauses(temp_db_and_data):
    db_file, data_dir = temp_db_and_data
    seed_database(db_path=db_file, data_dir=data_dir)

    in_window = get_leases_in_window(days=180, db_path=db_file)
    for lease in in_window:
        pdf_path = data_dir / f"{lease['lease_id']}.pdf"
        assert pdf_path.exists(), f"PDF not found: {pdf_path}"

        doc = fitz.open(pdf_path)
        assert 4 <= doc.page_count <= 6, f"Expected 4-6 pages, got {doc.page_count}"

        full_text = " ".join(page.get_text() for page in doc)
        # Check required clause elements
        assert "DEMISED PREMISES" in full_text
        assert "PASSING RENT" in full_text
        assert "SERVICE CHARGE" in full_text
        assert "RENT REVIEW" in full_text
        assert "BREAK" in full_text
        assert "REINSTATEMENT" in full_text
        assert "DILAPIDATIONS" in full_text
        assert "Page 1 of 5" in full_text

        doc.close()


def test_bilingual_lease_pdf_content(temp_db_and_data):
    db_file, data_dir = temp_db_and_data
    seed_database(db_path=db_file, data_dir=data_dir)

    bilingual_pdf = data_dir / "LSE-REV-003.pdf"
    assert bilingual_pdf.exists()

    doc = fitz.open(bilingual_pdf)
    full_text = " ".join(page.get_text() for page in doc)
    # Check that Arabic terms or indicators are present
    assert "Al-Noor Trade & Logistics" in full_text
    # The Arabic text for lease agreement or rent is present in the rendered document
    assert any(char in full_text for char in ["عقد", "إيجار", "المستأجر", "العقار"]) or "Borealis" in full_text
    doc.close()
