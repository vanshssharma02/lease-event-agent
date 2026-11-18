"""LangGraph Agent for lease-event-agent.

Implements the multi-stage state graph:
  trigger -> retrieve -> injection_guard -> build_prompt -> infer -> validate -> route (or retry/reject)
Persists run execution states to SQLite (agent_runs and inbox_items) and maintains
a tamper-evident cryptographic audit log across every node transition.
"""

import json
import uuid
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Callable, TypedDict

from langgraph.graph import StateGraph, START, END

from app.config import settings
from app.db import get_connection
from app.audit import append_entry, hash_payload
from app.retrieval import retrieve, RetrievedLeaseContext, LeaseRecord, RetrievedChunk
from app.guard import RuleBasedGuard, QuarantinedChunk
from app.prompt import PromptBuilder, AssembledPrompt
from app.llm import generate_memo
from app.validator import validate_memo, ValidationResult
from app.notify import send_notification
from app.schemas import LeaseEventMemo


class AgentState(TypedDict, total=False):
    """Execution state container for the LangGraph agent."""

    run_id: str
    lease_id: str
    parent_run_id: Optional[str]
    extra_instructions: Optional[str]
    lease: Optional[LeaseRecord]
    context: Optional[RetrievedLeaseContext]
    safe_chunks: List[RetrievedChunk]
    quarantined_chunk_ids: List[str]
    quarantined_details: List[Dict[str, Any]]
    prompt: Optional[AssembledPrompt]
    prompt_hash: Optional[str]
    raw_memo: Optional[str]
    validation_result: Optional[Dict[str, Any]]
    attempt_count: int
    error_context: List[str]
    status: str
    memo_dict: Optional[Dict[str, Any]]
    low_confidence: bool
    no_auto_notify: bool
    db_path: Optional[str]
    chroma_dir: Optional[str]
    collection_name: Optional[str]
    mock_override_fn: Optional[Callable[..., str]]


def persist_run_state(
    run_id: str,
    lease_id: str,
    status: str,
    memo_json: Optional[str] = None,
    parent_run_id: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Record or update execution progress in the agent_runs SQLite table."""
    conn = get_connection(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO agent_runs (run_id, lease_id, status, memo_json, created_at, updated_at, parent_run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    memo_json=COALESCE(excluded.memo_json, agent_runs.memo_json),
                    updated_at=excluded.updated_at;
                """,
                (run_id, lease_id, status, memo_json, now_iso, now_iso, parent_run_id),
            )
    finally:
        conn.close()


def trigger_node(state: AgentState) -> AgentState:
    """Initialize agent run execution and record TRIGGER audit entry."""
    run_id = state.get("run_id") or str(uuid.uuid4())
    lease_id = state["lease_id"]
    parent_run_id = state.get("parent_run_id")
    db_path = state.get("db_path")

    persist_run_state(
        run_id=run_id,
        lease_id=lease_id,
        status="IN_PROGRESS",
        parent_run_id=parent_run_id,
        db_path=db_path,
    )

    detail = {
        "lease_id": lease_id,
        "parent_run_id": parent_run_id,
        "extra_instructions": state.get("extra_instructions"),
    }
    append_entry(
        event_type="TRIGGER",
        run_id=run_id,
        input_hash=hash_payload(lease_id),
        output_hash=hash_payload(detail),
        detail=detail,
        db_path=db_path,
    )

    return {
        "run_id": run_id,
        "attempt_count": 0,
        "error_context": [],
        "status": "TRIGGERED",
    }


def retrieve_node(state: AgentState) -> AgentState:
    """Fetch structured register record and document chunks for the lease."""
    run_id = state["run_id"]
    lease_id = state["lease_id"]
    db_path = state.get("db_path")
    chroma_dir = state.get("chroma_dir")
    col_name = state.get("collection_name") or "lease_documents"

    from app.retrieval import get_chroma_client

    client = get_chroma_client(chroma_dir) if chroma_dir else None
    ctx = retrieve(lease_id=lease_id, client=client, db_path=db_path, collection_name=col_name)

    detail = {
        "lease_id": lease_id,
        "asset_id": ctx.lease.asset_id,
        "event_type": ctx.lease.event_type,
        "chunks_count": len(ctx.chunks),
        "chunk_ids": ctx.get_all_chunk_ids(),
    }
    append_entry(
        event_type="RETRIEVE",
        run_id=run_id,
        input_hash=hash_payload(lease_id),
        output_hash=hash_payload(detail),
        detail=detail,
        db_path=db_path,
    )

    return {
        "context": ctx,
        "lease": ctx.lease,
        "status": "RETRIEVED",
    }


