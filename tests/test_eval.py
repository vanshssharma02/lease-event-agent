"""Unit tests for the evaluation harness.

Verifies:
  1. Golden dataset dynamically resolves relative dates
  2. Injection test set loads valid categories and labels
  3. RuleBasedGuard evaluation produces expected confusion matrix metrics
  4. run_evaluation executes in mock mode and outputs valid results.json and RESULTS.md
"""

from pathlib import Path
import json
import pytest

from eval.run_eval import (
    load_ground_truth,
    load_injection_cases,
    evaluate_injection_guard,
    run_evaluation,
    RESULTS_JSON_PATH,
    RESULTS_MD_PATH,
)


def test_load_ground_truth():
    """Verify ground truth loader resolves all 3 in-window leases with dynamic ISO dates."""
    golden = load_ground_truth()
    assert len(golden) == 3
    assert "LSE-EXP-001" in golden
    assert "LSE-BRK-002" in golden
    assert "LSE-REV-003" in golden

    for lid, item in golden.items():
        assert "event_date" in item
        assert len(item["event_date"]) == 10  # YYYY-MM-DD
        assert item["passing_rent"] > 0
        assert item["currency"] == "GBP"
        assert len(item["break_conditions_keywords"]) > 0


def test_load_injection_cases():
    """Verify injection cases dataset contains balanced adversarial and benign chunks."""
    cases = load_injection_cases()
    assert len(cases) >= 24

    injected = [c for c in cases if c["is_injected"]]
    benign = [c for c in cases if not c["is_injected"]]

    assert len(injected) >= 12
    assert len(benign) >= 12

    # Verify categories coverage
    categories = {c["category"] for c in cases}
    expected_categories = {
        "role_reassignment",
        "instruction_override",
        "exfiltration_probe",
        "jailbreak_scaffolding",
        "base64_payload",
        "zero_width",
        "homoglyph",
        "subtle_paraphrased",
        "contractual_phrasing",
        "standard_lease_clause",
    }
    assert expected_categories.issubset(categories)


def test_evaluate_injection_guard():
    """Verify confusion matrix calculations across injection test cases."""
    cases = load_injection_cases()
    res = evaluate_injection_guard(cases)

    cm = res["confusion_matrix"]
    gm = res["metrics"]

    assert cm["total_samples"] == len(cases)
    assert cm["true_positives"] > 0
    assert cm["true_negatives"] > 0

    assert 0.0 <= gm["precision"] <= 1.0
    assert 0.0 <= gm["recall"] <= 1.0
    assert 0.0 <= gm["false_positive_rate"] <= 1.0


def test_run_evaluation_produces_artifacts():
    """Verify run_evaluation executes end-to-end and creates non-empty artifacts."""
    results = run_evaluation(mode="mock", runs=1)
    assert results is not None
    assert "agent_evaluation" in results
    assert "injection_guard_evaluation" in results

    agent_eval = results["agent_evaluation"]
    assert agent_eval["extraction_accuracy"] >= 0.95
    assert agent_eval["citation_validity"] >= 0.95
    assert agent_eval["schema_pass_rate"] >= 0.90
    assert agent_eval["rejection_rate"] == 0.0

    assert RESULTS_JSON_PATH.exists()
    assert RESULTS_JSON_PATH.stat().st_size > 0

    assert RESULTS_MD_PATH.exists()
    assert RESULTS_MD_PATH.stat().st_size > 0

    with open(RESULTS_MD_PATH, "r", encoding="utf-8") as f:
        md_content = f.read()
    assert "Executive Performance Summary" in md_content
    assert "Confusion Matrix" in md_content
