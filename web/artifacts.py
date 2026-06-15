"""Artifact writing for the AutoCodabench web UI.

Handles everything that gets written to disk per session:
  - Public HTML files + manifest.json served to the right-side workspace panel
  - Per-session transcript.md
  - Per-turn cost.jsonl
"""
from __future__ import annotations

import json
import logging
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from config import (
    PHASE_ARTIFACT,
    PHASE_BUNDLE,
    PHASE_ORDER,
    PHASE_PLAN,
    PHASE_TITLE,
    PHASE_VALIDATE,
    PUBLIC_SESSIONS,
)

log = logging.getLogger("autocodabench.web.artifacts")

# ---------------------------------------------------------------------------
# Shared CSS for markdown-rendered HTML pages in the workspace panel
# ---------------------------------------------------------------------------

_MD_DOC_CSS = (
    "<style>body{font:14px/1.55 -apple-system,BlinkMacSystemFont,"
    "'Segoe UI',Roboto,Helvetica,sans-serif;padding:24px 32px;"
    "color:#1f2328;max-width:80ch;margin:0 auto;background:#ffffff}"
    "h1,h2,h3,h4{margin-top:1.6em;color:#1f2328}"
    "h1{font-size:22px;border-bottom:1px solid #d0d7de;padding-bottom:6px}"
    "h2{font-size:18px}h3{font-size:15px}"
    "pre{background:#f6f8fa;padding:12px;border-radius:6px;overflow:auto}"
    "code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
    "font-size:12.5px}"
    "p code,li code{background:#eff1f4;padding:1px 4px;border-radius:3px}"
    "table{border-collapse:collapse;margin:14px 0}"
    "table td,table th{border:1px solid #d0d7de;padding:6px 10px}"
    "a{color:#0969da}"
    "</style>"
)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def public_session_dir(session_id: str) -> Path:
    p = PUBLIC_SESSIONS / session_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def render_md_to_html(md_text: str, title: str) -> str:
    """Convert a markdown string to a self-contained HTML page."""
    try:
        import markdown as _md_lib  # type: ignore
        body = _md_lib.markdown(md_text, extensions=["fenced_code", "tables"])
    except Exception:
        body = (
            "<pre style='white-space:pre-wrap'>"
            + md_text.replace("<", "&lt;").replace(">", "&gt;")
            + "</pre>"
        )
    return (
        "<!doctype html><meta charset='utf-8'>"
        + _MD_DOC_CSS
        + f"<title>{title}</title>{body}"
    )


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------

class Transcript:
    """Appends human-readable turns to <run_dir>/transcript.md."""

    @staticmethod
    def append(run_dir: Path, *, role: str, text: str) -> None:
        """Append one role-tagged turn.

        Tool calls are embedded inline as <details> collapsibles rather than
        separate turns, keeping the transcript readable as a single linear
        document (renders cleanly on GitHub, VS Code, Obsidian).

        First-write note: we emit a title on first write and only use `---`
        as a between-entries separator from the second entry onward, because
        a leading `---` is parsed as YAML frontmatter by most renderers and
        hides the first user prompt.
        """
        role_header = {
            "user":   "## 👤 user — ",
            "claude": "## 🤖 autocodabench — ",
        }.get(role, f"## {role} — ")

        path = run_dir / "transcript.md"
        is_first_write = (not path.exists()) or path.stat().st_size == 0

        if is_first_write:
            header = (
                f"# Transcript — {run_dir.name}\n\n"
                f"_Per-session conversation, written turn-by-turn. Tool calls "
                f"are embedded inside each assistant block as `<details>` "
                f"collapsibles. Cost, events, and raw tool snapshots are "
                f"in sibling files (`cost.jsonl`, `events.jsonl`, `tool_calls/`)._\n\n"
            )
            line = f"{header}{role_header}{utc_now()}\n\n{text}\n"
        else:
            line = f"\n---\n\n{role_header}{utc_now()}\n\n{text}\n"

        path.open("a", encoding="utf-8").write(line)

    @staticmethod
    def format_tool_call(*, op: str, raw_name: str, input_json: dict,
                         output_text: str, is_error: bool = False) -> str:
        """Render one tool call as a collapsed <details> block.

        The summary line is the friendly op label. Expanding reveals the raw
        MCP tool name, input JSON, and truncated output. Output is capped at
        2000 chars so a noisy search result does not dominate the transcript;
        the full output is still on disk under tool_calls/.
        """
        icon = "❌" if is_error else "🔧"
        output_text = (output_text or "").strip()
        if len(output_text) > 2000:
            output_text = output_text[:2000] + "\n…[truncated; full output in tool_calls/]"
        try:
            input_str = json.dumps(input_json, indent=2, ensure_ascii=False)
        except Exception:
            input_str = str(input_json)
        return (
            f"\n<details><summary>{icon} {op}</summary>\n\n"
            f"`{raw_name}`\n\n"
            f"**Input:**\n```json\n{input_str}\n```\n\n"
            f"**Output:**\n```\n{output_text}\n```\n\n"
            f"</details>\n"
        )


