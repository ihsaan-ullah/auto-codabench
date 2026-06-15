"""Session lifecycle management for the AutoCodabench web UI.

SessionManager owns everything that happens at chat start, per message, and
chat end. It sets up the isolated run dir, probes MCP imports, builds the
first SDK client, routes user messages, handles file attachments, and
triggers post-turn artifact writes and HF persistence.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import chainlit as cl
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from artifacts import PublicArtifacts, Transcript, utc_now
from config import (
    CONTEXT_WINDOW_TOKENS,
    DEFAULT_MODEL,
    MAX_USD_PER_SESSION,
    PHASE_BUNDLE,
    PHASE_PLAN,
    PHASE_TITLE,
    PHASE_VALIDATE,
    PYTHON_BIN,
    REPO_ROOT,
    TOOLS_BY_PHASE,
)
from hf_persist import persist_to_hf
from phase_manager import PhaseManager, _build_sdk_options
from streaming import run_agent_turn

log = logging.getLogger("autocodabench.web.session")

_ATTACHMENT_MAX_CHARS = 60_000
_PDF_MIME = "application/pdf"

# ---------------------------------------------------------------------------
# MCP server configuration
# ---------------------------------------------------------------------------

def build_mcp_servers(run_dir: Path) -> dict:
    """Return stdio MCP server configs scoped to this session's run dir."""
    env_for_mcp = {**os.environ, "AUTOCODABENCH_RUN_DIR": str(run_dir)}
    return {
        "autocodabench": {
            "type": "stdio",
            "command": PYTHON_BIN,
            "args": ["-m", "autocodabench.mcp.server"],
            "env": env_for_mcp,
        },
        "alex-mcp": {
            "type": "stdio",
            "command": PYTHON_BIN,
            "args": ["-m", "alex_mcp.server"],
            "env": env_for_mcp,
        },
    }


def probe_mcp_imports() -> list[str]:
    """Test that both MCP server modules import cleanly in a subprocess.

    Returns a list of human-readable error lines. An empty list means both
    servers are importable. Runs in a subprocess so an ImportError in one
    module can't crash the web process.
    """
    diag_snippet = (
        "import fastmcp, pathlib;"
        "p = pathlib.Path(fastmcp.__file__).parent;"
        "print('fastmcp', fastmcp.__version__);"
        "print('oauth_proxy as file:', (p / 'server/auth/oauth_proxy.py').is_file());"
        "print('oauth_proxy as pkg:', (p / 'server/auth/oauth_proxy/__init__.py').is_file())"
    )
    probes = {
        "autocodabench": "import autocodabench.mcp.server",
        "alex-mcp":      "import alex_mcp.server",
    }
    failures: list[str] = []
    for name, snippet in probes.items():
        try:
            result = subprocess.run(
                [PYTHON_BIN, "-c", snippet],
                capture_output=True, text=True, timeout=15,
            )
        except subprocess.TimeoutExpired:
            failures.append(f"`{name}`: import probe timed out after 15s")
            continue
        if result.returncode != 0:
            err  = (result.stderr or result.stdout or "").strip().splitlines()
            tail = "\n".join(err[-6:]) if err else "(no stderr)"
            failures.append(f"`{name}` failed to import:\n```\n{tail}\n```")

    if failures:
        try:
            diag = subprocess.run(
                [PYTHON_BIN, "-c", diag_snippet],
                capture_output=True, text=True, timeout=10,
            )
            info = (diag.stdout or diag.stderr or "(no output)").strip()
            failures.append(f"**runtime diagnostic:**\n```\n{info}\n```")
        except Exception as e:
            failures.append(f"**runtime diagnostic failed:** {e}")

    return failures


# ---------------------------------------------------------------------------
# Attachment extraction
# ---------------------------------------------------------------------------