def injection_guard_node(state: AgentState) -> AgentState:
    """Analyze chunks with RuleBasedGuard and isolate any malicious prompt injection."""
    run_id = state["run_id"]
    ctx: RetrievedLeaseContext = state["context"]
    db_path = state.get("db_path")

    guard = RuleBasedGuard(quarantine_threshold=0.75)
    safe_chunks, quarantined, flags = guard.quarantine_chunks(ctx.chunks)

    quarantined_details = [
        {
            "chunk_id": q.chunk_id,
            "page": q.page,
            "score": q.score,
            "reasons": q.reasons,
            "text": q.text,
        }
        for q in quarantined
    ]

    detail = {
        "total_chunks": len(ctx.chunks),
        "safe_chunks_count": len(safe_chunks),
        "quarantined_count": len(quarantined),
        "quarantined_chunk_ids": flags,
        "quarantined_details": quarantined_details,
    }
    append_entry(
        event_type="INJECT_GUARD",
        run_id=run_id,
        input_hash=hash_payload([c.text for c in ctx.chunks]),
        output_hash=hash_payload(detail),
        detail=detail,
        db_path=db_path,
    )

    return {
        "safe_chunks": safe_chunks,
        "quarantined_chunk_ids": flags,
        "quarantined_details": quarantined_details,
        "status": "GUARDED",
    }


def build_prompt_node(state: AgentState) -> AgentState:
    """Assemble structured prompt with typed slots, SHA-256 hash, and error feedback."""
    ctx: RetrievedLeaseContext = state["context"]
    safe_chunks: List[RetrievedChunk] = state["safe_chunks"]
    quarantined_ids = state.get("quarantined_chunk_ids", [])
    error_context = state.get("error_context", [])
    extra_instructions = state.get("extra_instructions")

    today = date.today()
    try:
        exp_date = date.fromisoformat(ctx.lease.expiry_date)
        raw_diff = (exp_date - today).days
        days_to_event = max(1, min(180, raw_diff))
    except Exception:
        days_to_event = 60

    builder = (
        PromptBuilder()
        .set_asset_context_slot(ctx.lease)
        .set_lease_terms_slot(safe_chunks)
        .set_task_slot(
            lease=ctx.lease,
            days_to_event=days_to_event,
            injection_flags=quarantined_ids,
            error_context=error_context if error_context else None,
            extra_instructions=extra_instructions,
        )
    )
    assembled = builder.build()

    return {
        "prompt": assembled,
        "prompt_hash": assembled.prompt_hash,
        "status": "PROMPT_BUILT",
    }


def infer_node(state: AgentState) -> AgentState:
    """Execute LLM generation in either live or mock mode."""
    run_id = state["run_id"]
    prompt: AssembledPrompt = state["prompt"]
    ctx: RetrievedLeaseContext = state["context"]
    db_path = state.get("db_path")
    mock_fn = state.get("mock_override_fn")

    attempt = state.get("attempt_count", 0) + 1

    if mock_fn:
        raw_memo = mock_fn(prompt, ctx, attempt=attempt)
    else:
        raw_memo = generate_memo(prompt, ctx)

    detail = {
        "attempt": attempt,
        "prompt_hash": prompt.prompt_hash,
        "model_version": settings.LLM_MODEL if settings.LLM_MODE == "live" else "mock-deterministic-v1",
        "raw_memo_length": len(raw_memo),
    }
    append_entry(
        event_type="INFER",
        run_id=run_id,
        model_version=detail["model_version"],
        prompt_hash=prompt.prompt_hash,
        input_hash=hash_payload(prompt.full_text),
        output_hash=hash_payload(raw_memo),
        detail=detail,
        db_path=db_path,
    )

    return {
        "raw_memo": raw_memo,
        "status": "INFERRED",
    }


