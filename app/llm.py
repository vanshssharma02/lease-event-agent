"""LLM Client Module for lease-event-agent.

Provides generate_memo(prompt, retrieved) with two operating modes:
  - 'live': Calls OpenRouter via the OpenAI Python SDK with structured JSON output,
    exponential backoff retry logic, and fallback model degradation.
  - 'mock': Deterministically produces schema-valid, cited JSON memos from retrieved data
    enabling offline testing and full test-suite execution with zero API keys.
"""

import json
import logging
import time
import uuid
from datetime import date
from typing import Optional, Dict, Any, Union

from openai import OpenAI, APIError, RateLimitError, APITimeoutError

from app.config import settings
from app.prompt import AssembledPrompt
from app.retrieval import RetrievedLeaseContext
from app.schemas import (
    LeaseEventMemo,
    CitedStr,
    CitedMoney,
    CitedDate,
    EventType,
    Urgency,
)

logger = logging.getLogger(__name__)


def generate_mock_memo(
    prompt: AssembledPrompt,
    retrieved: RetrievedLeaseContext,
    model_version: Optional[str] = None,
) -> str:
    """Deterministically construct a valid, cited LeaseEventMemo JSON string from retrieved data."""
    lease = retrieved.lease
    today = date.today()

    try:
        exp_date = date.fromisoformat(lease.expiry_date)
        raw_diff = (exp_date - today).days
        days_to_event = max(1, min(180, raw_diff))
    except Exception:
        days_to_event = 60

    # Map retrieved chunks by page for accurate citations
    p1 = next((c for c in retrieved.chunks if c.page == 1), retrieved.chunks[0] if retrieved.chunks else None)
    p2 = next((c for c in retrieved.chunks if c.page == 2), p1)
    p3 = next((c for c in retrieved.chunks if c.page == 3), p2)
    p4 = next((c for c in retrieved.chunks if c.page == 4), p3)
    p5 = next((c for c in retrieved.chunks if c.page == 5), p4)

    # Fallback IDs if no chunks present
    p1_id = p1.chunk_id if p1 else f"{lease.lease_id}-p1-c1"
    p2_id = p2.chunk_id if p2 else f"{lease.lease_id}-p2-c1"
    p4_id = p4.chunk_id if p4 else f"{lease.lease_id}-p4-c1"
    p5_id = p5.chunk_id if p5 else f"{lease.lease_id}-p5-c1"

    # Extract any injection flags if noted in prompt task slot
    injection_flags = []
    if "Recorded injection flags:" in prompt.user_content:
        # Extract from prompt slot if present
        pass

    # Urgency determination
    if days_to_event <= 90 or lease.event_type in ["EXPIRY", "BREAK"]:
        urgency = Urgency.HIGH
    else:
        urgency = Urgency.MEDIUM

    memo_obj = LeaseEventMemo(
        agent_id="lease-event-agent-v1",
        run_id=str(uuid.uuid4()),
        asset_id=lease.asset_id,
        lease_id=lease.lease_id,
        event_type=EventType(lease.event_type),
        days_to_event=days_to_event,
        tenant_name=CitedStr(
            value=lease.tenant,
            source_chunk_id=p1_id,
            page=p1.page if p1 else 1,
        ),
        passing_rent=CitedMoney(
            amount=lease.passing_rent,
            currency=lease.currency,
            source_chunk_id=p2_id,
            page=p2.page if p2 else 2,
        ),
        event_date=CitedDate(
            date=lease.expiry_date,
            source_chunk_id=p1_id,
            page=p1.page if p1 else 1,
        ),
        rent_at_risk=CitedMoney(
            amount=lease.passing_rent,
            currency=lease.currency,
            source_chunk_id=p2_id,
            page=p2.page if p2 else 2,
        ),
        break_conditions=[
            CitedStr(
                value="Delivery of full vacant possession unencumbered by occupational sub-leases",
                source_chunk_id=p4_id,
                page=p4.page if p4 else 4,
            ),
            CitedStr(
                value="Discharge of all passing rent, service charge, and outgoings without arrears",
                source_chunk_id=p4_id,
                page=p4.page if p4 else 4,
            ),
        ],
        reinstatement=CitedStr(
            value="Tenant covenant requiring dismantling of fixtures and yielding premises in repair",
            source_chunk_id=p5_id,
            page=p5.page if p5 else 5,
        ),
        wault=round(max(0.1, days_to_event / 365.25), 2),
        executive_summary=(
            f"Upcoming {lease.event_type} event for {lease.tenant} at {lease.asset_name} on {lease.expiry_date} "
            f"({days_to_event} days remaining). Annual passing rent of {lease.currency} {lease.passing_rent:,.2f} "
            f"is at risk. Immediate action required to verify compliance with contractual pre-conditions."
        ),
        recommended_actions=[
            "Instruct building surveyor to assess terminal dilapidations liability.",
            "Verify finance register to confirm zero passing rent or service charge arrears.",
            "Confirm occupational status to ensure vacant possession can be delivered.",
            "Review statutory Landlord and Tenant Act notice obligations with legal counsel.",
        ],
        urgency=urgency,
        confidence_score=0.96,
        injection_flags=injection_flags,
        model_version=model_version or settings.LLM_MODEL,
        prompt_hash=prompt.prompt_hash,
    )

    return json.dumps(memo_obj.model_dump(), indent=2)


def generate_live_memo(
    prompt: AssembledPrompt,
    retrieved: RetrievedLeaseContext,
    client: Optional[OpenAI] = None,
    max_retries: int = 3,
) -> str:
    """Call OpenRouter with exponential backoff and automatic fallback model retry."""
    if not settings.OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY is not configured in settings or environment.")

    if client is None:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY,
        )

    messages = prompt.to_messages()
    models_to_try = [settings.LLM_MODEL, settings.LLM_FALLBACK_MODEL]

    for model_name in models_to_try:
        delay = 1.0
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Calling OpenRouter model '{model_name}' (attempt {attempt}/{max_retries})...")
                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.0,
                )
                content = response.choices[0].message.content
                if content:
                    return content.strip()
                raise ValueError("Received empty response from OpenRouter API.")

            except (RateLimitError, APITimeoutError, APIError) as e:
                logger.warning(f"Error on model {model_name} attempt {attempt}: {str(e)}")
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2.0
                else:
                    logger.error(f"Exhausted retries for model '{model_name}'.")
                    break  # Fall back to next model

    raise RuntimeError(
        f"All models failed on OpenRouter: primary ({settings.LLM_MODEL}) and fallback ({settings.LLM_FALLBACK_MODEL})."
    )


def generate_memo(
    prompt: AssembledPrompt,
    retrieved: RetrievedLeaseContext,
    client: Optional[OpenAI] = None,
    mode: Optional[str] = None,
) -> str:
    """Route memo generation to either live OpenRouter API or deterministic mock generator."""
    effective_mode = mode or settings.LLM_MODE

    if effective_mode.lower() == "live":
        return generate_live_memo(prompt, retrieved, client=client)
    else:
        return generate_mock_memo(prompt, retrieved)
