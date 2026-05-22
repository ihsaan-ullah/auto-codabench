#!/usr/bin/env python3
"""Claude Code hook — mirror the live session transcript into the active run.

Invoked by `.claude/settings.json` hooks on UserPromptSubmit + Stop. Reads the
hook payload from stdin, locates `<repo>/auto_codabench/runs/LATEST/`, copies
the session's JSONL transcript into it, and regenerates a human-readable
`transcript.md`.

Failure is silent: if no active run exists, if the transcript_path is missing,
if JSON parsing fails, etc., we exit 0 without touching anything. We do NOT
want hooks to ever break Claude Code itself.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Locate the active run
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = REPO_ROOT / "auto_codabench" / "runs"
LATEST = RUNS_ROOT / "LATEST"


def _active_run() -> Path | None:
    if not LATEST.is_symlink() and not LATEST.exists():
        return None
    try:
        target = LATEST.resolve()
    except OSError:
        return None
    if not target.is_dir():
        return None
    if not (target / "meta.json").exists():
        return None
    return target


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Transcript rendering
# ---------------------------------------------------------------------------

def _extract_text(content) -> str:
    """Pull plain text out of a Claude Code transcript message's `content` field.

    `content` may be a list of blocks: text / tool_use / tool_result / thinking.
    We render text directly; flag the others in <details> blocks so the markdown
    stays readable.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    out: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            out.append(block.get("text", ""))
        elif btype == "thinking":
            t = block.get("thinking", "").strip()
            if t:
                out.append(f"<details><summary>(thinking)</summary>\n\n{t}\n\n</details>")
        elif btype == "tool_use":
            name = block.get("name", "?")
            tid = block.get("id", "")
            inputs = block.get("input", {})
            try:
                rendered = json.dumps(inputs, indent=2, ensure_ascii=False, default=str)
            except Exception:
                rendered = str(inputs)
            out.append(
                f"<details><summary>🔧 tool_use: <code>{name}</code></summary>\n\n"
                f"```json\n{rendered}\n```\n\n</details>"
            )
        elif btype == "tool_result":
            tid = block.get("tool_use_id", "")
            result_content = block.get("content", "")
            if isinstance(result_content, list):
                result_text = "\n".join(
                    b.get("text", "") for b in result_content if isinstance(b, dict)
                )
            else:
                result_text = str(result_content)
            is_err = block.get("is_error", False)
            tag = "🔴 tool_result (error)" if is_err else "🟢 tool_result"
            preview = (result_text or "").strip()
            if len(preview) > 4000:
                preview = preview[:4000] + "\n…(truncated)…"
            out.append(
                f"<details><summary>{tag}</summary>\n\n```\n{preview}\n```\n\n</details>"
            )
    return "\n\n".join(s for s in out if s)


_ROLE_HEADER = {
    "user": "## 👤 user — ",
    "assistant": "## 🤖 claude — ",
    "system": "## ⚙️ system — ",
}


def _run_started_at(run_dir: Path) -> str | None:
    """Read meta.json::started_at so we can drop pre-run history from the mirror.

    Claude Code sessions persist across many `/autocodabench-orchestrator`
    invocations within the same project — the JSONL contains *everything*
    since `claude` was launched. To make the transcript a shareable demo
    of one run, filter messages whose timestamp predates the run's open.
    """
    try:
        return json.loads((run_dir / "meta.json").read_text())["started_at"]
    except Exception:
        return None


def _ts_for_turn(turn: dict) -> str | None:
    """Best-effort timestamp string for a session-jsonl row."""
    return (
        turn.get("timestamp")
        or turn.get("ts")
        or (turn.get("message") or {}).get("timestamp")
    )


def _render_markdown(jsonl_path: Path, run_dir: Path) -> None:
    """Read session JSONL and write transcript.md / transcript.jsonl.

    The full session JSONL is mirrored verbatim as `transcript.jsonl` for
    auditing. `transcript.md` is filtered to only this run — turns whose
    timestamp is at or after meta.json::started_at — so the markdown file
    reads as a self-contained demo of *this* conversation.
    """
    raw_text = jsonl_path.read_text(encoding="utf-8", errors="replace")
    lines = raw_text.splitlines()
    turns = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            turns.append(json.loads(ln))
        except json.JSONDecodeError:
            continue

    # Always mirror the raw JSONL — ground truth, full session.
    (run_dir / "transcript.jsonl").write_text(raw_text, encoding="utf-8")

    started_at = _run_started_at(run_dir)
    total_count = sum(
        1 for t in turns if t.get("type") in ("user", "assistant")
    )

    md: list[str] = [
        f"# Transcript — {run_dir.name}",
        "",
        f"_Last refreshed: {_utc_now()}_",
        "",
        f"_Run started: {started_at or 'unknown'}_  "
        f"_·  Source: `{jsonl_path.name}` (filtered to this run)_",
        "",
        "Each turn is rendered below. Tool calls and results are folded into "
        "`<details>` blocks. The `transcript.jsonl` next to this file is the "
        "*full*, unfiltered Claude Code session log — use it for programmatic "
        "analysis. This markdown is the share-friendly per-run view.",
        "",
        "---",
        "",
    ]

    kept = 0
    for turn in turns:
        ttype = turn.get("type")
        if ttype not in ("user", "assistant"):
            continue
        ts = _ts_for_turn(turn) or ""
        # Drop pre-run history if we have a reliable run start time.
        if started_at and ts and ts < started_at:
            continue
        msg = turn.get("message") or {}
        role = msg.get("role") or ttype
        header = _ROLE_HEADER.get(role, f"## {role} — ")
        body = _extract_text(msg.get("content") or turn.get("content") or "")
        if not body.strip():
            continue
        md.append(header + ts)
        md.append("")
        md.append(body)
        md.append("")
        kept += 1

    md.append("")
    md.append("---")
    md.append("")
    md.append(
        f"_Rendered {kept} turn(s) for this run; full session JSONL has "
        f"{total_count} user/assistant turn(s) total._"
    )

    (run_dir / "transcript.md").write_text("\n".join(md), encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        payload = json.loads(raw)
    except Exception:
        return 0  # bad input — ignore

    run = _active_run()
    if run is None:
        return 0  # no active run — skip silently

    event = payload.get("hook_event_name") or "unknown"

    # Always append a small bookkeeping line to events.jsonl so we know hooks
    # actually fired (helps debug "I expected a transcript and got nothing").
    try:
        with (run / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _utc_now(),
                "kind": "hook_fired",
                "hook": event,
                "session_id": payload.get("session_id"),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # Copy the session transcript and regenerate transcript.md
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath")
    if transcript_path:
        try:
            p = Path(transcript_path).expanduser()
            if p.is_file():
                _render_markdown(p, run)
        except Exception:
            try:
                (run / "mcp_stderr" / "hook_errors.log").parent.mkdir(parents=True, exist_ok=True)
                with (run / "mcp_stderr" / "hook_errors.log").open("a", encoding="utf-8") as f:
                    f.write(f"{_utc_now()} {event} render failed:\n")
                    traceback.print_exc(file=f)
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
