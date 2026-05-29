"""MCP tool: publish a built bundle to Codabench.

Thin wrapper around the reference upload script at
`documentation/codabench_bundle_upload/upload_bundle.py`. We import its
helper functions directly rather than reimplementing the 4-step flow,
so this stays in sync with whatever the canonical script does.

Auth credentials come from environment:
  - CODABENCH_BASE_URL  (default https://www.codabench.org)
  - CODABENCH_USERNAME + CODABENCH_PASSWORD, OR
  - CODABENCH_TOKEN

If both forms are set, username+password wins (a fresh token is fetched
on each call, so a 90-day token rotation will not surprise us).
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

from ..config import REPO_ROOT, resolve_bundle_dir
from ..mcp import mcp
from ..run_log import logged_tool

log = logging.getLogger("autocodabench.upload")


def _load_upload_helpers():
    """Dynamically import the upload_bundle.py module from the docs dir.

    We do this lazily so module import doesn't fail in environments
    where the docs tree is missing (CI, slim Docker images, etc.).
    """
    script = REPO_ROOT / "documentation" / "codabench_bundle_upload" / "upload_bundle.py"
    if not script.is_file():
        raise FileNotFoundError(
            f"Upload script not found at {script}. The autocodabench_upload_bundle "
            "tool needs documentation/codabench_bundle_upload/upload_bundle.py "
            "checked in."
        )
    spec = importlib.util.spec_from_file_location("codabench_upload_bundle", script)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upload_zip(
    zip_path: Path,
    *,
    username: str | None = None,
    password: str | None = None,
    token: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Publish an already-built zip to Codabench. Credentials-explicit.

    Used both by the MCP `autocodabench_upload_bundle` tool (which pulls
    creds from env) and by the web-UI `/ac/upload-codabench` route
    (which passes user-supplied creds from the workspace form). Pulling
    from env is therefore optional — callers can fully override.

    Returns a dict with `competition_id` + `competition_url` on success,
    or `{"error": "..."}` on any failure. Never raises.
    """
    if not zip_path.is_file():
        return {"error": f"zip not found at {zip_path}. Run zip_bundle first."}

    base_url = base_url or os.environ.get(
        "CODABENCH_BASE_URL", "https://www.codabench.org")
    username = username or os.environ.get("CODABENCH_USERNAME")
    password = password or os.environ.get("CODABENCH_PASSWORD")
    token    = token    or os.environ.get("CODABENCH_TOKEN")

    if not (username and password) and not token:
        return {
            "error": (
                "Missing Codabench credentials. Provide username + password "
                "(via the workspace form) or set CODABENCH_TOKEN."
            )
        }

    try:
        helpers = _load_upload_helpers()
    except Exception as e:
        return {"error": f"Could not load upload helpers: {e}"}

    log.info("upload_zip path=%s size=%d", zip_path, zip_path.stat().st_size)

    try:
        # Step 1: fetch a fresh token if we have user/pass.
        if username and password:
            token = helpers.obtain_token(base_url, username, password)
        assert token  # validated above

        # Step 2: create the dataset placeholder (returns a signed PUT URL).
        created = helpers.create_dataset_placeholder(
            base_url, token,
            name=zip_path.stem,
            zip_filename=zip_path.name,
            file_size=float(zip_path.stat().st_size),
        )
        dataset_key = str(created["key"])
        sassy_url = str(created["sassy_url"])

        # Step 3: PUT the zip bytes to the signed URL.
        helpers.put_zip_to_signed_url(sassy_url, zip_path)

        # Step 4: tell Codabench the upload is done; receive a status_id to poll.
        final = helpers.finalize_dataset_upload(base_url, token, dataset_key)
        status_id = final.get("status_id")
        if status_id is None:
            return {
                "error": "Codabench returned no status_id; cannot poll. Raw response: " + str(final)
            }

        # Step 5: poll until Codabench finishes unpacking.
        outcome = helpers.poll_creation_status(
            base_url, token, status_id,
            poll_interval=3.0, timeout=120.0,
        )
    except SystemExit as e:
        # upload_bundle.py raises SystemExit on storage errors; convert.
        return {"error": f"Upload helper raised SystemExit: {e}"}
    except Exception as e:
        return {"error": f"Upload failed: {type(e).__name__}: {e}"}

    if outcome.get("status") != "Finished":
        return {
            "error": (
                f"Codabench unpack did not finish (status={outcome.get('status')}). "
                f"Full payload: {outcome}"
            ),
            "raw": outcome,
        }

    # Extract competition id and synthesize the public URL.
    comp = outcome.get("resulting_competition")
    if isinstance(comp, int):
        cid: Any = comp
    elif isinstance(comp, dict):
        cid = comp.get("pk") or comp.get("id")
    else:
        cid = None

    if cid is None:
        return {
            "error": "Unpack finished but Codabench did not return a competition id.",
            "raw": outcome,
        }

    return {
        "competition_id": cid,
        "competition_url": f"{base_url.rstrip('/')}/competitions/{cid}/",
        "raw": outcome,
    }


def _do_upload(slug: str, root_dir: str | None) -> dict[str, Any]:
    """Resolve slug → zip path, then delegate to upload_zip (env-creds)."""
    bundle_dir = resolve_bundle_dir(slug, root_dir)
    zip_path = bundle_dir.parent / f"{slug}.zip"
    return upload_zip(zip_path)


@mcp.tool()
@logged_tool("autocodabench_upload_bundle")
async def autocodabench_upload_bundle(
    slug: str,
    root_dir: str | None = None,
) -> dict[str, Any]:
    """Publish the bundle's .zip to Codabench and return its public URL.

    Use this **only in Session 2 (execution)**, after
    `autocodabench_validate_bundle` is clean and `autocodabench_zip_bundle`
    has produced `<bundles_root>/<slug>.zip`.

    Args:
        slug:     bundle slug previously passed to autocodabench_init_bundle.
        root_dir: optional override of the bundles root.

    Returns:
        Dict with `competition_id`, `competition_url`, and the raw Codabench
        creation-status payload. On failure, `error` describes what went wrong.
    """
    log.info("upload_bundle requested slug=%s root_dir=%s", slug, root_dir)
    try:
        return await asyncio.to_thread(_do_upload, slug, root_dir)
    except Exception as e:
        return {"error": f"upload_bundle failed: {e}"}
