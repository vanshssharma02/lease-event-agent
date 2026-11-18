"""Pydantic v2 schemas and models for lease-event-agent."""

import uuid
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict


class EventType(str, Enum):
    """Supported commercial lease lifecycle event types."""
    EXPIRY = "EXPIRY"
    BREAK = "BREAK"
    RENT_REVIEW = "RENT_REVIEW"


class Urgency(str, Enum):
    """Urgency classification for human-in-the-loop triage."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CitedStr(BaseModel):
    """A string value with mandatory chunk and page citation provenance."""
    model_config = ConfigDict(extra="ignore")

    value: str = Field(..., description="The cited textual value")
    source_chunk_id: str = Field(..., description="The stable chunk ID where the value originated")
    page: int = Field(..., ge=1, description="1-based page number of the source document")


class CitedMoney(BaseModel):
    """A monetary value with currency and mandatory citation provenance."""
    model_config = ConfigDict(extra="ignore")

    amount: float = Field(..., ge=0.0, description="The monetary amount")
    currency: str = Field(default="GBP", description="Three-letter currency code (e.g. GBP)")
    source_chunk_id: str = Field(..., description="The stable chunk ID where the amount originated")
    page: int = Field(..., ge=1, description="1-based page number of the source document")


class CitedDate(BaseModel):
    """An ISO date string with mandatory citation provenance."""
    model_config = ConfigDict(extra="ignore")

    date: str = Field(..., description="ISO 8601 date string (YYYY-MM-DD)")
    source_chunk_id: str = Field(..., description="The stable chunk ID where the date originated")
    page: int = Field(..., ge=1, description="1-based page number of the source document")


class LeaseEventMemo(BaseModel):
    """Complete, cited notification memo for a monitored lease event."""
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    agent_id: str = Field(default="lease-event-agent-v1", description="Identifier of the generating agent")
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique execution UUID")
    asset_id: str = Field(..., description="Asset identifier")
    lease_id: str = Field(..., description="Lease identifier")
    event_type: EventType = Field(..., description="Event type: EXPIRY, BREAK, or RENT_REVIEW")
    days_to_event: int = Field(..., gt=0, le=180, description="Calendar days to event (0 < x <= 180)")
    tenant_name: CitedStr = Field(..., description="Cited legal name of the tenant")
    passing_rent: CitedMoney = Field(..., description="Cited annual passing rent")
    event_date: CitedDate = Field(..., description="Cited date of the upcoming event")
    rent_at_risk: CitedMoney = Field(..., description="Passing rent or exposure at risk")
    break_conditions: List[CitedStr] = Field(default_factory=list, description="Cited conditions precedent for break or expiry")
    reinstatement: CitedStr = Field(..., description="Cited reinstatement and terminal dilapidations obligations")
    wault: float = Field(..., ge=0.0, description="Weighted Average Unexpired Lease Term in years")
    executive_summary: str = Field(..., max_length=600, description="High-level memo summary (max 600 chars)")
    recommended_actions: List[str] = Field(..., max_length=5, description="Recommended triage actions (max 5)")
    urgency: Urgency = Field(..., description="Urgency classification (HIGH, MEDIUM, LOW)")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Model confidence score between 0.0 and 1.0")
    injection_flags: List[str] = Field(default_factory=list, description="List of quarantined chunk IDs flagged for injection")
    model_version: str = Field(default="gemma-4-26b-a4b-it", description="Model version slug used for generation")
    prompt_hash: str = Field(..., description="SHA-256 hash of the complete assembled prompt")
