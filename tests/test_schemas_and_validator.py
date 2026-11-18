"""Unit tests for Milestone 3: Pydantic v2 schemas and deterministic validator rules."""

from datetime import date, timedelta
import pytest
from pydantic import ValidationError

from app.schemas import (
    LeaseEventMemo,
    CitedStr,
    CitedMoney,
    CitedDate,
    EventType,
    Urgency,
)
from app.retrieval import LeaseRecord, RetrievedChunk, RetrievedLeaseContext
from app.validator import validate_memo, ValidationResult


@pytest.fixture
def sample_context() -> RetrievedLeaseContext:
    """Create a realistic ground-truth RetrievedLeaseContext."""
    lease_rec = LeaseRecord(
        lease_id="LSE-EXP-001",
        asset_id="AST-MERIDIAN-01",
        tenant="Apex Logistics Ltd",
        expiry_date="2027-01-17",
        event_type="EXPIRY",
        passing_rent=240000.0,
        currency="GBP",
        status="ACTIVE",
        asset_name="Meridian Industrial Park",
        holding_spv="Meridian Propco 1 Ltd",
        portfolio="UK Logistics Portfolio",
        asset_manager="Morgan Taylor",
    )
    chunks = [
        RetrievedChunk(chunk_id="LSE-EXP-001-p1-c1", lease_id="LSE-EXP-001", page=1, text="Demised premises: Unit 4"),
        RetrievedChunk(chunk_id="LSE-EXP-001-p2-c1", lease_id="LSE-EXP-001", page=2, text="Passing rent £240,000 p.a."),
        RetrievedChunk(chunk_id="LSE-EXP-001-p3-c1", lease_id="LSE-EXP-001", page=3, text="Rent review mechanism OMV"),
        RetrievedChunk(chunk_id="LSE-EXP-001-p4-c1", lease_id="LSE-EXP-001", page=4, text="Tenant break clause terms"),
        RetrievedChunk(chunk_id="LSE-EXP-001-p5-c1", lease_id="LSE-EXP-001", page=5, text="Reinstatement obligations"),
    ]
    return RetrievedLeaseContext(lease=lease_rec, chunks=chunks)


