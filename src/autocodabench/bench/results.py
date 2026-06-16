"""The canonical, versioned benchmark result record.

Every benchmark run (create-bench now; validate-bench later) emits one of
these as ``results.json``. It is the **append-only contribution unit**: a
contributor runs a backbone, commits the resulting record under
``benchmark/<bench>/results/<backbone-tag>/<run-id>.json``, and an
aggregation step (Stage 3) folds all records into the committed leaderboard.
Because the schema is fixed and versioned, records from different machines,
backbones, and dates remain commensurable.

Privacy invariant: the backend descriptor records the *host* of an endpoint,
never the API key.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = 1

_REQUIRED_KEYS = ("schema_version", "benchmark", "backend", "competition",
                  "metrics", "generated_at")


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def _acb_version() -> str:
    try:
        from importlib.metadata import version
        return version("autocodabench")
    except Exception:
        return "unknown"


def backend_tag(spec: str | None) -> str:
    """Filesystem-safe partition name for a backend spec (for results/<tag>/)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", spec or "claude")


def backend_descriptor(backend: Any, *, spec: str | None = None,
                       model: str | None = None) -> dict[str, Any]:
    """Describe a backend for the record — name, spec, model, endpoint host.

    Never includes credentials. ``endpoint_host`` is populated for
    OpenAI-compatible backends (Ollama/vLLM/OpenAI) from their base URL.
    """
    host = None
    base_url = getattr(backend, "base_url", None)
    if base_url:
        try:
            host = urlparse(base_url).hostname
        except Exception:
            host = None
    return {
        "spec": spec,
        "name": getattr(backend, "name", None),
        "model": model or getattr(backend, "model", None),
        "endpoint_host": host,
    }


def new_result(*, benchmark: str, competition: str, backend: dict[str, Any],
               metrics: dict[str, Any], run_id: str | None = None,
               cost_usd: float | None = None, tokens: dict | None = None,
               turns: int | None = None, hardware_tag: str | None = None,
               instrument_version: dict | None = None,
               git_sha: str | None = None,
               generated_at: str | None = None,
               research: dict | None = None) -> dict[str, Any]:
    """Assemble a complete, schema-stamped result record.

    ``research`` records the Phase-1 external-knowledge capability for this run
    (requested config, whether the backbone could use it, and which sources were
    effectively active) — load-bearing for fair cross-backbone comparison, since
    only the Claude backend can reach external MCP / web tools.
    """
    if git_sha is None:
        try:
            from ..run_log import _git_sha
            git_sha = _git_sha()
        except Exception:
            git_sha = None
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": benchmark,
        "run_id": run_id,
        "generated_at": generated_at or _utc_now(),
        "autocodabench_version": _acb_version(),
        "git_sha": git_sha,
        "backend": backend,
        "hardware_tag": hardware_tag,
        "instrument_version": instrument_version or {},
        "competition": competition,
        "metrics": metrics,
        "research": research,
        "cost_usd": cost_usd,
        "tokens": tokens,
        "turns": turns,
    }


def validate(result: dict[str, Any]) -> list[str]:
    """Return a list of schema problems (empty == valid)."""
    problems = []
    for k in _REQUIRED_KEYS:
        if k not in result:
            problems.append(f"missing required key: {k}")
    sv = result.get("schema_version")
    if sv != SCHEMA_VERSION:
        problems.append(f"schema_version {sv!r} != {SCHEMA_VERSION}")
    if result.get("benchmark") not in ("create", "validate"):
        problems.append(f"unexpected benchmark: {result.get('benchmark')!r}")
    if not isinstance(result.get("metrics"), dict):
        problems.append("metrics must be an object")
    return problems


def dump(result: dict[str, Any], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return p


def load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
