"""Validator module for LeaseEventMemo objects.

Performs deterministic cross-register validation, citation provenance verification,
confidence threshold checks, and graceful truncation of summaries/actions.
"""

from datetime import date
from typing import List, Dict, Any, Optional, Union, Set
from pydantic import BaseModel, Field

from app.schemas import LeaseEventMemo
from app.retrieval import RetrievedLeaseContext


class ValidationResult(BaseModel):
    """Structured result of memo validation."""

    ok: bool = Field(..., description="True if no blocking validation errors were encountered")
    errors: List[str] = Field(default_factory=list, description="Human-readable error messages")
    error_codes: List[str] = Field(default_factory=list, description="Machine-readable specific error codes")
    warnings: List[str] = Field(default_factory=list, description="Non-blocking warning notices")
    truncations: List[str] = Field(default_factory=list, description="Notes on fields automatically truncated")
    memo: Optional[LeaseEventMemo] = Field(default=None, description="The validated (and potentially truncated) memo")


def validate_memo(
    memo_or_dict: Union[LeaseEventMemo, Dict[str, Any]],
    context: RetrievedLeaseContext,
) -> ValidationResult:
    """Validate a LeaseEventMemo against its ground-truth RetrievedLeaseContext.

    Enforces the following rules:
      1. RENT_OUT_OF_BOUNDS: Passing rent must be within ±50% of the register value.
      2. EVENT_DATE_MISMATCH: Event date must be within ±3 days of the register expiry/event date.
      3. INVALID_CITATION_ID: Every source_chunk_id cited must exist in the retrieved chunks.
      4. LOW_CONFIDENCE: Confidence score < 0.6 generates a non-blocking warning.
      5. Graceful truncation: Executive summary (>600 chars) and recommended actions (>5)
         are truncated with a logged note instead of failing validation.
    """
    errors: List[str] = []
    error_codes: List[str] = []
    warnings: List[str] = []
    truncations: List[str] = []

    # 1. Handle inputs and apply graceful truncations
    if isinstance(memo_or_dict, dict):
        raw = dict(memo_or_dict)

        # Check and apply executive_summary truncation
        summary = str(raw.get("executive_summary", ""))
        if len(summary) > 600:
            raw["executive_summary"] = summary[:600]
            truncations.append(
                f"SUMMARY_TRUNCATED: Executive summary exceeded 600 characters (length: {len(summary)}), truncated to 600 characters."
            )

        # Check and apply recommended_actions truncation
        actions = list(raw.get("recommended_actions", []))
        if len(actions) > 5:
            raw["recommended_actions"] = actions[:5]
            truncations.append(
                f"ACTIONS_TRUNCATED: Recommended actions list exceeded 5 items (count: {len(actions)}), truncated to 5 items."
            )

        try:
            memo = LeaseEventMemo.model_validate(raw)
        except Exception as e:
            return ValidationResult(
                ok=False,
                errors=[f"Schema validation failed: {str(e)}"],
                error_codes=["SCHEMA_VALIDATION_ERROR"],
                warnings=warnings,
                truncations=truncations,
                memo=None,
            )
    else:
        memo = memo_or_dict.model_copy(deep=True)
        # Apply truncation to model if fields exceed bounds
        if len(memo.executive_summary) > 600:
            memo.executive_summary = memo.executive_summary[:600]
            truncations.append(
                "SUMMARY_TRUNCATED: Executive summary exceeded 600 characters, truncated to 600 characters."
            )
        if len(memo.recommended_actions) > 5:
            memo.recommended_actions = memo.recommended_actions[:5]
            truncations.append(
                "ACTIONS_TRUNCATED: Recommended actions list exceeded 5 items, truncated to 5 items."
            )

    register_lease = context.lease
    valid_chunk_ids: Set[str] = set(context.get_all_chunk_ids())

    # RULE 1: Passing rent within ±50% of the register value
    reg_rent = register_lease.passing_rent
    memo_rent = memo.passing_rent.amount
    if reg_rent > 0:
        pct_diff = abs(memo_rent - reg_rent) / reg_rent
        if pct_diff > 0.50:
            errors.append(
                f"Passing rent £{memo_rent:,.2f} deviates by {pct_diff:.1%} from register value £{reg_rent:,.2f} (exceeds ±50% threshold)."
            )
            error_codes.append("RENT_OUT_OF_BOUNDS")

    # RULE 2: Event date within ±3 days of the register
    try:
        reg_date = date.fromisoformat(register_lease.expiry_date)
        memo_date = date.fromisoformat(memo.event_date.date)
        day_diff = abs((memo_date - reg_date).days)
        if day_diff > 3:
            errors.append(
                f"Event date '{memo_date}' deviates by {day_diff} days from register date '{reg_date}' (exceeds ±3 days threshold)."
            )
            error_codes.append("EVENT_DATE_MISMATCH")
    except Exception as e:
        errors.append(f"Invalid date format in event_date or register: {str(e)}")
        error_codes.append("INVALID_DATE_FORMAT")

    # RULE 3: Every source_chunk_id must exist in the retrieved set
    citations_to_check: List[tuple[str, str]] = [
        ("tenant_name", memo.tenant_name.source_chunk_id),
        ("passing_rent", memo.passing_rent.source_chunk_id),
        ("event_date", memo.event_date.source_chunk_id),
        ("rent_at_risk", memo.rent_at_risk.source_chunk_id),
        ("reinstatement", memo.reinstatement.source_chunk_id),
    ]
    for idx, bc in enumerate(memo.break_conditions):
        citations_to_check.append((f"break_conditions[{idx}]", bc.source_chunk_id))

    for field_name, chunk_id in citations_to_check:
        if chunk_id not in valid_chunk_ids:
            errors.append(
                f"Citation '{chunk_id}' cited in '{field_name}' does not exist in the retrieved chunks for lease '{register_lease.lease_id}'."
            )
            error_codes.append("INVALID_CITATION_ID")

    # RULE 4: Confidence < 0.6 flags low-confidence (warning / badge, no auto-notify)
    if memo.confidence_score < 0.6:
        warnings.append(
            f"LOW_CONFIDENCE: Confidence score {memo.confidence_score:.2f} is below 0.60. Flagged for manual review badge; automated dispatch suppressed."
        )

    is_ok = len(errors) == 0
    return ValidationResult(
        ok=is_ok,
        errors=errors,
        error_codes=error_codes,
        warnings=warnings,
        truncations=truncations,
        memo=memo if is_ok else None,
    )
