"""MCP tools that *execute* a Codabench bundle.

These are the runtime counterparts to the file-writer tools in
`bundle.py`. The implementer skill (`autocodabench-implement`) uses
them to self-validate the bundle it just wrote: run the bundle's own
baseline through the scoring pipeline (inside the bundle's declared
`docker_image`, exactly as the Codabench worker does — execution is
Docker-only) and execute the starting-kit notebook end-to-end (also
inside the image). The reformat-and-run skill uses
`run_user_submission` to score an external (ground-truth) submission
after it has been adapted to the bundle's interface.

The MCP wrappers are pure one-shots — the *skill* drives any retry
loop based on the returned `error` / `stderr_tail`. The loop belongs in
the skill, where a model session can read the traceback and decide how
to respond, not in this module, where it could only be a brittle regex
over stderr; a retry driven through logged tool calls is also an audit
trail, where one buried in library code would hide failures.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..instance import mcp
from ...run_log import logged_tool
from ...runner.execution import (
    install_env_extras,
    prepare_run_env,
    remove_run_env,
    run_baseline_submission,
    run_starting_kit,
    run_user_submission,
)

log = logging.getLogger("autocodabench.runner")


@mcp.tool()
@logged_tool("autocodabench_prepare_run_env")
async def autocodabench_prepare_run_env(
    slug: str,
    force_recreate: bool = False,
) -> dict[str, Any]:
    """Ensure the bundle's docker_image is available locally before runs.

    Docker-only execution has no per-run environment to build (programs run
    inside the bundle's declared `docker_image`, as on the platform). This
    checks the image is in the local Docker store and, if not, attempts one
    `docker pull`. If the image is an autocodabench base image you have not
    built/pulled, build it locally first (docker/build_and_push.sh, no --push)
    or point the bundle's docker_image at an available image.

    Args:
        slug:           bundle slug.
        force_recreate: accepted for compatibility; ignored.

    Returns:
        Dict: `ok`, `image`, `env_name` (= image), `present_locally`,
              `pulled`, `logs_dir`, `note`, `error`.
    """
    log.info("prepare_run_env slug=%s force_recreate=%s", slug, force_recreate)
    try:
        return await asyncio.to_thread(prepare_run_env, slug, force_recreate)
    except Exception as e:
        return {"ok": False, "error": f"prepare_run_env crashed: {e}"}


@mcp.tool()
@logged_tool("autocodabench_install_env_extras")
async def autocodabench_install_env_extras(
    env_name: str,
    packages: list[str],
) -> dict[str, Any]:
    """Unavailable under Docker-only execution (returns a guidance error).

    The Codabench worker installs nothing into the image, so a run-time pip
    install would make the bundle pass locally but fail on the platform. To
    add a dependency, set the bundle's `docker_image` to one that already
    ships it (a richer public image, or an autocodabench base image extended
    and rebuilt — see docker/README.md), then re-run.

    Returns:
        Dict: `ok=False`, `packages`, `error` (with the guidance above), `note`.
    """
    log.info("install_env_extras env=%s pkgs=%s", env_name, packages)
    try:
        return await asyncio.to_thread(install_env_extras, env_name, packages or [])
    except Exception as e:
        return {"ok": False, "error": f"install_env_extras crashed: {e}"}


@mcp.tool()
@logged_tool("autocodabench_run_baseline_submission")
async def autocodabench_run_baseline_submission(
    slug: str,
    env_name: str,
    subdir: str = "solution_baseline",
    extra_env: dict[str, str] | None = None,
    engine: str = "auto",
) -> dict[str, Any]:
    """Run the bundle's OWN baseline submission through ingestion + scoring.

    This is the bundle's self-test. The implementer skill calls this
    after writing the bundle to verify ingestion / scoring / metric
    plumbing actually works on real (toy) data, before any external
    submission ever touches it.

    Docker-only: the programs run inside the bundle's declared `docker_image`
    exactly as the Codabench worker runs them — no dependency installation,
    working dir `/app/program` — so a clean run is evidence of platform
    behavior. A Docker daemon is required; without one this returns an error.
    A `ModuleNotFoundError` means the declared `docker_image` lacks the
    dependency — change the image in competition.yaml to one that ships it
    (run-time installation is not available and would not be platform-faithful).

    Falls back gracefully to other common subdir names
    (`sample_code_submission`, `solution1`) if `subdir` does not exist.

    The container keeps the image's own thread/BLAS defaults, as the platform
    does. Pass `extra_env` ONLY to override (e.g. `{"OMP_NUM_THREADS": "4"}`).

    Args:
        slug:      bundle slug.
        env_name:  accepted for compatibility; ignored (Docker-only).
        subdir:    directory under `solutions/` containing the baseline.
        extra_env: optional env-var overrides applied at subprocess
                   start time (passed as `-e` under docker).
        engine:    "auto" (default) | "docker" (both require Docker).

    Returns:
        Dict: `ok`, `stage` ("ingestion"|"scoring"), `engine`,
              `docker_image`, `engine_note`, `ingestion`
              (`exit_code`/`stdout_tail`/`stderr_tail`/`duration_s`,
              `null` if λ-style), `scoring` (same shape), `scores`,
              `scores_format`, `sandbox_dir`, `logs_dir`, `error`.
              The `scores` dict mirrors the bundle's `scores.json`
              top-level keys verbatim.
    """
    log.info("run_baseline slug=%s env=%s subdir=%s engine=%s extra_env=%s",
             slug, env_name, subdir, engine, list((extra_env or {}).keys()))
    try:
        return await asyncio.to_thread(run_baseline_submission, slug, env_name, subdir,
                                       extra_env, engine)
    except Exception as e:
        return {"ok": False, "error": f"run_baseline_submission crashed: {e}"}


@mcp.tool()
@logged_tool("autocodabench_run_user_submission")
async def autocodabench_run_user_submission(
    slug: str,
    env_name: str,
    submission_dir: str,
    label: str,
    extra_env: dict[str, str] | None = None,
    engine: str = "auto",
) -> dict[str, Any]:
    """Run an external submission directory through ingestion + scoring.

    Used by `autocodabench-reformat-and-run` to score a ground-truth
    submission after it has been adapted to the bundle's interface. Same
    pipeline and engine semantics as `run_baseline_submission` (Docker-only —
    the bundle's declared `docker_image`, as the platform runs it), but the
    submission code is sourced from `submission_dir` instead of the bundle's
    `solutions/`.

    The container keeps the image's own thread/BLAS defaults, as the platform
    does. Pass `extra_env` only to override per-call.

    Args:
        slug:           bundle slug.
        env_name:       accepted for compatibility; ignored (Docker-only).
        submission_dir: absolute path to the submission folder.
        label:          short identifier scoping the run logs (e.g.
                        `"sub_1.attempt_2"`); appears in `logs_dir`.
        extra_env:      optional env-var overrides applied at subprocess
                        start time.
        engine:         "auto" (default) | "docker" (both require Docker).

    Returns:
        Same shape as `run_baseline_submission`.
    """
    log.info("run_user slug=%s env=%s sub=%s label=%s engine=%s extra_env=%s",
             slug, env_name, submission_dir, label, engine,
             list((extra_env or {}).keys()))
    try:
        return await asyncio.to_thread(run_user_submission, slug, env_name, submission_dir,
                                       label, extra_env, engine)
    except Exception as e:
        return {"ok": False, "error": f"run_user_submission crashed: {e}"}


@mcp.tool()
@logged_tool("autocodabench_run_starting_kit")
async def autocodabench_run_starting_kit(
    slug: str,
    env_name: str,
    notebook_path: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute the bundle's starting-kit notebook end-to-end inside Docker.

    Looks for `README.ipynb` at the bundle root or any `.ipynb` under
    `starting_kit/`. Runs `jupyter nbconvert --to notebook --execute --inplace`
    inside the bundle's `docker_image` (which ships the notebook toolchain),
    with the bundle mounted at `/app` as the working directory so relative
    paths resolve. Any cell that errors fails the run with the traceback in
    `stderr_tail`. The executed copy is saved under
    `<run>/run_logs/<slug>/starting_kit/executed.ipynb` for review.

    Args:
        slug:          bundle slug.
        env_name:      accepted for compatibility; ignored (Docker-only).
        notebook_path: optional explicit path; otherwise auto-discovered.
        extra_env:     optional env-var overrides.

    Returns:
        Dict: `ok`, `notebook_source`, `executed_notebook`,
              `cells_executed`, `exit_code`, `duration_s`, `timed_out`,
              `stdout_tail`, `stderr_tail`, `stdout_path`, `stderr_path`,
              `logs_dir`, `error`.
    """
    log.info("run_starting_kit slug=%s env=%s nb=%s extra_env=%s",
             slug, env_name, notebook_path, list((extra_env or {}).keys()))
    try:
        return await asyncio.to_thread(run_starting_kit, slug, env_name, notebook_path,
                                       extra_env)
    except Exception as e:
        return {"ok": False, "error": f"run_starting_kit crashed: {e}"}


@mcp.tool()
@logged_tool("autocodabench_remove_run_env")
async def autocodabench_remove_run_env(env_name: str) -> dict[str, Any]:
    """No-op under Docker-only execution (kept for caller compatibility).

    There is no per-run environment to remove: containers run with `--rm` and
    remove themselves, and base images are shared, not per-run. The
    orchestrator may still call this at the end of a run; it returns ok.

    Args:
        env_name: ignored.

    Returns:
        Dict: `ok`, `env_name`, `note`.
    """
    log.info("remove_run_env env=%s", env_name)
    try:
        return await asyncio.to_thread(remove_run_env, env_name)
    except Exception as e:
        return {"ok": False, "error": f"remove_run_env crashed: {e}"}
