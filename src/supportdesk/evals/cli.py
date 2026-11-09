"""Command-line entry point for the eval harness.

Usage::

    python -m supportdesk.evals.cli run [--sample] [--baseline]

``--baseline`` compares the computed metrics against the committed baseline
(``data/eval_baseline.json``) and exits non-zero if accuracy drops below it --
this is the CI eval gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .harness import BASELINE_PATH, load_baseline, run_eval, write_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SupportDesk eval harness")
    parser.add_argument("command", choices=["run"], help="Run the eval corpus")
    parser.add_argument(
        "--sample", action="store_true", help="Run only a sample of the corpus (first 20 tickets)"
    )
    parser.add_argument(
        "--baseline", action="store_true", help="Compare against the committed baseline (CI gate)"
    )
    args = parser.parse_args(argv)

    cases = run_eval()
    if args.sample:
        cases = cases[:20]
    metrics = write_report(cases)
    print(json.dumps(metrics, indent=2))

    if args.baseline:
        baseline = load_baseline()
        if baseline is None:
            print(f"No baseline found at {BASELINE_PATH}; creating one.")
            _write_baseline(metrics)
            return 0
        routing_drop = baseline["routing_accuracy"] - metrics["routing_accuracy"]
        tool_drop = baseline["tool_selection_accuracy"] - metrics["tool_selection_accuracy"]
        if routing_drop > 0.05 or tool_drop > 0.05:
            print(
                f"EVAL GATE FAILED: routing {baseline['routing_accuracy']} -> "
                f"{metrics['routing_accuracy']}, tool {baseline['tool_selection_accuracy']} -> "
                f"{metrics['tool_selection_accuracy']}"
            )
            return 1
        print("Eval gate passed: accuracy at or above committed baseline.")
    return 0


def _write_baseline(metrics: dict[str, Any]) -> None:
    import os

    os.makedirs(os.path.dirname(BASELINE_PATH), exist_ok=True)
    baseline = {
        "routing_accuracy": metrics["routing_accuracy"],
        "tool_selection_accuracy": metrics["tool_selection_accuracy"],
        "total_cases": metrics["total_cases"],
    }
    with open(BASELINE_PATH, "w") as f:
        json.dump(baseline, f, indent=2)
    print(f"Baseline written to {BASELINE_PATH}")


if __name__ == "__main__":
    sys.exit(main())