@pytest.fixture
def valid_memo_dict() -> dict:
    """A baseline dictionary that satisfies all schema and validation rules."""
    return {
        "agent_id": "lease-event-agent-v1",
        "asset_id": "AST-MERIDIAN-01",
        "lease_id": "LSE-EXP-001",
        "event_type": "EXPIRY",
        "days_to_event": 60,
        "tenant_name": {
            "value": "Apex Logistics Ltd",
            "source_chunk_id": "LSE-EXP-001-p1-c1",
            "page": 1,
        },
        "passing_rent": {
            "amount": 240000.0,
            "currency": "GBP",
            "source_chunk_id": "LSE-EXP-001-p2-c1",
            "page": 2,
        },
        "event_date": {
            "date": "2027-01-17",
            "source_chunk_id": "LSE-EXP-001-p1-c1",
            "page": 1,
        },
        "rent_at_risk": {
            "amount": 240000.0,
            "currency": "GBP",
            "source_chunk_id": "LSE-EXP-001-p2-c1",
            "page": 2,
        },
        "break_conditions": [
            {
                "value": "Vacant possession required",
                "source_chunk_id": "LSE-EXP-001-p4-c1",
                "page": 4,
            }
        ],
        "reinstatement": {
            "value": "Remove all pallet racking and mezzanine",
            "source_chunk_id": "LSE-EXP-001-p5-c1",
            "page": 5,
        },
        "wault": 0.16,
        "executive_summary": "Contractual expiry event approaching in 60 days for Apex Logistics at Meridian Industrial Park.",
        "recommended_actions": [
            "Issue formal dilapidations schedule",
            "Confirm vacant possession requirements with tenant",
            "Inspect premises condition with building surveyor",
        ],
        "urgency": "HIGH",
        "confidence_score": 0.95,
        "injection_flags": [],
        "model_version": "gemma-4-26b-a4b-it",
        "prompt_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }


def test_valid_memo_passes_validation(sample_context, valid_memo_dict):
    result = validate_memo(valid_memo_dict, sample_context)
    assert result.ok is True
    assert len(result.errors) == 0
    assert len(result.warnings) == 0
    assert result.memo is not None
    assert result.memo.tenant_name.value == "Apex Logistics Ltd"


def test_hallucinated_rent_fails_rent_bounds(sample_context, valid_memo_dict):
    # Register passing rent is £240,000. 50% bounds are [120,000, 360,000].
    # Set hallucinated rent to £500,000 (> +50%)
    valid_memo_dict["passing_rent"]["amount"] = 500000.0
    result = validate_memo(valid_memo_dict, sample_context)

    assert result.ok is False
    assert "RENT_OUT_OF_BOUNDS" in result.error_codes
    assert any("Passing rent £500,000.00 deviates" in e for e in result.errors)

    # Set hallucinated rent to £50,000 (< -50%)
    valid_memo_dict["passing_rent"]["amount"] = 50000.0
    result_low = validate_memo(valid_memo_dict, sample_context)
    assert result_low.ok is False
    assert "RENT_OUT_OF_BOUNDS" in result_low.error_codes


def test_date_mismatch_fails_event_date_rule(sample_context, valid_memo_dict):
    # Register date is 2027-01-17. Set date to 2027-01-25 (diff = 8 days > 3 days)
    valid_memo_dict["event_date"]["date"] = "2027-01-25"
    result = validate_memo(valid_memo_dict, sample_context)

    assert result.ok is False
    assert "EVENT_DATE_MISMATCH" in result.error_codes
    assert any("deviates by 8 days" in e for e in result.errors)

    # Allowed ±3 days tolerance: 2027-01-19 is +2 days (should pass date rule)
    valid_memo_dict["event_date"]["date"] = "2027-01-19"
    result_tolerated = validate_memo(valid_memo_dict, sample_context)
    assert "EVENT_DATE_MISMATCH" not in result_tolerated.error_codes


def test_fake_citation_id_fails_citation_rule(sample_context, valid_memo_dict):
    # Provide a hallucinated/fake chunk ID that does not exist in sample_context
    valid_memo_dict["reinstatement"]["source_chunk_id"] = "LSE-FAKE-999-p9-c9"
    result = validate_memo(valid_memo_dict, sample_context)

    assert result.ok is False
    assert "INVALID_CITATION_ID" in result.error_codes
    assert any("LSE-FAKE-999-p9-c9" in e for e in result.errors)


def test_low_confidence_generates_warning_only(sample_context, valid_memo_dict):
    # Confidence 0.52 < 0.60
    valid_memo_dict["confidence_score"] = 0.52
    result = validate_memo(valid_memo_dict, sample_context)

    # Does not block ok flag
    assert result.ok is True
    assert len(result.errors) == 0
    assert any("LOW_CONFIDENCE" in w for w in result.warnings)


def test_summary_and_actions_graceful_truncation(sample_context, valid_memo_dict):
    # Executive summary > 600 characters
    long_summary = "This is a detailed commercial lease analysis note. " * 20  # ~1020 chars
    valid_memo_dict["executive_summary"] = long_summary

    # Recommended actions > 5 items
    long_actions = [f"Action item number {i}" for i in range(1, 9)]  # 8 items
    valid_memo_dict["recommended_actions"] = long_actions

    result = validate_memo(valid_memo_dict, sample_context)

    assert result.ok is True
    assert len(result.errors) == 0
    assert len(result.truncations) == 2
    assert any("SUMMARY_TRUNCATED" in t for t in result.truncations)
    assert any("ACTIONS_TRUNCATED" in t for t in result.truncations)

    # Verify memo was truncated
    assert len(result.memo.executive_summary) == 600
    assert len(result.memo.recommended_actions) == 5


def test_schema_constraints_validation():
    # Test days_to_event <= 0 or > 180 raises ValidationError
    with pytest.raises(ValidationError):
        LeaseEventMemo(
            asset_id="AST-01",
            lease_id="LSE-01",
            event_type=EventType.EXPIRY,
            days_to_event=0,  # Invalid: gt=0
            tenant_name=CitedStr(value="T", source_chunk_id="c1", page=1),
            passing_rent=CitedMoney(amount=100.0, source_chunk_id="c1", page=1),
            event_date=CitedDate(date="2027-01-01", source_chunk_id="c1", page=1),
            rent_at_risk=CitedMoney(amount=100.0, source_chunk_id="c1", page=1),
            reinstatement=CitedStr(value="R", source_chunk_id="c1", page=1),
            wault=1.0,
            executive_summary="Summary",
            recommended_actions=[],
            urgency=Urgency.HIGH,
            confidence_score=0.9,
            prompt_hash="abc",
        )

    with pytest.raises(ValidationError):
        LeaseEventMemo(
            asset_id="AST-01",
            lease_id="LSE-01",
            event_type=EventType.EXPIRY,
            days_to_event=181,  # Invalid: le=180
            tenant_name=CitedStr(value="T", source_chunk_id="c1", page=1),
            passing_rent=CitedMoney(amount=100.0, source_chunk_id="c1", page=1),
            event_date=CitedDate(date="2027-01-01", source_chunk_id="c1", page=1),
            rent_at_risk=CitedMoney(amount=100.0, source_chunk_id="c1", page=1),
            reinstatement=CitedStr(value="R", source_chunk_id="c1", page=1),
            wault=1.0,
            executive_summary="Summary",
            recommended_actions=[],
            urgency=Urgency.HIGH,
            confidence_score=0.9,
            prompt_hash="abc",
        )
