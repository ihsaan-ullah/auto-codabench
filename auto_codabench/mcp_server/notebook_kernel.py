"""Per-run Jupyter kernel + starting_kit.ipynb authoring helpers.

The new stage-by-stage UX (see web/app.py + the orchestrator skill)
builds a `starting_kit.ipynb` cell-group by cell-group: the agent
writes cells via MCP tools, the kernel executes them, outputs land
inside the notebook, the web UI renders the executed notebook in the
side panel.

This module owns:
  - one persistent `AsyncKernelManager` per MCP-server subprocess
    (i.e. per Chainlit session — each session spawns its own
    autocodabench MCP subprocess);
  - a "stage" model where cells are tagged with the stage that wrote
    them, so we can re-execute / reset by stage;
  - notebook (de)serialization in nbformat-v4;
  - HTML rendering via nbconvert.HTMLExporter.

Scope: HF Spaces alpha. CPU only, toy-data baselines. No GPU paths,
no shell-out beyond what the kernel itself runs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import queue
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import nbformat
from nbformat import NotebookNode, v4 as nbv4

log = logging.getLogger("autocodabench.notebook")

# Default cell-execution timeout. Toy data should be well under this;
# anything blocking longer is almost always a bug in the agent's code.
CELL_TIMEOUT_S = 60

# Stage names — must stay in sync with web/app.py's TaskList nodes and
# the orchestrator skill's stage table.
STAGES = [
    "0.roadmap",      # design-only, no cells
    "1.setup",
    "2.data",
    "3.eda",
    "4.metric",
    "5.baseline",
    "6.predict_score",
    "7.diagnostics",
    "8.bundle",       # packaging — runs autocodabench bundle-write tools
]


# ---------------------------------------------------------------------------
# Notebook on-disk helpers (pure, no kernel involved)
# ---------------------------------------------------------------------------

def _nb_path(run_dir: Path) -> Path:
    return run_dir / "starting_kit.ipynb"


def _load_or_new_notebook(run_dir: Path) -> NotebookNode:
    p = _nb_path(run_dir)
    if p.is_file():
        try:
            return nbformat.read(p, as_version=4)
        except Exception as e:
            log.warning("starting_kit.ipynb unreadable (%s) — starting fresh", e)
    nb = nbv4.new_notebook()
    nb["metadata"]["kernelspec"] = {
        "name": "python3",
        "display_name": "Python 3",
        "language": "python",
    }
    nb["metadata"]["autocodabench"] = {"stages_present": []}
    return nb


def _save_notebook(run_dir: Path, nb: NotebookNode) -> None:
    nbformat.write(nb, _nb_path(run_dir))


def _stage_index(stage: str) -> int:
    try:
        return STAGES.index(stage)
    except ValueError:
        return -1


def _cell_stage(cell: NotebookNode) -> str | None:
    return (cell.get("metadata") or {}).get("autocodabench_stage")


# ---------------------------------------------------------------------------
# Kernel manager
# ---------------------------------------------------------------------------

@dataclass
class _KernelState:
    """In-process state for the one kernel this subprocess owns."""
    km: Any = None      # jupyter_client.AsyncKernelManager
    kc: Any = None      # AsyncKernelClient
    run_dir: Path | None = None
    started_stages: list[str] = field(default_factory=list)


_kernel = _KernelState()


async def _ensure_kernel(run_dir: Path) -> None:
    """Lazy-start the kernel on first execution call."""
    from jupyter_client.manager import AsyncKernelManager  # local import: heavy

    if _kernel.km is not None and _kernel.run_dir == run_dir:
        # Already up and pointing at this run.
        try:
            await _kernel.kc.is_alive() if hasattr(_kernel.kc, "is_alive") else None
        except Exception:
            pass
        if await _is_kernel_alive():
            return
        # Dead → fall through to restart.
        await _shutdown_kernel()

    elif _kernel.km is not None and _kernel.run_dir != run_dir:
        # Run dir changed under us (shouldn't normally happen — one
        # MCP subprocess per session) — shut down and restart.
        await _shutdown_kernel()

    km = AsyncKernelManager(kernel_name="python3")
    # Set cwd to the run dir so relative file IO from cells lands here.
    await km.start_kernel(cwd=str(run_dir))
    kc = km.client()
    kc.start_channels()
    await kc.wait_for_ready(timeout=30)
    _kernel.km = km
    _kernel.kc = kc
    _kernel.run_dir = run_dir
    _kernel.started_stages = []
    # AsyncKernelManager doesn't reliably expose .kernel.pid before the
    # provisioner finishes wiring; provisioner has .pid in jupyter_client
    # 8.x but it's fine to just skip if absent.
    pid = getattr(getattr(km, "provisioner", None), "pid", None) or getattr(km, "pid", None)
    log.info("kernel up for %s (pid=%s)", run_dir, pid)


async def _is_kernel_alive() -> bool:
    if _kernel.km is None:
        return False
    try:
        return await _kernel.km.is_alive()
    except Exception:
        return False


async def _shutdown_kernel() -> None:
    if _kernel.kc is not None:
        try:
            _kernel.kc.stop_channels()
        except Exception:
            pass
    if _kernel.km is not None:
        try:
            await _kernel.km.shutdown_kernel(now=True)
        except Exception:
            pass
    _kernel.km = None
    _kernel.kc = None
    _kernel.run_dir = None
    _kernel.started_stages = []


# ---------------------------------------------------------------------------
# Cell execution
# ---------------------------------------------------------------------------

async def _execute_cell(cell: NotebookNode) -> NotebookNode:
    """Execute one code cell, attach its outputs to it, return it.

    Markdown / raw cells are returned unchanged.
    """
    if cell.cell_type != "code":
        return cell
    kc = _kernel.kc
    if kc is None:
        raise RuntimeError("kernel not started")
    msg_id = kc.execute(cell.source, allow_stdin=False)
    outputs: list[NotebookNode] = []
    deadline_loop = asyncio.get_event_loop().time() + CELL_TIMEOUT_S
    while True:
        try:
            msg = await asyncio.wait_for(kc.get_iopub_msg(), timeout=1.0)
        except asyncio.TimeoutError:
            if asyncio.get_event_loop().time() > deadline_loop:
                outputs.append(nbv4.new_output(
                    output_type="error",
                    ename="CellTimeout",
                    evalue=f"cell exceeded {CELL_TIMEOUT_S}s",
                    traceback=[f"CellTimeout: cell exceeded {CELL_TIMEOUT_S}s"],
                ))
                break
            continue
        if msg.get("parent_header", {}).get("msg_id") != msg_id:
            continue
        mt = msg["msg_type"]
        c = msg.get("content", {})
        if mt == "status" and c.get("execution_state") == "idle":
            break
        if mt == "stream":
            outputs.append(nbv4.new_output(
                output_type="stream",
                name=c.get("name", "stdout"),
                text=c.get("text", ""),
            ))
        elif mt in ("display_data", "execute_result"):
            outputs.append(nbv4.new_output(
                output_type=mt,
                data=c.get("data", {}),
                metadata=c.get("metadata", {}),
                execution_count=c.get("execution_count"),
            ))
        elif mt == "error":
            outputs.append(nbv4.new_output(
                output_type="error",
                ename=c.get("ename", ""),
                evalue=c.get("evalue", ""),
                traceback=c.get("traceback", []),
            ))
    cell.outputs = outputs
    return cell


# ---------------------------------------------------------------------------
# Public API used by tools/notebook.py
# ---------------------------------------------------------------------------

async def init_notebook(run_dir: Path) -> dict[str, Any]:
    """Create / reset starting_kit.ipynb; do NOT touch the kernel."""
    nb = nbv4.new_notebook()
    nb["metadata"]["kernelspec"] = {
        "name": "python3", "display_name": "Python 3", "language": "python",
    }
    nb["metadata"]["autocodabench"] = {"stages_present": []}
    _save_notebook(run_dir, nb)
    return {"path": str(_nb_path(run_dir)), "cells": 0}


def write_cell(
    run_dir: Path,
    stage: str,
    cell_type: str,
    source: str,
    position: str = "append",
) -> dict[str, Any]:
    """Insert / append a cell tagged with `stage`.

    `position` is one of:
      - "append"  — at the end of the notebook (default);
      - "stage_end" — at the end of the contiguous block for this stage
        (or after the last cell of the previous stage if none exist yet).

    Returns the new index of the cell and the running cell count.
    """
    if cell_type not in ("code", "markdown"):
        return {"error": f"cell_type must be code|markdown, got {cell_type!r}"}
    if _stage_index(stage) < 0:
        return {"error": f"unknown stage {stage!r}; valid: {STAGES}"}

    nb = _load_or_new_notebook(run_dir)
    new_cell = (nbv4.new_code_cell(source=source)
                if cell_type == "code"
                else nbv4.new_markdown_cell(source=source))
    new_cell.setdefault("metadata", {})["autocodabench_stage"] = stage

    if position == "append":
        nb.cells.append(new_cell)
    else:  # "stage_end" — insert after the last cell belonging to this stage,
           # or after the last cell of any earlier stage.
        target_si = _stage_index(stage)
        last_at_or_before = -1
        for i, c in enumerate(nb.cells):
            si = _stage_index(_cell_stage(c) or "")
            if 0 <= si <= target_si:
                last_at_or_before = i
        insert_at = last_at_or_before + 1
        nb.cells.insert(insert_at, new_cell)

    stages_present = sorted({_cell_stage(c) for c in nb.cells if _cell_stage(c)})
    nb["metadata"]["autocodabench"]["stages_present"] = stages_present

    _save_notebook(run_dir, nb)
    return {
        "cells": len(nb.cells),
        "stage": stage,
        "stages_present": stages_present,
    }


async def run_stage(run_dir: Path, stage: str) -> dict[str, Any]:
    """Execute every cell tagged with `stage` in their notebook order.

    Cells from earlier stages are NOT re-run — we rely on the kernel
    being warm (or, on hybrid-reset, already re-warmed by run_stage()
    on earlier stages). This matches the chosen "Hybrid persistent
    during a stage, reset on Revise" kernel strategy.

    Returns a summary: per-cell index, success flag, and any error
    name/value. Cell outputs are also persisted into the notebook.
    """
    if _stage_index(stage) < 0:
        return {"error": f"unknown stage {stage!r}; valid: {STAGES}"}
    await _ensure_kernel(run_dir)
    nb = _load_or_new_notebook(run_dir)
    summaries = []
    for i, cell in enumerate(nb.cells):
        if _cell_stage(cell) != stage:
            continue
        if cell.cell_type != "code":
            summaries.append({"index": i, "type": "markdown", "ok": True})
            continue
        cell = await _execute_cell(cell)
        nb.cells[i] = cell
        err = next((o for o in cell.outputs if o.get("output_type") == "error"), None)
        summaries.append({
            "index": i,
            "type": "code",
            "ok": err is None,
            "error_name":  (err or {}).get("ename"),
            "error_value": (err or {}).get("evalue"),
            "n_outputs": len(cell.outputs),
        })
    _save_notebook(run_dir, nb)
    if stage not in _kernel.started_stages:
        _kernel.started_stages.append(stage)
    return {
        "stage": stage,
        "cells_executed": [s for s in summaries if s.get("type") == "code"],
        "all_ok": all(s["ok"] for s in summaries),
    }


async def reset_to_stage(run_dir: Path, stage: str) -> dict[str, Any]:
    """Restart the kernel and re-run all stages strictly *before* `stage`.

    Used when the user clicks "Revise this stage" — we need a clean
    kernel state up to (but not including) the target stage, so the
    agent's refined cells run on the same context as last time.
    """
    target = _stage_index(stage)
    if target < 0:
        return {"error": f"unknown stage {stage!r}"}
    # Drop the existing kernel.
    await _shutdown_kernel()
    nb = _load_or_new_notebook(run_dir)
    # Drop output state for `stage` and later cells (they'll be re-written).
    for c in nb.cells:
        if _stage_index(_cell_stage(c) or "") >= target and c.cell_type == "code":
            c.outputs = []
            c.execution_count = None
    _save_notebook(run_dir, nb)
    # Re-warm by running every earlier stage in order.
    rerun_summary = []
    for s in STAGES[:target]:
        if s in {"0.roadmap", "8.bundle"}:
            continue  # design-only / packaging stages don't have kernel cells
        # Only re-run if there are any cells for it.
        any_cells = any(_cell_stage(c) == s for c in nb.cells)
        if not any_cells:
            continue
        summary = await run_stage(run_dir, s)
        rerun_summary.append(summary)
    return {
        "reset_to": stage,
        "re_executed": rerun_summary,
        "kernel": "fresh",
    }


def render_html(run_dir: Path) -> dict[str, Any]:
    """Render the current notebook to a self-contained HTML string.

    Used by the web UI to display the executed notebook in
    cl.ElementSidebar. nbconvert's HTMLExporter sanitises the output.
    """
    from nbconvert import HTMLExporter
    nb = _load_or_new_notebook(run_dir)
    if not nb.cells:
        return {"html": "<p><em>No cells yet.</em></p>", "cells": 0}
    exporter = HTMLExporter(template_name="basic")
    body, _ = exporter.from_notebook_node(nb)
    return {"html": body, "cells": len(nb.cells)}


async def shutdown(run_dir: Path | None = None) -> dict[str, Any]:
    """Tear down the kernel (e.g. on chat end). Idempotent."""
    await _shutdown_kernel()
    return {"shutdown": True}