def _extract_attachment_text(element) -> tuple[str, str] | None:
    """Return (label, body_text) for one attached file element, or None.

    Supported: PDF (via pypdf), .md, .txt. Other types are skipped silently.
    """
    path = getattr(element, "path", None)
    name = getattr(element, "name", None) or (Path(path).name if path else "<unknown>")
    mime = (getattr(element, "mime", "") or "").lower()
    if not path or not Path(path).exists():
        return None
    try:
        if mime == _PDF_MIME or name.lower().endswith(".pdf"):
            from pypdf import PdfReader
            reader  = PdfReader(path)
            pages   = []
            for i, page in enumerate(reader.pages):
                try:
                    pages.append(page.extract_text() or "")
                except Exception as e:
                    pages.append(f"[page {i + 1}: extraction failed: {e}]")
            body    = "\n\n".join(pages).strip()
            label   = f"{name} (PDF, {len(reader.pages)} pages)"
        elif mime in ("text/plain", "text/markdown") or name.lower().endswith((".md", ".txt")):
            body  = Path(path).read_text(encoding="utf-8", errors="replace")
            label = f"{name} ({len(body):,} chars)"
        else:
            return None
    except Exception as e:
        log.warning("attachment extraction for %s failed: %s", name, e)
        return None

    if not body.strip():
        return (label, "[empty after text extraction]")
    if len(body) > _ATTACHMENT_MAX_CHARS:
        body = body[:_ATTACHMENT_MAX_CHARS] + (
            f"\n\n[…truncated at {_ATTACHMENT_MAX_CHARS:,} chars]"
        )
    return (label, body)


# ---------------------------------------------------------------------------
# Phase-seeding from chat uploads
#
# A user can enter the pipeline at a later phase by dropping the upstream
# artifact into the chat instead of producing it agentically:
#   - implementation_plan.md  → seeds the Phase 1 output → jump to Phase 2.
#   - a bundle .zip (with competition.yaml) → seeds the Phase 2 output → jump
#     to Phase 3.
# Seeded artifacts land exactly where the built ones would, so the rest of the
# UI (phase gating, downloads, validate kickoff) needs no special-casing.
# ---------------------------------------------------------------------------

def _safe_slug(name: str) -> str:
    """Filesystem-safe bundle slug derived from an uploaded filename stem."""
    stem = Path(name).stem.strip().lower()
    cleaned = "".join(c if (c.isalnum() or c in "-_") else "-" for c in stem)
    cleaned = cleaned.strip("-_")
    return cleaned or "uploaded-bundle"


