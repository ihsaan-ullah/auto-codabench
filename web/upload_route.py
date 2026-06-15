"""FastAPI upload route for direct-to-Codabench bundle publishing.

Mounts POST /ac/upload-codabench on Chainlit's underlying FastAPI app.
Credentials come from the user typing them into the workspace panel form —
they are NOT routed through the LLM and NOT stored in env vars.

Mounted on the same origin as the chat so there are no CORS issues.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from artifacts import PublicArtifacts, Transcript, utc_now
from config import PUBLIC_SESSIONS
from autocodabench.core.config import runs_root as _acb_runs_root

log = logging.getLogger("autocodabench.web.upload_route")

RUNS_ROOT = _acb_runs_root()


def _resolve_session_run_dir(session_id: str) -> Path | None:
    """Locate the run dir for a session by globbing for its meta.json.

    Run dirs are named `web_<user>_<runtime>_<session_id>/`. A simple
    suffix match on session_id is sufficient.
    """
    if not session_id:
        return None
    for candidate in RUNS_ROOT.glob(f"web_*_{session_id}"):
        if (candidate / "meta.json").is_file():
            return candidate
    return None


def register_upload_route() -> None:
    """Mount POST /ac/upload-codabench on Chainlit's FastAPI app.

    Idempotent — safe to call multiple times. The app is tagged after the
    first registration so module re-imports don't double-register.
    """
    try:
        from chainlit.server import app as cl_app
        from fastapi import Request
        from fastapi.responses import JSONResponse
    except Exception as e:
        log.warning("Chainlit FastAPI app unavailable; upload route not mounted: %s", e)
        return

    if getattr(cl_app, "_ac_upload_route_registered", False):
        return
    cl_app._ac_upload_route_registered = True  # type: ignore[attr-defined]

    @cl_app.post("/ac/upload-codabench")
    async def _ac_upload_codabench(request: Request) -> JSONResponse:
        """Upload a session's bundle.zip to Codabench using user-supplied creds.

        Request body (JSON): {"session_id": str, "username": str, "password": str}
        Response:            {"ok": bool, "competition_url"?: str, "error"?: str}

        Every non-success path returns BOTH `ok: False` AND a non-empty
        `error` string. The UI's "unknown error" fallback only fires when
        this contract is broken.
        """
        try:
            body = await request.json()
        except Exception as e:
            log.warning("upload-codabench: malformed JSON body: %s", e)
            return JSONResponse({"ok": False, "error": f"invalid JSON body: {e!s}"}, status_code=400)

        sid      = str(body.get("session_id") or "").strip()
        username = str(body.get("username")   or "").strip()
        password =     body.get("password")   or ""

        if not sid:
            return JSONResponse({"ok": False, "error": "session_id is required"}, status_code=400)
        if not username:
            return JSONResponse({"ok": False, "error": "username is required"}, status_code=400)
        if not password:
            return JSONResponse({"ok": False, "error": "password is required"}, status_code=400)

        run_dir = _resolve_session_run_dir(sid)
        if run_dir is None:
            log.warning("upload-codabench: no run dir for sid=%s", sid)
            return JSONResponse(
                {"ok": False, "error": f"no run dir found for session {sid} under {RUNS_ROOT}."},
                status_code=404,
            )

        bundle_zip = PublicArtifacts.find_bundle_zip(run_dir)
        if bundle_zip is None or not bundle_zip.is_file():
            log.warning("upload-codabench: bundle.zip missing sid=%s run_dir=%s", sid, run_dir)
            return JSONResponse(
                {"ok": False, "error": "bundle.zip not found. Did Phase 2 finish?"},
                status_code=409,
            )

        log.info("upload-codabench START sid=%s user=%s zip=%s (%d bytes)",
                 sid, username, bundle_zip, bundle_zip.stat().st_size)

        try:
            from autocodabench.upload import upload_zip
            result = await asyncio.to_thread(
                upload_zip, bundle_zip, username=username, password=password,
            )
        except Exception as e:
            log.exception("upload-codabench: upload_zip raised")
            return JSONResponse(
                {"ok": False, "error": f"upload raised: {type(e).__name__}: {e!s}"},
                status_code=500,
            )

        if not isinstance(result, dict):
            return JSONResponse(
                {"ok": False, "error": f"upload_zip returned unexpected type {type(result).__name__}"},
                status_code=500,
            )
        if result.get("error"):
            return JSONResponse({"ok": False, "error": str(result["error"])}, status_code=502)

        comp_url = result.get("competition_url")
        comp_id  = result.get("competition_id")
        if not comp_url:
            return JSONResponse(
                {"ok": False, "error": f"upload finished but no competition_url returned. Raw keys: {sorted(result.keys())}"},
                status_code=502,
            )

        try:
            Transcript.append(run_dir, role="user",
                              text=f"[ui] Uploaded bundle to Codabench as `{username}`.")
            Transcript.append(run_dir, role="claude",
                              text=(f"🚀 **Bundle published to Codabench.**\n\n"
                                    f"competition: [{comp_url}]({comp_url}) (id `{comp_id}`)."))
        except Exception as e:
            log.warning("transcript append after upload failed: %s", e)

        log.info("upload-codabench OK sid=%s url=%s id=%s", sid, comp_url, comp_id)
        return JSONResponse({"ok": True, "competition_id": comp_id, "competition_url": comp_url})
