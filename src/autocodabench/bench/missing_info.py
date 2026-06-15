"""Cross-run aggregation of missing-information inventories.

The plan and build phases each emit a ``missing_info_report.json`` recording
what the model had to infer because the proposal did not state it (schema in
``benchmark/README.md``). This module aggregates a list of such reports into
cross-run statistics — totals by section/severity/impact/resolution, the
most-missed fields, and the high-stakes inferences that could change scoring.

Ported verbatim (the pure-data ``aggregate``) from the old experiment
harness's ``aggregate_missing_info.py`` so it is reusable as a library and
unit-testable keylessly. Filesystem discovery is provided separately and is
root-agnostic.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def discover_reports(root: str | Path, glob: str = "**/missing_info_report.json") -> list[Path]:
    """Find every missing-info report under ``root`` (any depth)."""
    return sorted(Path(root).glob(glob))


def load_report(path: str | Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:  # pragma: no cover - I/O guard
        print(f"  WARN: could not parse {path}: {e}", file=sys.stderr)
        return None


def aggregate(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Return an aggregation suitable for both human and JSON output."""
    by_comp_runs: dict[str, int] = defaultdict(int)
    by_comp_with_items: dict[str, int] = defaultdict(int)
    all_items: list[dict] = []
    section_counter: Counter = Counter()
    field_counter: Counter = Counter()  # (section, field)
    severity_counter: Counter = Counter()
    impact_counter: Counter = Counter()
    action_counter: Counter = Counter()
    confidence_counter: Counter = Counter()
    high_stakes: list[dict] = []  # would_block_correct_scoring == true

    for r in reports:
        comp = r.get("competition_sample_name", "<unknown>")
        by_comp_runs[comp] += 1
        items = r.get("items", []) or []
        if items:
            by_comp_with_items[comp] += 1
        for it in items:
            all_items.append(it)
            section = it.get("section", "<unknown>")
            field = it.get("field", "<unknown>")
            severity = it.get("severity", "<unknown>")
            impact = it.get("impact_area", "<unknown>")
            resolution = it.get("resolution") or {}
            action = resolution.get("action", "<unknown>")
            confidence = resolution.get("confidence", "<unknown>")

            section_counter[section] += 1
            field_counter[(section, field)] += 1
            severity_counter[severity] += 1
            impact_counter[impact] += 1
            action_counter[action] += 1
            confidence_counter[confidence] += 1

            if resolution.get("would_block_correct_scoring"):
                high_stakes.append({
                    "competition_sample_name": comp,
                    "run_id": r.get("run_id"),
                    "section": section,
                    "field": field,
                    "what_was_missing": it.get("what_was_missing", "")[:200],
                    "resolution_choice": resolution.get("choice", "")[:200],
                    "confidence": confidence,
                })

    return {
        "total_runs": len(reports),
        "total_items": len(all_items),
        "items_per_run_avg": round(len(all_items) / len(reports), 2) if reports else 0,
        "by_competition_sample": {
            comp: {
                "runs": by_comp_runs[comp],
                "runs_with_items": by_comp_with_items[comp],
            } for comp in sorted(by_comp_runs)
        },
        "by_section": dict(section_counter.most_common()),
        "by_severity": dict(severity_counter.most_common()),
        "by_impact_area": dict(impact_counter.most_common()),
        "by_resolution_action": dict(action_counter.most_common()),
        "by_confidence": dict(confidence_counter.most_common()),
        "top_fields": [
            {"section": section, "field": field, "count": n}
            for (section, field), n in field_counter.most_common()
        ],
        "high_stakes_inferences": high_stakes,
    }
