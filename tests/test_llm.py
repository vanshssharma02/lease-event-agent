"""Unit tests for Milestone 4: LLM Client and End-to-End Mock Validation."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.config import settings
from app.db import init_db
from app.seed import seed_database, get_leases_in_window
from app.retrieval import retrieve, index_all_in_window, get_chroma_client
from app.guard import RuleBasedGuard
from app.prompt import PromptBuilder
from app.llm import generate_memo, generate_mock_memo, generate_live_memo
from app.validator import validate_memo, ValidationResult
from app.schemas import LeaseEventMemo


@pytest.fixture
def populated_env(tmp_path: Path):
    """Seed test database, generate PDFs, and index in ChromaDB."""
    db_file = tmp_path / "test_llm.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    chroma_dir = tmp_path / "chroma_db"
    chroma_dir.mkdir(parents=True, exist_ok=True)

    seed_database(db_path=db_file, data_dir=data_dir)
    client = get_chroma_client(chroma_dir)
    index_all_in_window(db_path=db_file, client=client, collection_name="test_llm_col")

    return db_file, data_dir, client


def test_mock_mode_output_passes_validator_for_all_three_leases(populated_env):
    """Critical Acceptance Test: Mock-mode output must pass validation for all 3 in-window leases."""
    db_file, _, client = populated_env
    guard = RuleBasedGuard()

    in_window = get_leases_in_window(days=180, db_path=db_file)
    assert len(in_window) == 3

    for item in in_window:
        lid = item["lease_id"]

        # 1. Retrieve typed context
        ctx = retrieve(lid, client=client, db_path=db_file, collection_name="test_llm_col")
        assert len(ctx.chunks) > 0

        # 2. Guard inspection and quarantine
        safe_chunks, quarantined, flags = guard.quarantine_chunks(ctx.chunks)

        # 3. Assemble prompt via PromptBuilder
        prompt = (
            PromptBuilder()
            .set_asset_context_slot(ctx.lease)
            .set_lease_terms_slot(safe_chunks)
            .set_task_slot(ctx.lease, days_to_event=60, injection_flags=flags)
            .build()
        )
        assert len(prompt.prompt_hash) == 64

        # 4. Generate memo in mock mode
        raw_json = generate_memo(prompt, ctx, mode="mock")
        assert isinstance(raw_json, str)

        memo_dict = json.loads(raw_json)
        assert memo_dict["lease_id"] == lid
        assert memo_dict["prompt_hash"] == prompt.prompt_hash

        # 5. Run validator against retrieved ground-truth
        val_result: ValidationResult = validate_memo(memo_dict, ctx)

        # 6. Assert clean pass
        assert val_result.ok is True, f"Validation failed for {lid}: {val_result.errors}"
        assert len(val_result.errors) == 0
        assert val_result.memo is not None
        assert val_result.memo.tenant_name.value == ctx.lease.tenant
        assert val_result.memo.passing_rent.amount == ctx.lease.passing_rent


def test_live_mode_requires_api_key(populated_env):
    db_file, _, client = populated_env
    ctx = retrieve("LSE-EXP-001", client=client, db_path=db_file, collection_name="test_llm_col")
    prompt = (
        PromptBuilder()
        .set_asset_context_slot(ctx.lease)
        .set_lease_terms_slot(ctx.chunks)
        .set_task_slot(ctx.lease, days_to_event=60)
        .build()
    )

    with patch.object(settings, "OPENROUTER_API_KEY", ""):
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY is not configured"):
            generate_live_memo(prompt, ctx)


def test_live_mode_fallback_on_primary_failure(populated_env):
    """Test that live generation attempts fallback model if primary model fails."""
    db_file, _, client = populated_env
    ctx = retrieve("LSE-EXP-001", client=client, db_path=db_file, collection_name="test_llm_col")
    prompt = (
        PromptBuilder()
        .set_asset_context_slot(ctx.lease)
        .set_lease_terms_slot(ctx.chunks)
        .set_task_slot(ctx.lease, days_to_event=60)
        .build()
    )

    mock_openai = MagicMock()
    # Primary model throws exception, fallback succeeds
    from openai import APIError

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content='{"status": "fallback_success"}'))
    ]

    def side_effect(*args, **kwargs):
        if kwargs.get("model") == settings.LLM_MODEL:
            raise APIError("Rate limit exceeded on primary model", request=None, body=None)
        return mock_response

    mock_openai.chat.completions.create.side_effect = side_effect

    with patch.object(settings, "OPENROUTER_API_KEY", "test-key"):
        result = generate_live_memo(prompt, ctx, client=mock_openai, max_retries=1)
        assert result == '{"status": "fallback_success"}'
        assert mock_openai.chat.completions.create.call_count >= 2
