"""MCP tools that drive the per-session starting_kit.ipynb.

Stage model: 0.roadmap, 1.setup, 2.data, 3.eda, 4.metric, 5.baseline,
6.predict_score, 7.diagnostics, 8.bundle (see notebook_kernel.STAGES).

The agent's typical loop for one stage is:
  - nb_write_cell(stage, "markdown", "## Stage 2 — Data loader")
  - nb_write_cell(stage, "code", "import pandas as pd ...")
  - nb_write_cell(stage, "code", "...")
  - nb_run_stage(stage)        ← kernel executes; outputs land in the notebook
  - nb_render_html()           ← optional; web UI calls this on each turn
  - log_event(kind="stage_done", payload={...})

If the user clicks "Revise this stage" in the UI, the web layer calls
nb_reset_to_stage(stage), which restarts the kernel and re-runs all
earlier stages so the agent's refined cells re-execute against the same
context.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..mcp import mcp
from ..run_log import current_run, logged_tool
from .. import notebook_kernel as nbk

log = logging.getLogger("autocodabench.tools.notebook")


def _run_dir_or_error() -> tuple[Path | None, dict[str, Any] | None]:
    """Resolve the active run dir; return (run_dir, None) or (None, err_dict)."""
    p = current_run()
    if p is None:
        return None, {"error": "no active run — call autocodabench_open_run first"}
    return p, None


@mcp.tool()
@logged_tool("autocodabench_nb_init")
async def autocodabench_nb_init() -> dict[str, Any]:
    """Create or reset `<run>/starting_kit.ipynb` to an empty notebook.

    Call this once near the start of stage 1 (Setup). Idempotent — safe
    to call again if you want to start over from scratch.
    """
    run, err = _run_dir_or_error()
    if err:
        return err
    return await nbk.init_notebook(run)


@mcp.tool()
@logged_tool("autocodabench_nb_write_cell")
async def autocodabench_nb_write_cell(
    stage: str,
    cell_type: str,
    source: str,
    position: str = "stage_end",
) -> dict[str, Any]:
    """Append or insert a cell into the starting kit, tagged with `stage`.

    Args:
        stage: one of `0.roadmap`, `1.setup`, `2.data`, `3.eda`,
               `4.metric`, `5.baseline`, `6.predict_score`,
               `7.diagnostics`, `8.bundle`.
        cell_type: `code` or `markdown`.
        source: full cell content (multi-line ok).
        position: `stage_end` (default — insert at the end of this
                  stage's contiguous block, preserving topological order)
                  or `append` (always at the end of the notebook).

    Returns: {"cells": <total>, "stage": ..., "stages_present": [...]}.
    """
    run, err = _run_dir_or_error()
    if err:
        return err
    return nbk.write_cell(run, stage, cell_type, source, position=position)


@mcp.tool()
@logged_tool("autocodabench_nb_run_stage")
async def autocodabench_nb_run_stage(stage: str) -> dict[str, Any]:
    """Execute every cell tagged with `stage`. Persists outputs into the notebook.

    The persistent kernel keeps state across stages — variables from
    `1.setup` are visible in `2.data`, etc. If the user revises an
    earlier stage, the kernel is restarted automatically (see
    `autocodabench_nb_reset_to_stage`).

    Returns per-cell summary {"index", "ok", "error_name", "error_value",
    "n_outputs"} plus an `all_ok` boolean.
    """
    run, err = _run_dir_or_error()
    if err:
        return err
    return await nbk.run_stage(run, stage)


@mcp.tool()
@logged_tool("autocodabench_nb_reset_to_stage")
async def autocodabench_nb_reset_to_stage(stage: str) -> dict[str, Any]:
    """Restart the kernel; re-run every stage *before* `stage`.

    Use this when the user clicked "Revise this stage" in the UI: the
    web layer routes that click through this tool. After it returns,
    the agent re-writes cells for `stage` (and possibly later stages)
    and calls `autocodabench_nb_run_stage(stage)` again.
    """
    run, err = _run_dir_or_error()
    if err:
        return err
    return await nbk.reset_to_stage(run, stage)


@mcp.tool()
@logged_tool("autocodabench_nb_render_html")
async def autocodabench_nb_render_html() -> dict[str, Any]:
    """Render `<run>/starting_kit.ipynb` (with current outputs) to HTML.

    Returns {"html": "...", "cells": N}. The HTML is sanitised by
    nbconvert and safe to embed inside a markdown viewer (Chainlit's
    cl.Text with unsafe_allow_html=true).
    """
    run, err = _run_dir_or_error()
    if err:
        return err
    return nbk.render_html(run)


@mcp.tool()
@logged_tool("autocodabench_nb_shutdown")
async def autocodabench_nb_shutdown() -> dict[str, Any]:
    """Cleanly shut the kernel down. Idempotent.

    Called by the web layer on chat end; the agent doesn't normally
    need this.
    """
    return await nbk.shutdown()
