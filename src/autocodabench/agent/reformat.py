"""The reformat-and-run phase: score one external submission via a bundle.

This is the SDK analog of the old ``claude -p "/autocodabench-reformat-and-run"``
shell-out. One backend session adapts a ground-truth submission to a built
bundle's interface (and its Docker image's libraries), runs it through the
bundle's scoring pipeline via ``autocodabench_run_user_submission``, and emits
the skill's documented JSON. The model is structurally blind to any expected
score — the orchestrator audits the produced score afterwards
(:mod:`autocodabench.bench.audit`).

Bundle resolution is by slug against the *active run dir's* ``bundles/``
(:func:`autocodabench.core.config.resolve_bundle_dir`), so this phase runs with
``AUTOCODABENCH_RUN_DIR`` pointed at the **build** run dir (where the bundle and
its run-logs live). The adapted-submission artifacts (``attempt_<K>/``,
``final.json``) go to a separate ``out_dir`` the caller owns.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..backends.base import AgentBackend, AgentRunResult, AgentTask
from . import prompts
from .pipeline import _mcp_servers

# Same authoring surface the build phase has, plus Bash (Claude-only, for
# probing the image) and Write (to author the adapted submission). On the
# generic backend, Bash is simply unavailable; Write/run_user_submission map
# through local_tools.
REFORMAT_TOOLS = ["mcp__autocodabench__*", "Read", "Write", "Glob", "Grep", "Bash"]


@dataclass
class ReformatResult:
    ok: bool
    final: dict[str, Any] | None       # the skill's final.json shape
    out_dir: Path
    run: AgentRunResult | None = None
    error: str | None = None

    @property
    def scores(self) -> dict | None:
        return (self.final or {}).get("scores")


async def reformat_and_run_async(
    *,
    bundle_dir: str | Path,
    build_run_dir: str | Path,
    submission_dir: str | Path,
    out_dir: str | Path,
    backend: AgentBackend,
    slug: str | None = None,
    label: str = "sub",
    model: str | None = None,
    max_budget_usd: float | None = None,
    on_text: Callable[[str], None] | None = None,
    on_event: Callable[[dict], None] | None = None,
) -> ReformatResult:
    """Adapt + score one submission against a built bundle. One backend session."""
    bundle_dir = Path(bundle_dir).resolve()
    build_run_dir = Path(build_run_dir).resolve()
    submission_dir = Path(submission_dir).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = slug or bundle_dir.name

    # Active run dir = the build dir, so `slug` resolves to its bundle and the
    # runner's logs land alongside the bundle's other run logs.
    import os
    env = {**os.environ, "AUTOCODABENCH_RUN_DIR": str(build_run_dir)}
    mcp_servers = _mcp_servers(build_run_dir)

    prompt = (
        "Reformat-and-run in NON-INTERACTIVE mode.\n\n"
        f"bundle_dir:     {bundle_dir}\n"
        f"bundle_slug:    {slug}   (pass as `slug` to autocodabench_run_user_submission)\n"
        f"submission_dir: {submission_dir}\n"
        f"out_dir:        {out_dir}\n"
        f"label:          {label}\n\n"
        "Adapt the submission into out_dir/attempt_<K>/, run it via\n"
        f"  autocodabench_run_user_submission(slug=\"{slug}\", "
        "submission_dir=\"<out_dir>/attempt_<K>/\", label=\"<label>.attempt_<K>\")\n"
        "iterate up to the attempt cap on runtime errors, write out_dir/final.json, "
        "and emit the single final JSON object as your last message."
    )

    run = await backend.run(AgentTask(
        prompt=prompt,
        system_prompt=prompts.reformat_system_prompt(),
        allowed_tools=REFORMAT_TOOLS,
        mcp_servers=mcp_servers,
        env=env,
        model=model,
        max_budget_usd=max_budget_usd,
        trace_path=out_dir / "agent_trace.jsonl",
        on_text=on_text,
        on_event=on_event,
    ))

    # Prefer the on-disk final.json the skill writes; fall back to the last
    # JSON object in the session's final text.
    final = _read_final(out_dir / "final.json") or _extract_last_json(run.final_text)
    ok = bool(run.ok and final is not None)
    error = None if ok else (run.error or "reformat-and-run produced no final.json")
    return ReformatResult(ok=ok, final=final, out_dir=out_dir, run=run, error=error)


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------

def _read_final(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _json_objects(text: str) -> list[str]:
    """Return every top-level ``{...}`` span (string-aware bracket matching)."""
    objs: list[str] = []
    depth = 0
    start: int | None = None
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                objs.append(text[start:i + 1])
                start = None
    return objs


def _extract_last_json(text: str | None) -> dict | None:
    """The last parseable JSON object in ``text`` (the skill's final message)."""
    if not text:
        return None
    # Prefer fenced ```json blocks if present, else any top-level object.
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    for cand in reversed(fenced):
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    for cand in reversed(_json_objects(text)):
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    return None