def validate_node(state: AgentState) -> AgentState:
    """Validate memo against register ground-truth and retrieved document citations."""
    run_id = state["run_id"]
    ctx: RetrievedLeaseContext = state["context"]
    raw_memo_str = state["raw_memo"]
    db_path = state.get("db_path")
    attempt = state.get("attempt_count", 0) + 1

    try:
        memo_dict = json.loads(raw_memo_str)
        # Carry quarantined injection chunk IDs if not already present
        q_ids = state.get("quarantined_chunk_ids", [])
        if q_ids and "injection_flags" in memo_dict:
            memo_dict["injection_flags"] = sorted(list(set(memo_dict["injection_flags"] + q_ids)))
        val_result: ValidationResult = validate_memo(memo_dict, ctx)
    except Exception as e:
        val_result = ValidationResult(
            ok=False,
            errors=[f"JSON parse or schema validation failed: {str(e)}"],
            error_codes=["SCHEMA_VALIDATION_ERROR"],
        )
        memo_dict = {}

    detail = {
        "attempt": attempt,
        "ok": val_result.ok,
        "errors": val_result.errors,
        "error_codes": val_result.error_codes,
        "warnings": val_result.warnings,
        "truncations": val_result.truncations,
    }
    append_entry(
        event_type="VALIDATE",
        run_id=run_id,
        input_hash=hash_payload(raw_memo_str),
        output_hash=hash_payload(detail),
        detail=detail,
        db_path=db_path,
    )

    if not val_result.ok:
        return {
            "validation_result": val_result.model_dump(),
            "attempt_count": attempt,
            "error_context": val_result.errors,
            "status": "VALIDATION_FAILED",
        }

    validated_memo = val_result.memo
    validated_dict = validated_memo.model_dump() if validated_memo else memo_dict
    low_confidence = (validated_memo.confidence_score < 0.6) if validated_memo else False

    return {
        "validation_result": val_result.model_dump(),
        "memo_dict": validated_dict,
        "attempt_count": attempt,
        "low_confidence": low_confidence,
        "no_auto_notify": low_confidence,
        "status": "VALIDATED",
    }


def route_decision_edge(state: AgentState) -> str:
    """Determine conditional routing branch after validation."""
    val_res = state.get("validation_result", {})
    if val_res.get("ok"):
        return "route"

    attempt_count = state.get("attempt_count", 0)
    if attempt_count < 2:
        return "retry"
    return "reject"