# ---------------------------------------------------------------------------
# Cost log
# ---------------------------------------------------------------------------

class CostLog:
    """Appends one JSON line to <run_dir>/cost.jsonl per assistant turn."""

    @staticmethod
    def append(run_dir: Path, *, turn_cost: float, cumulative: float,
               model: str, session_id: str, user_id: str) -> None:
        line = json.dumps({
            "at":         utc_now(),
            "turn_cost":  round(turn_cost, 6),
            "cumulative": round(cumulative, 6),
            "model":      model,
            "session":    session_id,
            "user":       user_id,
        })
        (run_dir / "cost.jsonl").open("a", encoding="utf-8").write(line + "\n")


# ---------------------------------------------------------------------------
# Public workspace panel artifacts
# ---------------------------------------------------------------------------

class PublicArtifacts:
    """Writes rendered HTML + manifest.json into web/public/sessions/<sid>/.

    The right-side workspace panel in chat.js fetches these files via plain
    HTTP at /public/sessions/<sid>/... after every assistant turn. No Chainlit
    element machinery is involved — this is pure static file serving.

    Files written each turn:
      plan.html       — markdown render of specs/implementation_plan.md
      transcript.html — markdown render of transcript.md
      cost.html       — monospace dump of cost.jsonl
      specs/*.html    — markdown render of each file in specs/
      bundle.zip      — copy of the session's built bundle (Phase 2+)
      workspace.zip   — all of the above bundled for one-click download
      manifest.json   — file list with URLs, tags, and ready flags for chat.js
    """

    @staticmethod
    def find_bundle_zip(run_dir: Path) -> Path | None:
        """Locate the zip this session's Phase 2 produced.

        Resolution order:
          1. <run>/bundles/*/*.zip  — canonical per-session location
          2. global bundles root filtered by mtime >= session start — defensive
             fallback for the case where the MCP subprocess lost AUTOCODABENCH_RUN_DIR.
        Always returns the most-recently-modified candidate (handles revert +
        re-advance, where the user may have multiple bundle versions).
        """
        from autocodabench.core.config import bundles_root as _acb_bundles_root

        session_bundles = run_dir / "bundles"
        if session_bundles.is_dir():
            candidates = list(session_bundles.glob("*/*.zip"))
            if candidates:
                return max(candidates, key=lambda p: p.stat().st_mtime)

        meta = run_dir / "meta.json"
        if not meta.is_file():
            return None
        session_start = meta.stat().st_mtime
        global_root = _acb_bundles_root()
        if not global_root.is_dir():
            return None
        fresh = [p for p in global_root.glob("*/*.zip")
                 if p.stat().st_mtime >= session_start]
        if not fresh:
            return None
        found = max(fresh, key=lambda p: p.stat().st_mtime)
        log.warning("bundle found in GLOBAL fallback (env var lost?): "
                    "session_dir=%s, found=%s", run_dir, found)
        return found

    @staticmethod
    def write(run_dir: Path, session_id: str) -> None:
        """Render and write all workspace panel files for this session."""
        try:
            out = public_session_dir(session_id)

            # --- plan ---
            plan_paths = [
                run_dir / "specs" / "implementation_plan.md",
                run_dir / "implementation_plan.md",
            ]
            plan_path = next((p for p in plan_paths if p.is_file()), None)
            plan_ready = plan_path is not None and plan_path.stat().st_size > 0

            if plan_ready:
                plan_text = plan_path.read_text(encoding="utf-8", errors="replace")
                (out / "plan.html").write_text(
                    render_md_to_html(plan_text, "implementation_plan.md"),
                    encoding="utf-8",
                )
                # Raw markdown copy so the plan is directly downloadable.
                (out / "implementation_plan.md").write_text(plan_text, encoding="utf-8")
            else:
                (out / "implementation_plan.md").unlink(missing_ok=True)
                (out / "plan.html").write_text(
                    "<!doctype html><html><head><meta charset='utf-8'>"
                    "<style>body{font:14px/1.5 -apple-system,sans-serif;"
                    "padding:24px;color:#555}em{color:#888}</style>"
                    "</head><body><h2>📝 implementation_plan.md</h2>"
                    "<p><em>The plan will appear here as Phase 1 saves it. "
                    "Once you're happy with the plan, click "
                    "<b>▶ Advance to Phase 2</b> in the phase pills at the top "
                    "to package the Codabench bundle.</em></p></body></html>",
                    encoding="utf-8",
                )

            # --- transcript ---
            transcript = run_dir / "transcript.md"
            if transcript.is_file() and transcript.stat().st_size > 0:
                try:
                    import markdown as _md_lib  # type: ignore
                    rendered = _md_lib.markdown(
                        transcript.read_text(encoding="utf-8", errors="replace"),
                        extensions=["fenced_code", "tables"],
                    )
                except Exception:
                    rendered = (
                        "<pre style='white-space:pre-wrap'>"
                        + transcript.read_text(encoding="utf-8", errors="replace")
                        + "</pre>"
                    )
                (out / "transcript.html").write_text(
                    "<!doctype html><meta charset='utf-8'>"
                    "<style>body{font:14px/1.5 -apple-system,sans-serif;"
                    "padding:18px;color:#222;max-width:80ch;margin:0 auto}"
                    "pre{background:#f6f8fa;padding:12px;border-radius:6px;"
                    "overflow:auto}code{font-family:ui-monospace,Menlo,Consolas;"
                    "font-size:12.5px}h1,h2,h3{margin-top:1.5em}</style>"
                    "<title>transcript.md</title>" + rendered,
                    encoding="utf-8",
                )

            # --- cost.jsonl ---
            cost = run_dir / "cost.jsonl"
            if cost.is_file() and cost.stat().st_size > 0:
                (out / "cost.html").write_text(
                    "<!doctype html><meta charset='utf-8'>"
                    "<style>body{font:13px/1.4 ui-monospace,Menlo;"
                    "padding:18px;background:#0d1117;color:#c9d1d9}</style>"
                    "<title>cost.jsonl</title><pre>"
                    + cost.read_text(encoding="utf-8", errors="replace")
                    + "</pre>",
                    encoding="utf-8",
                )

            # --- specs/*.md ---
            specs_in  = run_dir / "specs"
            specs_out = out / "specs"
            specs_out.mkdir(exist_ok=True)
            for spec_md in (specs_in.glob("*.md") if specs_in.is_dir() else []):
                try:
                    import markdown as _md_lib  # type: ignore
                    rendered = _md_lib.markdown(
                        spec_md.read_text(encoding="utf-8", errors="replace"),
                        extensions=["fenced_code", "tables"],
                    )
                except Exception:
                    rendered = (
                        "<pre style='white-space:pre-wrap'>"
                        + spec_md.read_text(encoding="utf-8", errors="replace")
                        + "</pre>"
                    )
                (specs_out / (spec_md.stem + ".html")).write_text(
                    "<!doctype html><meta charset='utf-8'>"
                    "<style>body{font:14px/1.5 -apple-system,sans-serif;"
                    "padding:18px;color:#222;max-width:80ch;margin:0 auto}"
                    "pre{background:#f6f8fa;padding:12px;border-radius:6px;"
                    "overflow:auto}code{font-family:ui-monospace,Menlo,Consolas;"
                    "font-size:12.5px}h1,h2,h3{margin-top:1.5em}</style>"
                    f"<title>{spec_md.name}</title>" + rendered,
                    encoding="utf-8",
                )

            # --- validation_report.md (Phase 3 output) ---
            report = run_dir / "validation_report.md"
            report_ready = report.is_file() and report.stat().st_size > 0
            if report_ready:
                report_text = report.read_text(encoding="utf-8", errors="replace")
                (out / "validation_report.html").write_text(
                    render_md_to_html(report_text, "validation_report.md"),
                    encoding="utf-8",
                )
                (out / "validation_report.md").write_text(report_text, encoding="utf-8")
            else:
                (out / "validation_report.html").unlink(missing_ok=True)
                (out / "validation_report.md").unlink(missing_ok=True)

            # --- bundle.zip ---
            bundle_src = PublicArtifacts.find_bundle_zip(run_dir)
            bundle_pub = out / "bundle.zip"
            if bundle_src is not None:
                try:
                    shutil.copyfile(bundle_src, bundle_pub)
                except Exception as e:
                    log.warning("bundle copy failed: %s", e)

            # --- workspace.zip (all artifacts as one download) ---
            workspace_zip = out / "workspace.zip"
            try:
                tmp_zip = out / ".workspace.zip.tmp"
                with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                    for p in out.rglob("*"):
                        if not p.is_file():
                            continue
                        if p.name in ("workspace.zip", ".workspace.zip.tmp", "manifest.json"):
                            continue
                        zf.write(p, p.relative_to(out))
                tmp_zip.replace(workspace_zip)
            except Exception as e:
                log.warning("workspace.zip build failed: %s", e)

            # --- manifest.json ---
            def _tag(p: Path) -> str:
                try:
                    st = p.stat()
                    return f"{st.st_size}-{int(st.st_mtime)}"
                except Exception:
                    return "0-0"

            tabs = [
                {
                    "name":  "📝 implementation_plan.md",
                    "url":   f"/public/sessions/{session_id}/plan.html",
                    "kind":  "plan",
                    "ready": plan_ready,
                    "tag":   _tag(out / "plan.html"),
                },
            ]
            if (out / "transcript.html").is_file():
                tabs.append({
                    "name":  "📄 transcript.md",
                    "url":   f"/public/sessions/{session_id}/transcript.html",
                    "kind":  "transcript",
                    "ready": True,
                    "tag":   _tag(out / "transcript.html"),
                })
            if (out / "cost.html").is_file():
                tabs.append({
                    "name":  "💰 cost.jsonl",
                    "url":   f"/public/sessions/{session_id}/cost.html",
                    "kind":  "cost",
                    "ready": True,
                    "tag":   _tag(out / "cost.html"),
                })
            for spec_html in sorted(specs_out.glob("*.html")):
                if spec_html.stem == "implementation_plan":
                    continue
                tabs.append({
                    "name":  f"📄 specs/{spec_html.stem}.md",
                    "url":   f"/public/sessions/{session_id}/specs/{spec_html.name}",
                    "kind":  "spec",
                    "ready": True,
                    "tag":   _tag(spec_html),
                })

            if (out / "validation_report.html").is_file():
                tabs.append({
                    "name":  "✅ validation_report.md",
                    "url":   f"/public/sessions/{session_id}/validation_report.html",
                    "kind":  "validation",
                    "ready": True,
                    "tag":   _tag(out / "validation_report.html"),
                })

            bundle_ready = bundle_pub.is_file()
            ws_ready     = workspace_zip.is_file()
            plan_dl      = out / "implementation_plan.md"
            report_dl    = out / "validation_report.md"
            plan_dl_ready   = plan_dl.is_file()
            report_dl_ready = report_dl.is_file()
            downloads: list[dict] = [
                {
                    "name":     "📝 implementation_plan.md",
                    "filename": "implementation_plan.md",
                    "url":      f"/public/sessions/{session_id}/implementation_plan.md",
                    "kind":     "plan",
                    "ready":    plan_dl_ready,
                    "size":     plan_dl.stat().st_size if plan_dl_ready else 0,
                    "tag":      _tag(plan_dl) if plan_dl_ready else "missing",
                },
                {
                    "name":     "📦 competition bundle (.zip)",
                    "filename": "bundle.zip",
                    "url":      f"/public/sessions/{session_id}/bundle.zip",
                    "kind":     "bundle",
                    "ready":    bundle_ready,
                    "size":     bundle_pub.stat().st_size if bundle_ready else 0,
                    "tag":      _tag(bundle_pub) if bundle_ready else "missing",
                },
                {
                    "name":     "✅ validation_report.md",
                    "filename": "validation_report.md",
                    "url":      f"/public/sessions/{session_id}/validation_report.md",
                    "kind":     "validation",
                    "ready":    report_dl_ready,
                    "size":     report_dl.stat().st_size if report_dl_ready else 0,
                    "tag":      _tag(report_dl) if report_dl_ready else "missing",
                },
                {
                    "name":     "📦 workspace.zip (all artifacts)",
                    "filename": "workspace.zip",
                    "url":      f"/public/sessions/{session_id}/workspace.zip",
                    "kind":     "workspace",
                    "ready":    ws_ready,
                    "size":     workspace_zip.stat().st_size if ws_ready else 0,
                    "tag":      _tag(workspace_zip) if ws_ready else "missing",
                },
            ]

            manifest = {
                "session_id": session_id,
                "updated_at": utc_now(),
                "tabs":       tabs,
                "downloads":  downloads,
                "files":      tabs,  # legacy key kept for older cached chat.js
            }
            (out / "manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
        except Exception as e:
            log.warning("public artifacts write failed: %s", e)


# ---------------------------------------------------------------------------
# Phase state JSON (drives the top phase bar in chat.js)
# ---------------------------------------------------------------------------

class PhaseState:
    """Writes web/public/sessions/<sid>/phase_state.json for chat.js.

    Polled by the phase bar every ~2 s. Cheap to compute: a few disk stats
    plus a small JSON write.
    """

    @staticmethod
    def artifact_exists(run_dir: Path, phase: str) -> bool:
        """Has this phase produced its locked artifact yet?

        Used by the phase bar to decide whether the Advance button is enabled
        and whether a completed phase should show a lock icon.

        PLAN     → specs/implementation_plan.md (legacy fallback: implementation_plan.md
                   directly under run_dir).
        BUNDLE   → any *.zip under <run>/bundles/.
        VALIDATE → validation_report.md under run_dir (written when Phase 3 runs).
        """
        if phase == PHASE_PLAN:
            return ((run_dir / "specs" / "implementation_plan.md").is_file()
                    or (run_dir / "implementation_plan.md").is_file())
        if phase == PHASE_BUNDLE:
            return PublicArtifacts.find_bundle_zip(run_dir) is not None
        if phase == PHASE_VALIDATE:
            return (run_dir / "validation_report.md").is_file()
        return False

    @staticmethod
    def prerequisite_met(run_dir: Path, phase: str) -> bool:
        """Is this phase's INPUT available, so the user may jump to it?

        A phase's input is the immediately preceding phase's output artifact:
          Plan     → no prerequisite (always reachable).
          Bundle   → needs the plan (implementation_plan.md).
          Validate → needs a bundle (built in Phase 2 or uploaded).

        This is what powers "jump to any reachable phase": the artifact can be
        produced by the prior phase OR seeded by the user via a chat upload.
        """
        pi = PHASE_ORDER.index(phase)
        if pi == 0:
            return True
        prev = PHASE_ORDER[pi - 1]
        return PhaseState.artifact_exists(run_dir, prev)

    @staticmethod
    def phase_status(phase: str, current: str) -> str:
        """Return one of: 'active', 'locked', or 'pending' (index-relative).

        active  — this is the current phase.
        locked  — a phase BEHIND the current one (click = revert / revise).
        pending — a phase AHEAD of the current one (click = advance/jump if its
                  prerequisite is met; see `prerequisite_met`).

        Status is purely positional; whether an ahead phase is *clickable* is
        decided from the separate `reachable` flag, so an uploaded artifact for
        a future phase doesn't mislabel it as a completed/behind phase.
        """
        if phase == current:
            return "active"
        pi = PHASE_ORDER.index(phase)
        ci = PHASE_ORDER.index(current)
        return "locked" if pi < ci else "pending"

    @staticmethod
    def write(run_dir: Path, session_id: str, *,
              current: str, history: list[str],
              last_input_tokens: int, last_output_tokens: int,
              cum_cost: float, max_usd: float,
              context_window: int) -> None:
        """Write phase_state.json for the given session."""
        try:
            out = public_session_dir(session_id)

            cur_idx     = PHASE_ORDER.index(current)
            phases_payload = []
            for ph in PHASE_ORDER:
                exists    = PhaseState.artifact_exists(run_dir, ph)
                pi        = PHASE_ORDER.index(ph)
                # A forward phase is "reachable" (jumpable) when its input
                # prerequisite is on disk; behind/current phases are always
                # navigable (revert / stay).
                reachable = (pi <= cur_idx) or PhaseState.prerequisite_met(run_dir, ph)
                phases_payload.append({
                    "id":        ph,
                    "title":     PHASE_TITLE[ph],
                    "artifact":  PHASE_ARTIFACT[ph],
                    "exists":    exists,
                    "reachable": reachable,
                    "status":    PhaseState.phase_status(ph, current),
                })

            next_phase  = PHASE_ORDER[cur_idx + 1] if cur_idx + 1 < len(PHASE_ORDER) else None
            # Back-compat single flag: can we step to the immediate next phase?
            can_advance = (next_phase is not None
                           and PhaseState.prerequisite_met(run_dir, next_phase))

            payload = {
                "session_id":  session_id,
                "updated_at":  utc_now(),
                "current":     current,
                "next":        next_phase,
                "can_advance": can_advance,
                "phases":      phases_payload,
                "context": {
                    "input_tokens":  last_input_tokens,
                    "output_tokens": last_output_tokens,
                    "max_tokens":    context_window,
                    "pct":           round(100.0 * last_input_tokens / context_window, 1),
                },
                "cost": {
                    "cumulative_usd": round(cum_cost, 4),
                    "budget_usd":     max_usd,
                    "pct":            round(100.0 * cum_cost / max_usd, 1) if max_usd > 0 else 0.0,
                },
            }
            (out / "phase_state.json").write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
        except Exception as e:
            log.warning("phase_state write failed: %s", e)
