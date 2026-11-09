"""SupportDesk eval package (separate from the test suite).

The eval harness runs the labeled ticket corpus through a deterministic,
keyword-driven fake LLM and reports routing accuracy and tool-selection
accuracy. It is intentionally separate from `tests/` per the project spec.
"""