def _zip_is_bundle(zip_path: Path) -> bool:
    """True if the zip contains a competition.yaml (i.e. looks like a bundle)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            return any(n.rstrip("/").endswith("competition.yaml") for n in zf.namelist())
    except Exception as e:
        log.warning("zip inspect failed for %s: %s", zip_path, e)
        return False


def _seed_bundle_from_zip(run_dir: Path, zip_path: Path) -> str | None:
    """Extract an uploaded bundle zip into <run>/bundles/<slug>/.

    Normalises a single wrapping top-level directory so competition.yaml lands
    at the bundle root, then drops a copy of the zip alongside it (so
    find_bundle_zip + the downloads manifest pick it up). Returns the slug, or
    None on failure.
    """
    slug = _safe_slug(zip_path.name)
    dest = run_dir / "bundles" / slug
    tmp = run_dir / ".tmp_bundle_upload"
    try:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        # Locate the directory that actually holds competition.yaml.
        comp = next((p for p in tmp.rglob("competition.yaml")), None)
        bundle_root = comp.parent if comp is not None else tmp
        dest.mkdir(parents=True, exist_ok=True)
        for item in bundle_root.iterdir():
            target = dest / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
        shutil.copy2(zip_path, dest / f"{slug}.zip")
        return slug
    except Exception as e:
        log.warning("seed bundle from %s failed: %s", zip_path, e)
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _ingest_seed_artifacts(run_dir: Path, msg) -> list[str]:
    """Seed phase artifacts from recognised chat attachments.

    Returns a list of seeded kinds ('plan' and/or 'bundle'). Unrecognised
    attachments are ignored here (they still flow through the normal
    attachment-extraction path).
    """
    elements = getattr(msg, "elements", None) or []
    seeded: list[str] = []
    for el in elements:
        path = getattr(el, "path", None)
        name = getattr(el, "name", None) or (Path(path).name if path else "")
        if not path or not Path(path).exists():
            continue
        lname = name.lower()
        if lname == "implementation_plan.md" or lname.endswith("/implementation_plan.md"):
            specs = run_dir / "specs"
            specs.mkdir(exist_ok=True)
            try:
                shutil.copy2(path, specs / "implementation_plan.md")
                seeded.append("plan")
            except Exception as e:
                log.warning("seed plan from %s failed: %s", path, e)
        elif lname.endswith(".zip") and _zip_is_bundle(Path(path)):
            if _seed_bundle_from_zip(run_dir, Path(path)) is not None:
                seeded.append("bundle")
    return seeded


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------

class SessionManager:
    """Handles the Chainlit session lifecycle and per-turn message routing."""

    @staticmethod
    async def on_chat_start() -> None:
        """Initialise a new chat session.

        1. Guard against duplicate firings (reconnect / second tab).
        2. Create an isolated run dir with the layout the MCP server expects.
        3. Probe MCP imports and surface any startup failures immediately.
        4. Build the Phase 1 SDK client and send the greeting.
        5. Pre-write public artifacts so the workspace panel paints on load.
        """
        # Guard: on_chat_start re-fires on websocket reconnect or duplicate tabs.
        if cl.user_session.get("session_id"):
            log.info("on_chat_start re-fired for existing session %s — skipping",
                     cl.user_session.get("session_id"))
            cl.user_session.set("ready", True)
            return

        cl.user_session.set("ready", False)

        # 1. Per-session isolated run dir.
        from autocodabench.core.config import runs_root as _acb_runs_root
        RUNS_ROOT  = _acb_runs_root()
        session_id = uuid.uuid4().hex[:12]
        user       = cl.user_session.get("user")
        user_id    = (user.identifier if user else "anon").replace("/", "_")
        runtime_id = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S")
        run_dir    = RUNS_ROOT / f"web_{user_id}_{runtime_id}_{session_id}"
        run_dir.mkdir(parents=True, exist_ok=True)

        for sub in ("tool_calls", "specs", "specs_history", "mcp_stderr"):
            (run_dir / sub).mkdir(exist_ok=True)

        meta = {
            "started_at": utc_now(),
            "branch_id":  f"web-{user_id}",
            "runtime_id": runtime_id,
            "slug":       f"web_{session_id}",
            "session_id": session_id,
            "user":       user_id,
            "git_sha":    None,
            "cwd":        str(REPO_ROOT),
            "pid":        os.getpid(),
            "created_by": "web/session_manager.py:on_chat_start",
        }
        (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        cl.user_session.set("run_dir",          str(run_dir))
        cl.user_session.set("session_id",       session_id)
        cl.user_session.set("started_at",       utc_now())
        cl.user_session.set("had_user_message", False)

        # 2. MCP probe.
        mcp_servers   = build_mcp_servers(run_dir)
        cl.user_session.set("mcp_servers", mcp_servers)

        mcp_failures = probe_mcp_imports()
        if mcp_failures:
            await cl.Message(
                content=(
                    "**⚠️ MCP servers failed to start.** Tools will be "
                    "unavailable in this session.\n\n"
                    + "\n\n".join(mcp_failures)
                ),
                author="autocodabench",
            ).send()

        # 3. SDK client for Phase 1.
        cl.user_session.set("phase",              PHASE_PLAN)
        cl.user_session.set("phase_history",      [])
        cl.user_session.set("last_input_tokens",  0)
        cl.user_session.set("last_output_tokens", 0)
        cl.user_session.set("cum_cost_usd",       0.0)

        client = ClaudeSDKClient(options=_build_sdk_options(run_dir, PHASE_PLAN, mcp_servers))
        await client.connect()
        cl.user_session.set("client", client)

        # 4. Greeting (READY_PHRASE must appear here for chat.js to unlock the input).
        await cl.Message(
            content=(
                "# AutoCodabench\n\n"
                "Tell me a competition idea — a sentence is enough — and I'll "
                "explore the design space with you, citing the literature as "
                "we go. You can also drop a PDF / markdown design doc and I'll "
                "fill in the gaps.\n\n"
                "**Start at any phase by dropping a file in the chat:**\n"
                "- an `implementation_plan.md` → jump to "
                f"**{PHASE_TITLE[PHASE_BUNDLE]}**.\n"
                "- a competition **bundle `.zip`** → jump to "
                f"**{PHASE_TITLE[PHASE_VALIDATE]}**.\n\n"
                "_New here? Open **Readme** in the top-right for how the "
                "phase bar works._\n\n"
                f"_session `{session_id}` · model `{DEFAULT_MODEL}` · "
                f"budget ${MAX_USD_PER_SESSION:.2f}_"
            ),
            author="autocodabench",
        ).send()
        cl.user_session.set("ready", True)

        # 5. Pre-write public artifacts and phase state.
        PublicArtifacts.write(run_dir, session_id)
        PhaseManager.write_state(run_dir)
        await PhaseManager.refresh_phase_controls()

    @staticmethod
    async def on_message(msg: cl.Message) -> None:
        """Handle one user message: augment with attachments, stream response."""
        phase = cl.user_session.get("phase") or "unknown"
        log.info("[session] on_message — phase=%r content=%.80r", phase, msg.content)
        if not cl.user_session.get("ready"):
            log.warning("[session] on_message called before session ready — dropping")
            await cl.Message(
                content="_Still initializing — give me a few more seconds._",
                author="autocodabench",
            ).send()
            return

        client  = cl.user_session.get("client")
        run_dir = Path(cl.user_session.get("run_dir"))

        if client is None:
            log.error("[session] on_message: no client in session — cannot respond")
            await cl.Message(content="(no active session; please refresh)").send()
            return

        cl.user_session.set("had_user_message", True)

        # Phase-seeding: if the user dropped an implementation_plan.md or a
        # bundle .zip, save it as the corresponding phase artifact and let them
        # jump straight to the next phase instead of running the planner.
        seeded = _ingest_seed_artifacts(run_dir, msg)
        if seeded:
            await SessionManager._announce_seeded(run_dir, seeded)
            session_id = cl.user_session.get("session_id") or ""
            PhaseManager.write_state(run_dir)
            await PhaseManager.refresh_phase_controls()
            PublicArtifacts.write(run_dir, session_id)
            asyncio.create_task(persist_to_hf(run_dir))
            log.info("[session] on_message seeded=%s — short-circuiting agent turn", seeded)
            return

        augmented_text = SessionManager._augment_user_message(run_dir, msg)
        Transcript.append(run_dir, role="user", text=augmented_text)

        response_msg = cl.Message(content="", author="autocodabench")
        await response_msg.send()
        log.info("[session] starting run_agent_turn for user message")
        await run_agent_turn(client, augmented_text, run_dir, response_msg)
        log.info("[session] run_agent_turn complete — writing state and checking bundle")

        PhaseManager.write_state(run_dir)
        await PhaseManager.refresh_phase_controls()
        await PhaseManager.maybe_offer_bundle_actions()
        log.info("[session] on_message DONE")
        asyncio.create_task(persist_to_hf(run_dir))

    @staticmethod
    async def on_chat_end() -> None:
        """Disconnect the SDK client and do a final HF persist."""
        run_dir_str  = cl.user_session.get("run_dir")
        had_activity = cl.user_session.get("had_user_message", False)
        if run_dir_str and had_activity:
            try:
                await persist_to_hf(Path(run_dir_str))
            except Exception as e:
                log.warning("final HF persist failed: %s", e)
        client = cl.user_session.get("client")
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass

    @staticmethod
    async def _announce_seeded(run_dir: Path, seeded: list[str]) -> None:
        """Tell the user which artifact was imported and where they can jump."""
        lines: list[str] = []
        if "plan" in seeded:
            lines.append(
                f"📝 Saved your **implementation_plan.md** as the "
                f"{PHASE_TITLE[PHASE_PLAN]} artifact. Click the "
                f"**{PHASE_TITLE[PHASE_BUNDLE]}** pill in the phase bar to "
                f"build the bundle from it — or keep chatting to revise the "
                f"plan first."
            )
        if "bundle" in seeded:
            lines.append(
                f"📦 Imported your **bundle** as the "
                f"{PHASE_TITLE[PHASE_BUNDLE]} artifact. Click the "
                f"**{PHASE_TITLE[PHASE_VALIDATE]}** pill to lint it."
            )
        await cl.Message(
            author="autocodabench",
            content="### ✅ Artifact imported\n\n" + "\n\n".join(lines),
        ).send()

    @staticmethod
    def _augment_user_message(run_dir: Path, msg: cl.Message) -> str:
        """Prepend extracted attachment text to the user's message.

        Also mirrors each file into <run_dir>/uploads/ so the agent can
        re-read it later via the Read tool.
        """
        elements = getattr(msg, "elements", None) or []
        if not elements:
            return msg.content or ""

        uploads_dir = run_dir / "uploads"
        uploads_dir.mkdir(exist_ok=True)
        extracted_blocks: list[str] = []

        for el in elements:
            result = _extract_attachment_text(el)
            if result is None:
                continue
            label, body = result
            src = getattr(el, "path", None)
            if src and Path(src).exists():
                try:
                    shutil.copy2(src, uploads_dir / Path(src).name)
                except Exception as e:
                    log.warning("failed to mirror %s: %s", src, e)
            extracted_blocks.append(
                f"<attached_document name=\"{label}\">\n{body}\n</attached_document>"
            )

        if not extracted_blocks:
            return msg.content or ""

        head = (
            f"_The user attached {len(extracted_blocks)} document(s). "
            f"Use the extracted text below as reference for the plan._"
        )
        return f"{msg.content or ''}\n\n{head}\n\n" + "\n\n".join(extracted_blocks)