def route_node(state: AgentState) -> AgentState:
    """Store routed memo in inbox_items and dispatch notifications."""
    run_id = state["run_id"]
    lease_id = state["lease_id"]
    ctx: RetrievedLeaseContext = state["context"]
    memo_dict = state["memo_dict"]
    db_path = state.get("db_path")
    low_conf = state.get("low_confidence", False)
    no_auto_notify = state.get("no_auto_notify", False)

    memo_obj = LeaseEventMemo.model_validate(memo_dict)

    # Cited chunks collection
    cited_chunks = []
    chunk_map = {c.chunk_id: c for c in ctx.chunks}
    cited_ids = {
        memo_obj.tenant_name.source_chunk_id,
        memo_obj.passing_rent.source_chunk_id,
        memo_obj.event_date.source_chunk_id,
        memo_obj.rent_at_risk.source_chunk_id,
        memo_obj.reinstatement.source_chunk_id,
    }
    for bc in memo_obj.break_conditions:
        cited_ids.add(bc.source_chunk_id)

    for cid in cited_ids:
        if cid in chunk_map:
            c = chunk_map[cid]
            cited_chunks.append({
                "chunk_id": c.chunk_id,
                "page": c.page,
                "text": c.text,
                "lease_id": c.lease_id,
            })

    quarantined_json_str = json.dumps(state.get("quarantined_details", []))
    cited_chunks_json_str = json.dumps(cited_chunks)
    memo_json_str = json.dumps(memo_dict)
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO inbox_items (
                    run_id, lease_id, asset_id, memo_json, cited_chunks_json,
                    quarantined_json, urgency, confidence, low_confidence,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_approval', ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    memo_json=excluded.memo_json,
                    cited_chunks_json=excluded.cited_chunks_json,
                    quarantined_json=excluded.quarantined_json,
                    urgency=excluded.urgency,
                    confidence=excluded.confidence,
                    low_confidence=excluded.low_confidence,
                    status='pending_approval';
                """,
                (
                    run_id,
                    lease_id,
                    ctx.lease.asset_id,
                    memo_json_str,
                    cited_chunks_json_str,
                    quarantined_json_str,
                    memo_obj.urgency.value,
                    memo_obj.confidence_score,
                    1 if low_conf else 0,
                    now_iso,
                ),
            )
    finally:
        conn.close()

    persist_run_state(
        run_id=run_id,
        lease_id=lease_id,
        status="ROUTED_PENDING_APPROVAL",
        memo_json=memo_json_str,
        parent_run_id=state.get("parent_run_id"),
        db_path=db_path,
    )

    route_detail = {
        "status": "ROUTED_PENDING_APPROVAL",
        "urgency": memo_obj.urgency.value,
        "confidence": memo_obj.confidence_score,
        "low_confidence": low_conf,
        "no_auto_notify": no_auto_notify,
    }
    append_entry(
        event_type="ROUTE",
        run_id=run_id,
        input_hash=hash_payload(memo_dict),
        output_hash=hash_payload(route_detail),
        detail=route_detail,
        db_path=db_path,
    )

    # Dispatch notification to asset manager (or suppress if low confidence)
    send_notification(
        run_id=run_id,
        lease_id=lease_id,
        memo=memo_obj,
        context=ctx,
        no_auto_notify=no_auto_notify,
        db_path=db_path,
    )

    return {
        "status": "ROUTED_PENDING_APPROVAL",
    }


def reject_node(state: AgentState) -> AgentState:
    """Record terminal rejection when validation retries are exhausted."""
    run_id = state["run_id"]
    lease_id = state["lease_id"]
    db_path = state.get("db_path")
    error_context = state.get("error_context", [])

    persist_run_state(
        run_id=run_id,
        lease_id=lease_id,
        status="REJECTED_BY_VALIDATOR",
        parent_run_id=state.get("parent_run_id"),
        db_path=db_path,
    )

    reject_detail = {
        "status": "REJECTED_BY_VALIDATOR",
        "attempts": state.get("attempt_count", 0),
        "errors": error_context,
    }
    append_entry(
        event_type="ROUTE",
        run_id=run_id,
        input_hash=hash_payload(error_context),
        output_hash=hash_payload(reject_detail),
        detail=reject_detail,
        db_path=db_path,
    )

    return {
        "status": "REJECTED_BY_VALIDATOR",
    }


def build_agent_graph():
    """Construct and compile the LangGraph workflow."""
    builder = StateGraph(AgentState)

    builder.add_node("trigger", trigger_node)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("injection_guard", injection_guard_node)
    builder.add_node("build_prompt", build_prompt_node)
    builder.add_node("infer", infer_node)
    builder.add_node("validate", validate_node)
    builder.add_node("route", route_node)
    builder.add_node("reject", reject_node)

    builder.add_edge(START, "trigger")
    builder.add_edge("trigger", "retrieve")
    builder.add_edge("retrieve", "injection_guard")
    builder.add_edge("injection_guard", "build_prompt")
    builder.add_edge("build_prompt", "infer")
    builder.add_edge("infer", "validate")

    builder.add_conditional_edges(
        "validate",
        route_decision_edge,
        {
            "route": "route",
            "retry": "build_prompt",
            "reject": "reject",
        },
    )

    builder.add_edge("route", END)
    builder.add_edge("reject", END)

    return builder.compile()


# Global compiled workflow instance
agent_workflow = build_agent_graph()


def run_agent(
    lease_id: str,
    run_id: Optional[str] = None,
    parent_run_id: Optional[str] = None,
    extra_instructions: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
    chroma_dir: Optional[Union[str, Path]] = None,
    collection_name: Optional[str] = None,
    mock_override_fn: Optional[Callable[..., str]] = None,
) -> AgentState:
    """Execute the full agent workflow for a given lease."""
    initial_state: AgentState = {
        "run_id": run_id or str(uuid.uuid4()),
        "lease_id": lease_id,
        "parent_run_id": parent_run_id,
        "extra_instructions": extra_instructions,
        "attempt_count": 0,
        "error_context": [],
        "quarantined_chunk_ids": [],
        "quarantined_details": [],
        "low_confidence": False,
        "no_auto_notify": False,
        "db_path": str(db_path) if db_path else str(settings.DB_PATH),
        "chroma_dir": str(chroma_dir) if chroma_dir else str(settings.CHROMA_PERSIST_DIR),
        "collection_name": collection_name or "lease_documents",
        "mock_override_fn": mock_override_fn,
    }

    result = agent_workflow.invoke(initial_state)
    return result
