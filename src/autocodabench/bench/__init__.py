"""Evaluation utilities shared by the benchmark harnesses under ``benchmark/``.

These are the deterministic, model-independent pieces the benchmarks lean on:

- :mod:`.audit` — compare a produced score to a ground-truth
  ``expected_result.json`` within tolerance (pure arithmetic; no LLM).
- :mod:`.results` — the canonical, versioned result record that every
  benchmark run emits, so contributed results aggregate commensurably.
- :mod:`.missing_info` — cross-run aggregation of missing-information
  inventories.
- :mod:`.report` — render a human ``run_report.md`` from a result record.

Keeping them in the installable package (rather than under ``benchmark/``)
gives the harness scripts clean imports and lets the unit suite cover them
keylessly.
"""
from __future__ import annotations

from . import audit, missing_info, report, results

__all__ = ["audit", "missing_info", "report", "results"]
