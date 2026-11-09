"""Eval tests: run the labeled ticket corpus through a deterministic fake LLM
and report routing / tool-selection accuracy against a committed baseline.

Evals are separate from unit/integration tests: they measure the quality of the
agent's decisions rather than the correctness of individual functions.
"""

import pytest

from supportdesk.evals.cli import main as eval_main
from supportdesk.evals.harness import load_baseline, run_eval, write_report

pytestmark = pytest.mark.eval


def test_eval_accuracy_matches_baseline():
    cases = run_eval()
    metrics = write_report(cases)

    baseline = load_baseline()
    assert baseline is not None, "committed baseline missing"

    # The eval gate: accuracy must not drop more than 5 points vs baseline.
    routing_drop = baseline["routing_accuracy"] - metrics["routing_accuracy"]
    tool_drop = baseline["tool_selection_accuracy"] - metrics["tool_selection_accuracy"]
    assert routing_drop <= 0.05, f"routing accuracy dropped: {routing_drop}"
    assert tool_drop <= 0.05, f"tool-selection accuracy dropped: {tool_drop}"

    # Sanity: the corpus is non-empty and both metrics are computed.
    assert metrics["total_cases"] > 0
    assert 0.0 <= metrics["routing_accuracy"] <= 1.0
    assert 0.0 <= metrics["tool_selection_accuracy"] <= 1.0


def test_eval_cli_baseline_gate():
    # The CLI --baseline flag is the CI eval gate; it must exit 0 at baseline.
    assert eval_main(["run", "--baseline"]) == 0
