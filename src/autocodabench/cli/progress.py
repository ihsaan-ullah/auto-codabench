"""Live progress UI for the agentic CLI commands.

The Claude Agent SDK streams one structured event per step (assistant text,
tool calls, tool results). Left raw, that is either a wall of noise or — in the
default view — near silence, so a long phase looks *frozen*. This module turns
the stream into the kind of feedback an interactive coding agent gives:

- a **live status line** that keeps moving while the model works —
  ``Composing…``, a white blob sweeping a dim track, and the elapsed seconds —
  so the terminal never looks hung (animated only on a TTY; redirected output
  falls back to plain, scrollable lines);
- a **friendly per-step narrative** above it — the agent's own narration, each
  tool call rendered as a short action (``⏺ Write scoring program  +84 lines``),
  and the milestones the agent addresses to the user.

`ProgressUI` is a context manager: enter to start the animation, exit to stop it
and restore the cursor (even on Ctrl-C). Its :meth:`on_event` is the
``on_event`` callback the backend already emits into.
"""
from __future__ import annotations

import shutil
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Any

# --- ANSI ------------------------------------------------------------------
_ORANGE = "\033[38;5;208m"
_WHITE = "\033[97m"
_GREY = "\033[37m"
_DIM = "\033[90m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_BOLD = "\033[1m"
_RESET = "\033[0m"
_HIDE_CURSOR = "\033[?25l"
_SHOW_CURSOR = "\033[?25h"
_CLEAR_LINE = "\r\033[K"

# The status verb. Kept fixed — the sweeping blob carries the motion, so the
# word stays put rather than flickering between synonyms.
_VERB = "Composing"

# Event kinds an agent uses to address the end user directly (via
# `autocodabench_log_event(kind=..., message=...)`). "deviation" reports a
# departure from the locked plan and is highlighted.
_USER_MESSAGE_KINDS = {"progress", "milestone", "status", "deviation"}


# --- small pure helpers ----------------------------------------------------

def _short_tool_name(name: str) -> str:
    """`mcp__autocodabench__autocodabench_write_scoring_program` → `write_scoring_program`."""
    return (name or "").split("__")[-1].replace("autocodabench_", "")


def _basename(x: Any) -> str:
    return Path(x).name if isinstance(x, str) and x else ""


def _count_lines(x: Any) -> int | None:
    return len(x.splitlines()) if isinstance(x, str) and x else None


def _plus(n: int | None) -> str | None:
    return f"+{n} lines" if n else None


def _files_detail(files: Any) -> str | None:
    if not isinstance(files, dict) or not files:
        return None
    total = sum(_count_lines(v) or 0 for v in files.values())
    n = len(files)
    unit = "file" if n == 1 else "files"
    return f"{n} {unit}, +{total} lines" if total else f"{n} {unit}"


def _edit_detail(inp: dict) -> str | None:
    new = _count_lines(inp.get("new_string")) or 0
    old = _count_lines(inp.get("old_string")) or 0
    parts = ([f"+{new}"] if new else []) + ([f"-{old}"] if old else [])
    return " ".join(parts) + " lines" if parts else None


def _one_line(text: Any, width: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= width else s[: width - 1] + "…"


def _tool_arg_summary(inp: dict) -> str:
    """A short, identifying summary of a tool call's arguments for one line."""
    if not isinstance(inp, dict) or not inp:
        return ""
    for key in ("name", "slug", "page", "filename", "path", "file_path",
                "pattern", "spec_name", "kind"):
        val = inp.get(key)
        if isinstance(val, str) and val:
            return f"({val})"
    for val in inp.values():  # fall back to the first short scalar
        if isinstance(val, str) and val:
            return f"({val if len(val) <= 48 else val[:47] + '…'})"
    return ""


def _is_parallel_cancellation(text: str) -> bool:
    """A tool result that is a sibling-cancellation, not a genuine failure:
    when one call in a parallel batch errors, the runtime cancels the others."""
    low = (text or "").lower()
    return "cancelled" in low and "parallel tool call" in low


def _friendly_action(name: str, inp: dict) -> tuple[str | None, str | None]:
    """Map a tool call to a human action + an optional change detail.

    Returns ``(action, detail)`` — e.g. ``("Write scoring program", "+84 lines")``.
    ``action`` is ``None`` for housekeeping tools that deserve no own line (they
    only nudge the live status).
    """
    inp = inp or {}
    table = {
        "init_bundle": (f"Init bundle {inp.get('slug', '')}".strip(), None),
        "write_competition_yaml": ("Write competition.yaml", None),
        "write_page": (f"Write page {_basename(inp.get('filename'))}".strip(),
                       _plus(_count_lines(inp.get("body")))),
        "write_scoring_program": ("Write scoring program",
                                  _plus(_count_lines(inp.get("script")))),
        "write_ingestion_program": ("Write ingestion program",
                                    _plus(_count_lines(inp.get("script")))),
        "write_solution": ("Write baseline solution",
                           _files_detail(inp.get("files"))),
        "attach_data": ("Attach data", None),
        "zip_bundle": ("Zip bundle", None),
        "snapshot_spec": (f"Save {_basename(inp.get('filename'))}".strip(),
                          _plus(_count_lines(inp.get("body")))),
        "validate_bundle": ("Validate bundle", None),
        "prepare_run_env": ("Prepare run environment", None),
        "install_env_extras": ("Install extras", None),
        "run_baseline_submission": ("Run baseline submission", None),
        "run_user_submission": ("Run submission", None),
        "run_starting_kit": ("Run starting-kit notebook", None),
        "upload_bundle": ("Upload bundle", None),
        # housekeeping — status only, no dedicated line
        "open_run": (None, None),
        "current_run": (None, None),
    }
    if name in table:
        return table[name]
    # Generic Claude Code tools the agent may also reach for.
    if name == "Read":
        return f"Read {_basename(inp.get('file_path'))}".strip(), None
    if name == "Write":
        return (f"Write {_basename(inp.get('file_path'))}".strip(),
                _plus(_count_lines(inp.get("content"))))
    if name == "Edit":
        return f"Edit {_basename(inp.get('file_path'))}".strip(), _edit_detail(inp)
    if name == "Grep":
        return f"Search {inp.get('pattern', '')!r}", None
    if name == "Glob":
        return f"Find {inp.get('pattern', '')}", None
    if name == "Bash":
        return f"Run  {_one_line(inp.get('command', ''), 56)}", None
    if name in ("TodoWrite",):
        return None, None
    # Unknown tool: humanize the name + a short arg hint.
    return name.replace("_", " ").capitalize() + _tool_arg_summary(inp), None


# --- the live UI -----------------------------------------------------------

class ProgressUI:
    """Render pipeline events as a live narrative + animated status line.

    Construct with ``debug=True`` for the full developer trace (raw tool errors,
    every tool call, the agent's narration verbatim). Use as a context manager
    around the run to drive the animation; call :meth:`on_event` from the
    backend's ``on_event`` hook.
    """

    def __init__(self, *, debug: bool = False, interval: float = 0.09):
        self.debug = debug
        self.interval = interval
        self.animate = False          # set in __enter__ iff stdout is a TTY
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = "Warming up…"
        self._t0 = time.monotonic()
        self._frame = 0
        self._spinner_visible = False

    # -- lifecycle ----------------------------------------------------------
    def __enter__(self) -> "ProgressUI":
        self.animate = sys.stdout.isatty()
        if self.animate:
            self._t0 = time.monotonic()
            sys.stdout.write(_HIDE_CURSOR)
            sys.stdout.flush()
            self._thread = threading.Thread(target=self._animate_loop, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self.animate:
            with self._lock:
                sys.stdout.write(_CLEAR_LINE + _SHOW_CURSOR)
                sys.stdout.flush()
        return False

    # -- output primitives --------------------------------------------------
    def _c(self, s: str, code: str) -> str:
        """Colorize only when animating (a TTY); keep redirected logs clean."""
        return f"{code}{s}{_RESET}" if self.animate else s

    def line(self, text: str = "") -> None:
        """Print a persistent line above the live status."""
        with self._lock:
            if self.animate and self._spinner_visible:
                sys.stdout.write(_CLEAR_LINE)
                self._spinner_visible = False
            sys.stdout.write(text + "\n")
            sys.stdout.flush()

    def set_status(self, text: str) -> None:
        with self._lock:
            self._status = _one_line(text, 80) or self._status

    # -- the animation ------------------------------------------------------
    def _animate_loop(self) -> None:
        while not self._stop.wait(self.interval):
            with self._lock:
                self._paint()

    def _blob(self) -> str:
        """A white blob sweeping (knight-rider bounce) across a dim track."""
        w = 14
        period = 2 * (w - 1)
        pos = self._frame % period
        if pos >= w:
            pos = period - pos
        cells = []
        for i in range(w):
            d = abs(i - pos)
            if d == 0:
                cells.append(f"{_WHITE}●{_RESET}")
            elif d == 1:
                cells.append(f"{_GREY}•{_RESET}")
            else:
                cells.append(f"{_DIM}·{_RESET}")
        return "".join(cells)

    def _paint(self) -> None:
        now = time.monotonic()
        self._frame += 1
        elapsed = int(now - self._t0)
        width = shutil.get_terminal_size((80, 20)).columns
        status = _one_line(self._status, max(8, width - 44))
        line = (f"{_CLEAR_LINE}{_ORANGE}{_VERB}…{_RESET} {self._blob()} "
                f"{_DIM}({elapsed}s · {status}){_RESET}")
        sys.stdout.write(line)
        sys.stdout.flush()
        self._spinner_visible = True

    # -- event handling -----------------------------------------------------
    def on_event(self, ev: dict) -> None:
        kind = ev.get("kind")
        if kind == "phase":
            self._on_phase(ev)
        elif kind == "phase_done":
            self._on_phase_done(ev)
        elif kind == "tool_use":
            self._on_tool_use(ev)
        elif kind == "tool_result":
            self._on_tool_result(ev)
        elif kind == "text":
            self._on_text(ev)

    def _on_phase(self, ev: dict) -> None:
        self._t0 = time.monotonic()  # elapsed is per-phase
        bar = self._c("─" * 60, _DIM)
        title = ev.get("title") or ev.get("phase") or "working"
        self.line()
        self.line(bar)
        self.line(self._c(f" Phase {ev.get('index')}/{ev.get('total')} · {title}", _BOLD))
        if self.debug and ev.get("detail"):
            self.line(self._c(f" {ev['detail']}", _DIM))
        self.line(bar)
        self.set_status(title)

    def _on_phase_done(self, ev: dict) -> None:
        ok = ev.get("ok")
        mark = self._c("✓", _GREEN) if ok else self._c("✗", _RED)
        turns = ev.get("num_turns")
        tail = f" · {turns} turns" if (self.debug and turns) else ""
        self.line(f"  {mark} {ev.get('phase')} phase complete{tail}")

    def _on_tool_use(self, ev: dict) -> None:
        name = _short_tool_name(ev.get("name", "?"))
        inp = ev.get("input") or {}
        if name == "log_event":
            message = inp.get("message")
            ekind = (inp.get("kind") or "").lower()
            if message and ekind in _USER_MESSAGE_KINDS:
                if ekind == "deviation":
                    self.line(f"  {self._c('⚠', _YELLOW)} {message}")
                else:
                    self.line(f"  {self._c('•', _ORANGE)} {message}")
                self.set_status(message)
            elif self.debug:
                self.line(self._c(f"  ⏺ log_event({ekind})", _DIM))
            return
        action, detail = _friendly_action(name, inp)
        if action is None:  # housekeeping — nudge the status only
            if self.debug:
                self.line(self._c(f"  ⏺ {name}{_tool_arg_summary(inp)}", _DIM))
            return
        suffix = self._c(f"  {detail}", _DIM) if detail else ""
        if self.debug:  # keep the raw tool name greppable in the developer trace
            suffix += self._c(f"  ({name})", _DIM)
        self.line(f"  {self._c('⏺', _ORANGE)} {action}{suffix}")
        self.set_status(action)

    def _on_tool_result(self, ev: dict) -> None:
        if not ev.get("is_error"):
            if self.debug and ev.get("preview"):
                self.line(self._c(f"      ⎿ {_one_line(ev['preview'], 120)}", _DIM))
            return
        preview = ev.get("preview") or "tool error"
        if _is_parallel_cancellation(preview):
            if self.debug:
                self.line(self._c("      ↻ retried (a parallel sibling call was "
                                  "cancelled — not a failure)", _DIM))
        elif self.debug:
            self.line(self._c(f"      ↳ ⚠ {_one_line(preview, 200)}", _RED))

    def _on_text(self, ev: dict) -> None:
        text = (ev.get("text") or "").strip()
        if not text:
            return
        self.set_status(_one_line(text, 80))
        # The agent's running narration — shown in both views (it is the
        # user-friendly story of what is happening); debug adds a gutter rule.
        body = text if len(text) <= 1200 else text[:1200].rstrip() + " …"
        prefix = self._c("  │ ", _DIM) if self.debug else "  "
        for para in body.split("\n"):
            for chunk in (textwrap.wrap(para, width=84) or [""]):
                self.line(f"{prefix}{chunk}")
