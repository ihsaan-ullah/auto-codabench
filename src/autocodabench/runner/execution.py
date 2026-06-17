"""Execution-side helpers for the autocodabench MCP server.

The bundle-write side (`bundle_io.py`) only knows about *files*. This
module is the runtime counterpart: it stages the Codabench sandbox
layout, invokes the bundle's scoring / ingestion programs end-to-end,
and executes the bundle's `starting_kit` notebook.

Execution is **Docker-only**. Every program — scoring, ingestion, and the
starting-kit notebook — runs inside the bundle's declared ``docker_image``
exactly as the Codabench compute worker does: working directory
``/app/program`` (or the bundle root for the notebook), the sandbox mounted
under ``/app``, and **no dependency installation** (the worker never installs
``requirements.txt``; dependencies must be baked into the image — see the
autocodabench base images in ``docker/``). A clean local run is therefore
evidence the bundle will execute on the platform; a subsequent platform
failure points at the server, not the bundle. There is no host-side fallback:
a missing Docker daemon is a hard error. (The previous conda engine has been
removed; ``prepare_run_env`` now only ensures the image is present locally,
and ``remove_run_env`` / ``install_env_extras`` are retained as compatibility
shims — containers are ephemeral and dependencies belong in the image.)

Used by the `autocodabench-implement` skill so it can self-validate the bundle
it just wrote (run its own sample submission + starting kit) and by
`autocodabench-reformat-and-run` (run an external user submission through the
bundle's scoring pipeline).

Design rules:

- **Pure one-shot.** Each function does one operation and returns;
  iteration is the model's job. No internal retry loops.
- **No model in this file.** Diagnosis of stderr lives in the skill
  prompt, which is where the actual Claude session can reason about
  the failure.
- **Bounded output.** stdout/stderr are tee'd to disk in full, but
  the returned dict carries only the last ~80 lines of each, keeping
  subprocess noise out of the model's context while preserving the
  complete record on disk.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shlex
import shutil
import signal
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, IO, TextIO

import yaml  # PyYAML — already a dependency via fastmcp

from ..core.config import resolve_bundle_dir
from ..run_log import current_run, log_event

# How many tail lines of stdout/stderr to return inline. The full streams
# are always tee'd to disk; this only affects the in-message preview.
_TAIL_LINES = 80

# Cap individual subprocess wall-clock to 30 min by default. Long enough
# for a CPU-side baseline epoch but short enough to fail loud if the
# scoring program hangs.
_DEFAULT_TIMEOUT_S = 1800

# Defaults set in the OS environ for every subprocess we launch. These
# MUST be set before python starts because:
#
# 1. libomp / OpenBLAS / MKL read their thread-count vars at .so-load
#    time. By the time `import numpy` returns (which itself pulls libomp
#    in), the thread pools are already sized. Setting OMP_NUM_THREADS=1
#    in Python via `os.environ.setdefault` is too late — that was the
#    failure mode that hung the sub_1 run on macOS/arm64 for 24 minutes
#    using ~10s of CPU.
# 2. TF reads its inter/intra-op thread vars at session-creation time;
#    similar story.
# 3. PYTHONUNBUFFERED=1 makes child python flush stdout/stderr promptly
#    so the tee-to-disk output is closer to live.
# 4. TF_CPP_MIN_LOG_LEVEL=2 silences TF's INFO chatter; warnings/errors
#    still surface.
#
# Single-threading BLAS/OMP is a defensive default for the developer
# laptop case (small, toy-sized data — multi-threading overhead would
# dominate anyway). On Codabench's Linux workers + Docker the bundle
# will run with the docker_image's default settings, not these — the
# values live in the *harness's* subprocess env, not in the bundle.
# Per-call `env=` overrides still win (e.g. `extra_env={"OMP_NUM_THREADS": "8"}`).
_SUBPROCESS_DEFAULTS = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "TF_NUM_INTEROP_THREADS": "1",
    "TF_NUM_INTRAOP_THREADS": "1",
    "TF_CPP_MIN_LOG_LEVEL": "2",
    "PYTHONUNBUFFERED": "1",
}


# ---------------------------------------------------------------------------
# Execution engines
# ---------------------------------------------------------------------------

# Default docker_image for a bundle that declares none.
#
# autocodabench ships two purpose-built base images (docker/*.Dockerfile):
# autocodabench-base-cpu (Codabench py312 + the essential scientific stack and
# a pinned starting-kit notebook toolchain) and autocodabench-base-gpu (the
# gpu310 worker image plus the same stack). Pre-baking the dependencies means
# the great majority of generated bundles run inside the exact image
# Codabench's worker will use, with no per-run installation — the platform
# installs nothing, so a clean local run is evidence of a clean platform run.
#
# The names below are the *intended* published locations; they resolve only
# after the images are built and pushed (docker/build_and_push.sh) under a
# namespace you control. Override per-environment with AUTOCODABENCH_DOCKER_IMAGE
# / AUTOCODABENCH_DOCKER_IMAGE_GPU, or set AUTOCODABENCH_DOCKER_NAMESPACE to
# rewrite just the namespace. Until then, set the env var to a stock image
# (e.g. codalab/codalab-legacy:py312) to run without the custom base.
_DOCKER_NAMESPACE = os.environ.get("AUTOCODABENCH_DOCKER_NAMESPACE", "autocodabench")
_DEFAULT_DOCKER_IMAGE = os.environ.get(
    "AUTOCODABENCH_DOCKER_IMAGE", f"{_DOCKER_NAMESPACE}/autocodabench-base-cpu:latest")
_DEFAULT_DOCKER_IMAGE_GPU = os.environ.get(
    "AUTOCODABENCH_DOCKER_IMAGE_GPU", f"{_DOCKER_NAMESPACE}/autocodabench-base-gpu:latest")

# autocodabench executes exclusively through Docker: the Codabench worker runs
# a bundle's programs inside its declared docker_image and installs nothing, so
# Docker is the only faithful path. ("conda" is accepted as an argument only to
# return a clear "removed" error.)
_ENGINES = ("auto", "docker")

# Worker-faithful container paths. The Codabench compute worker mounts the
# *active program directory* (scoring OR ingestion, run as separate
# invocations) at /app/program, with the working directory set there, and
# the data/output trees at the paths below (compute_worker.py). It also
# substitutes legacy $variables in metadata commands with these paths
# before execution. We honor both spellings — the literal /app/... path
# and its $variable — so a bundle authored either way runs unchanged.
#
# `_WORKER_PATHS` maps each (variable, absolute) spelling to the role used
# to resolve it per engine. Order is longest-first so that, e.g.,
# `/app/input_data` is matched before `/app/input`.
_WORKER_ROLES = (
    # (role, container_abs_path, variable_alias)
    ("input_data", "/app/input_data", "$input_data"),
    ("ingested_program", "/app/ingested_program", "$ingested_program"),
    ("submission", "/app/submission", "$submission"),
    ("program", "/app/program", "$program"),
    ("output", "/app/output", "$output"),
    ("input", "/app/input", "$input"),
)


def _docker_available() -> bool:
    """True when a Docker CLI and a reachable daemon are both present."""
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=10,
        )
        return probe.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def bundle_docker_image(slug: str, root_dir: str | None = None) -> str:
    """The image competition.yaml declares; Codabench's default otherwise.

    ``AUTOCODABENCH_DOCKER_IMAGE_OVERRIDE`` wins over *both* — a deliberate,
    explicit local escape hatch (unlike ``AUTOCODABENCH_DOCKER_IMAGE``, which is
    only the fallback when a bundle declares no image). It lets a user on an
    incompatible host substitute a native image for the bundle's declared one
    to test locally. Because the substitute differs from what the platform will
    actually use, callers should surface that the run is a local convenience,
    not a faithful platform validation."""
    override = os.environ.get("AUTOCODABENCH_DOCKER_IMAGE_OVERRIDE", "").strip()
    if override:
        return override
    yaml_path = resolve_bundle_dir(slug, root_dir) / "competition.yaml"
    if yaml_path.is_file():
        try:
            comp = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            image = comp.get("docker_image")
            if isinstance(image, str) and image.strip():
                return image.strip()
        except yaml.YAMLError:
            pass
    return _DEFAULT_DOCKER_IMAGE


def docker_image_overridden() -> str | None:
    """The override image if ``AUTOCODABENCH_DOCKER_IMAGE_OVERRIDE`` is set."""
    v = os.environ.get("AUTOCODABENCH_DOCKER_IMAGE_OVERRIDE", "").strip()
    return v or None


def emulation_allowed() -> bool:
    """Whether the user has explicitly opted in to the slow QEMU-emulated run
    (``AUTOCODABENCH_ALLOW_EMULATION=1``)."""
    return os.environ.get("AUTOCODABENCH_ALLOW_EMULATION", "").strip().lower() in (
        "1", "true", "yes", "on")


# A native, multi-arch CPU image: the Codabench base resolves to the host arch
# on both amd64 and Apple-silicon, so it never emulates (see docker/README.md).
_NATIVE_MULTIARCH_IMAGE = "codalab/codalab-legacy:py312"


def emulation_guidance(preflight: dict[str, Any]) -> str | None:
    """If the image would run under QEMU emulation on this host, return a verbose,
    honest message (cost + remedies); else ``None``.

    Pure function of a :func:`docker_preflight` dict, so it is unit-testable
    without Docker."""
    if preflight.get("emulated") is not True:
        return None
    host = preflight.get("host_arch") or "this host"
    image = preflight.get("image") or "the declared image"
    arches = preflight.get("image_available_arches") or []
    only = "/".join(arches) if arches else (preflight.get("image_arch") or "a foreign arch")
    return (
        f"Docker image '{image}' is {only}-only, but this host is {host}. "
        f"Running it requires QEMU emulation, which is very slow — a baseline + "
        f"starting-kit validation typically takes well over 20 minutes. Execution "
        f"was skipped rather than run silently under emulation.\n"
        f"You can:\n"
        f"  1. Use a native, multi-arch image (recommended) and re-run a fresh "
        f"`autocodabench validate`:\n"
        f"       export AUTOCODABENCH_DOCKER_IMAGE_OVERRIDE={_NATIVE_MULTIARCH_IMAGE}\n"
        f"     (the Codabench CPU base is amd64+arm64; or build the autocodabench "
        f"base from docker/ — see docker/README.md). Note: a substitute image may "
        f"lack libraries the bundle's declared image ships, so the baseline can "
        f"fail on a missing dependency — that is a local-convenience run, not a "
        f"faithful check against the platform's image.\n"
        f"  2. Run static checks only (no Docker): add --no-execute.\n"
        f"  3. Force the slow emulated run anyway: export AUTOCODABENCH_ALLOW_EMULATION=1"
    )


_NO_DOCKER_ERROR = (
    "no Docker daemon is reachable. autocodabench executes exclusively through "
    "Docker — it runs a bundle's programs inside its declared docker_image "
    "exactly as the Codabench worker does. Install and start Docker, then retry "
    "(see docker/README.md)."
)


def resolve_execution_engine(engine: str = "auto") -> dict[str, Any]:
    """Confirm Docker is available for scoring/ingestion runs.

    Docker is the only execution path: the Codabench worker runs a bundle's
    programs inside its declared ``docker_image`` and installs nothing, so a
    clean local run is evidence of platform behavior. The conda engine has been
    removed; passing ``engine="conda"`` returns an explanatory error.

    Returns ``{"engine": "docker"|None, "note": ..., "error": ...}``.
    """
    if engine == "conda":
        return {"engine": None, "note": None,
                "error": "the conda execution engine has been removed; "
                         "autocodabench now runs exclusively through Docker. "
                         + _NO_DOCKER_ERROR}
    if engine not in _ENGINES:
        return {"engine": None, "note": None,
                "error": f"unknown engine {engine!r}; expected one of {_ENGINES}"}
    if _docker_available():
        return {"engine": "docker", "note": None, "error": None}
    return {"engine": None, "note": None, "error": _NO_DOCKER_ERROR}


# ---------------------------------------------------------------------------
# Docker preflight: report which image will run, its CPU architecture, and
# whether it matches the host (native) or will run under QEMU emulation (slow).
# Surfaced at the start of `create` / `validate` so the user knows the
# runtime up front and that Docker is a prerequisite.
# ---------------------------------------------------------------------------

# Normalize the many spellings the Docker/OS toolchain uses for the same CPU
# architecture to the two that matter here. `docker info` reports `aarch64`
# for Apple silicon while image manifests use `arm64`; both mean the same
# thing, and an image whose arch set includes the host arch runs natively.
_ARCH_ALIASES = {
    "arm64": "arm64", "aarch64": "arm64", "arm64/v8": "arm64",
    "x86_64": "amd64", "amd64": "amd64",
}


def _normalize_arch(raw: str | None) -> str:
    a = (raw or "").strip().lower()
    return _ARCH_ALIASES.get(a, a or "unknown")


def _host_arch() -> str:
    """The host CPU architecture, normalized to 'arm64' | 'amd64' | raw."""
    return _normalize_arch(platform.machine())


def _docker_query(args: list[str], timeout: int = 20) -> tuple[str | None, str | None]:
    """Run `docker <args>`, returning (stdout, None) on success or
    (None, error) otherwise. Never raises — preflight must not crash a run."""
    if shutil.which("docker") is None:
        return None, "docker CLI not found on PATH"
    try:
        res = subprocess.run(["docker", *args], capture_output=True,
                             text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)
    if res.returncode != 0:
        return None, (res.stderr or res.stdout or "docker error").strip()
    return res.stdout.strip(), None


def docker_daemon_status() -> dict[str, Any]:
    """Probe the local Docker install and daemon. Best-effort, never raises.

    Returns ``{cli_installed, daemon_running, os, arch, server_version}`` —
    ``arch`` is the daemon's CPU architecture, normalized (the VM Docker
    Desktop runs on a Mac, e.g. 'arm64' for Apple silicon).
    """
    if shutil.which("docker") is None:
        return {"cli_installed": False, "daemon_running": False,
                "os": None, "arch": None, "server_version": None}
    out, err = _docker_query(
        ["info", "--format", "{{.OSType}}|{{.Architecture}}|{{.ServerVersion}}"],
        timeout=12)
    if out is None:
        return {"cli_installed": True, "daemon_running": False,
                "os": None, "arch": None, "server_version": None}
    os_type, _, rest = out.partition("|")
    arch, _, server = rest.partition("|")
    return {"cli_installed": True, "daemon_running": True,
            "os": os_type or None, "arch": _normalize_arch(arch),
            "server_version": server.strip() or None}


def image_arch_status(image: str) -> dict[str, Any]:
    """Determine an image's CPU architecture(s) without running it.

    A local inspect is authoritative — it is the exact image Docker would run.
    For an image not yet pulled, a remote ``docker manifest inspect`` lists the
    architectures the registry offers (a multi-arch tag such as
    ``codalab/codalab-legacy:py312`` ships both amd64 and arm64; Docker then
    pulls the one matching the host, so it runs natively). Attestation entries
    (``platform.architecture == "unknown"``) are ignored.

    Returns ``{present_locally, arch, available_arches, multi_arch, source,
    error}``.
    """
    out, _err = _docker_query(
        ["image", "inspect", image, "--format", "{{.Architecture}}"])
    if out:
        arch = _normalize_arch(out.splitlines()[0])
        return {"present_locally": True, "arch": arch,
                "available_arches": [arch], "multi_arch": False,
                "source": "local image", "error": None}

    # Not pulled: ask the registry. `--verbose` exposes the architecture for
    # BOTH a multi-arch manifest list (a JSON array, one entry per platform)
    # and a single-arch image (a JSON object) — a plain `manifest inspect`
    # omits the arch of a single-arch image, since it lives in the config blob.
    out, err = _docker_query(["manifest", "inspect", "--verbose", image], timeout=30)
    if out:
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            data = None
        entries = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        arches: list[str] = []
        for e in entries:
            raw = (((e or {}).get("Descriptor") or {}).get("platform") or {}).get("architecture")
            if raw and raw != "unknown":
                arches.append(_normalize_arch(raw))
        arches = sorted(set(arches))
        return {
            "present_locally": False,
            "arch": arches[0] if len(arches) == 1 else None,
            "available_arches": arches, "multi_arch": len(arches) > 1,
            "source": "remote manifest",
            "error": None if arches else "no architectures listed in manifest",
        }
    # Collapse multi-line registry errors (auth/denied) into one tidy line.
    tidy = " ".join((err or "").split()) or "image not available locally or in any registry"
    return {"present_locally": False, "arch": None, "available_arches": [],
            "multi_arch": False, "source": None, "error": tidy}


def docker_preflight(image: str | None = None) -> dict[str, Any]:
    """One structured report of Docker readiness and image/host architecture fit.

    ``image`` defaults to the CPU base image. ``runs_natively`` is True when the
    image's architecture set includes the host arch (no emulation), False when
    it does not, and None when the architecture could not be determined
    (e.g. the image is not pulled and the registry is unreachable offline).
    ``emulated`` is the negation of ``runs_natively`` once known.

    This never raises: a missing Docker daemon yields ``ready=False`` with the
    detail in ``docker``, not an exception.
    """
    host = _host_arch()
    daemon = docker_daemon_status()
    image = image or _DEFAULT_DOCKER_IMAGE

    if daemon["daemon_running"]:
        img = image_arch_status(image)
    else:
        img = {"present_locally": False, "arch": None, "available_arches": [],
               "multi_arch": False, "source": None,
               "error": "Docker daemon not running"}

    arches = img["available_arches"]
    runs_natively = (host in arches) if arches else None
    return {
        "host_arch": host,
        "host_os": platform.system(),
        "docker": daemon,
        "image": image,
        "image_present_locally": img["present_locally"],
        "image_arch": img["arch"],
        "image_available_arches": arches,
        "image_multi_arch": img["multi_arch"],
        "image_source": img["source"],
        "image_error": img["error"],
        "runs_natively": runs_natively,
        "emulated": (None if runs_natively is None else not runs_natively),
        "ready": daemon["daemon_running"],
    }


def _host_path_for_role(role: str, sandbox: Path, program_subdir: str) -> Path:
    """Real on-disk path the worker would mount for a container role."""
    if role == "program":
        return sandbox / "program" / program_subdir
    if role == "ingested_program":
        return sandbox / "program" / "ingestion_program"
    return sandbox / role  # input, output, input_data, submission


def _resolve_command(cmd: str, eng: str, sandbox: Path, program_subdir: str) -> str:
    """Resolve worker path tokens in a metadata command.

    `$program`/`$input`/... become the worker's absolute container paths (the
    mounts make them real); literal `/app/...` paths are already correct and
    left untouched. `eng` is accepted for signature stability but is always
    "docker" now.
    """
    for _role, abspath, var in _WORKER_ROLES:
        cmd = cmd.replace(var, abspath)
    return cmd


def _docker_run(image: str, sandbox: Path, program_subdir: str, cmd: str,
                extra_env: dict[str, str] | None, has_ingestion: bool) -> str:
    """Build the ``docker run`` invocation that mirrors the compute worker.

    The active program directory is mounted at ``/app/program`` with the
    working directory set there, and the data/output trees at
    ``/app/input`` / ``/app/output`` / ``/app/input_data`` /
    ``/app/submission`` — exactly the worker's layout, so a bundle's
    ``/app/...`` metadata command runs verbatim. Nothing is installed
    into the container: the worker never installs ``requirements.txt``,
    so neither do we. The first run of a new image pulls it, which can
    take minutes and counts against the timeout.
    """
    mounts: list[tuple[Path, str, str]] = [
        (_host_path_for_role("program", sandbox, program_subdir), "/app/program", "rw"),
        (sandbox / "input", "/app/input", "rw"),
        (sandbox / "output", "/app/output", "rw"),
    ]
    for role in ("input_data", "submission", "public_data", "sample_data"):
        if (sandbox / role).exists():
            mounts.append((sandbox / role, f"/app/{role}", "rw"))
    if has_ingestion and program_subdir != "ingestion_program":
        mounts.append((sandbox / "program" / "ingestion_program",
                       "/app/ingested_program", "ro"))

    env = {"PYTHONUNBUFFERED": "1"}
    if extra_env:
        env.update(extra_env)
    env_flags = " ".join(f"-e {shlex.quote(f'{k}={v}')}" for k, v in env.items())
    vol_flags = " ".join(
        f"-v {shlex.quote(str(h))}:{c}:{m}" for h, c, m in mounts)
    resolved = _resolve_command(cmd, "docker", sandbox, program_subdir)
    return (f"docker run --rm {env_flags} {vol_flags} -w /app/program "
            f"{shlex.quote(image)} bash -c {shlex.quote(resolved)}")


def _pump(src: IO[str], sink: TextIO | None, tail: deque[str], counter: list[int]) -> None:
    """Daemon-thread body: copy one stream line-by-line to disk + ring buffer.

    `counter` is a single-element list used as a thread-safe lines-seen
    counter (GIL atomicity is enough — only one writer per stream). The
    ring buffer (`tail`, bounded `deque(maxlen=_TAIL_LINES)`) keeps the
    last N lines for the inline return.

    Each line is flushed to disk immediately. `bufsize=1` on the Popen
    + `flush()` here is what makes the on-disk file actually live —
    important for long-running TF/torch jobs where the only signal that
    they are alive is the steady drip of progress lines.
    """
    try:
        for line in iter(src.readline, ""):
            tail.append(line.rstrip("\n"))
            counter[0] += 1
            if sink is not None:
                sink.write(line)
                sink.flush()
    finally:
        try:
            src.close()
        except Exception:
            pass


def _bash(cmd: str, cwd: Path | str | None = None, timeout: int | None = None,
          stdout: Path | None = None, stderr: Path | None = None,
          env: dict[str, str] | None = None) -> dict[str, Any]:
    """Run a shell command. Tee streams to disk live (line-by-line).

    The on-disk files at `stdout` / `stderr` paths grow as the
    subprocess runs, so `tail -f` works from outside this process —
    important for long-running ingestion / training where the only
    signal the process is alive is its steady output. The
    `stdout_tail` / `stderr_tail` returned in the result dict are the
    last `_TAIL_LINES` lines collected by per-stream daemon threads.

    Returns a dict with exit_code, duration_s, stdout_tail, stderr_tail,
    stdout_path, stderr_path, stdout_lines, stderr_lines, command,
    timed_out.
    """
    timeout = timeout or _DEFAULT_TIMEOUT_S
    t0 = time.perf_counter()
    timed_out = False

    proc_env = os.environ.copy()
    # Set our subprocess defaults BEFORE merging caller's env, so explicit
    # caller values (e.g. extra_env={"OMP_NUM_THREADS": "8"}) override.
    for k, v in _SUBPROCESS_DEFAULTS.items():
        proc_env.setdefault(k, v)
    if env:
        proc_env.update(env)

    out_tail: deque[str] = deque(maxlen=_TAIL_LINES)
    err_tail: deque[str] = deque(maxlen=_TAIL_LINES)
    out_count = [0]
    err_count = [0]

    fout = stdout.open("w", encoding="utf-8") if stdout else None
    ferr = stderr.open("w", encoding="utf-8") if stderr else None

    try:
        # `start_new_session=True` makes the child a process-group leader, so
        # on timeout we can SIGKILL the whole group via `os.killpg` and reap
        # grandchildren (docker run → bash → python). Without this, `p.kill()`
        # only hits the direct child and leaves orphans pinning CPU/memory
        # — observed in the 6/3 run where the python ingestion process was
        # still alive 30+ minutes after its parent was killed.
        p = subprocess.Popen(
            cmd, shell=True, cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=proc_env, bufsize=1,
            start_new_session=True,
        )
        t_out = threading.Thread(target=_pump, args=(p.stdout, fout, out_tail, out_count),
                                 daemon=True)
        t_err = threading.Thread(target=_pump, args=(p.stderr, ferr, err_tail, err_count),
                                 daemon=True)
        t_out.start()
        t_err.start()

        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                p.kill()
            p.wait()
            timed_out = True

        # Let pump threads drain whatever buffered output the child wrote
        # between its last flush and exit. A short join is enough — the
        # child's pipes are closed once it exits, so `iter(readline, "")`
        # terminates.
        t_out.join(timeout=5)
        t_err.join(timeout=5)
        exit_code = p.returncode
    finally:
        if fout: fout.close()
        if ferr: ferr.close()

    duration_s = round(time.perf_counter() - t0, 2)
    return {
        "command": cmd,
        "exit_code": exit_code,
        "duration_s": duration_s,
        "timed_out": timed_out,
        "stdout_tail": "\n".join(out_tail),
        "stderr_tail": "\n".join(err_tail),
        "stdout_path": str(stdout) if stdout else None,
        "stderr_path": str(stderr) if stderr else None,
        "stdout_lines": out_count[0],
        "stderr_lines": err_count[0],
    }


def _run_logs_dir(slug: str, root_dir: str | None = None) -> Path:
    """Per-session run-logs root: <run>/run_logs/<slug>/ when a run is open.

    With no active run (a direct library/validate call), fall back to a
    ``<slug>_run_logs`` dir next to the bundle, resolving the bundle via the
    same ``root_dir`` the caller used so logs land beside the right bundle even
    for a foreign directory."""
    run = current_run()
    if run is None:
        # CLI / validate fallback: write next to the bundle.
        return resolve_bundle_dir(slug, root_dir).parent / f"{slug}_run_logs"
    d = run / "run_logs" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Execution cache — let pre-launch validation (phase 3) reuse the docker runs
# the build phase (phase 2) already performed, instead of re-running them.
#
# The cache lives *next to* the bundle directory (``<bundle>/../`` — the
# ``bundles/`` dir for a generated run, the bundle's parent for a hand-written
# one), keyed by the kind of run. Crucially it is keyed to the bundle's own
# location rather than to any run dir, so a separate ``validate``
# invocation pointed at the same bundle finds the build phase's entry. Each
# entry records the hash of the bundle's executable inputs; a reused result is
# only honoured when that hash still matches, so editing the scoring program /
# data / baseline between phase 2 and phase 3 invalidates the cache and forces
# a fresh run (the "ran plan+build, then changed the code" case).
# ---------------------------------------------------------------------------

_CACHE_FILENAME = ".acb_execution_cache.json"


def _iter_hashable_files(bundle_dir: Path):
    for p in sorted(bundle_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(bundle_dir)
        if any(part == "__pycache__" for part in rel.parts):
            continue
        if rel.name.startswith(".acb") or rel.suffix in (".zip", ".pyc"):
            continue
        yield rel, p


def bundle_content_hash(bundle_dir: str | Path) -> str:
    """A stable digest of a bundle's files (paths + contents).

    Coarse on purpose: any change anywhere in the bundle (scoring code, data,
    baseline, pages, competition.yaml) changes the hash and so invalidates a
    cached run. Reusing a stale result is far worse than re-running, so the
    cache errs toward re-execution. Hidden ``.acb*`` bookkeeping files and the
    built zip are excluded so the cache does not invalidate itself.
    """
    bundle_dir = Path(bundle_dir)
    h = hashlib.sha256()
    for rel, p in _iter_hashable_files(bundle_dir):
        h.update(str(rel).replace(os.sep, "/").encode("utf-8"))
        h.update(b"\0")
        try:
            h.update(hashlib.sha256(p.read_bytes()).digest())
        except OSError:
            h.update(b"<unreadable>")
        h.update(b"\0")
    return h.hexdigest()


def _execution_cache_path(bundle_dir: Path) -> Path:
    return bundle_dir.parent / _CACHE_FILENAME


def read_execution_cache(bundle_dir: str | Path) -> dict[str, Any]:
    p = _execution_cache_path(Path(bundle_dir))
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def cached_run(bundle_dir: str | Path, kind: str,
               current_hash: str | None = None) -> dict[str, Any] | None:
    """Return a usable cache entry for ``kind`` iff its hash still matches and
    the recorded run was ``ok``; else None."""
    bundle_dir = Path(bundle_dir)
    entry = (read_execution_cache(bundle_dir).get("entries") or {}).get(kind)
    if not isinstance(entry, dict) or not entry.get("ok"):
        return None
    if current_hash is None:
        current_hash = bundle_content_hash(bundle_dir)
    return entry if entry.get("input_hash") == current_hash else None


def write_execution_cache_entry(bundle_dir: str | Path, kind: str,
                                entry: dict[str, Any]) -> None:
    """Upsert one run record into the bundle-adjacent cache. Best-effort:
    a write failure (read-only tempdir, etc.) is swallowed — the cache is an
    optimization, never a correctness dependency."""
    bundle_dir = Path(bundle_dir)
    data = read_execution_cache(bundle_dir)
    entries = data.setdefault("entries", {})
    entries[kind] = entry
    try:
        _execution_cache_path(bundle_dir).write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass


def _utc_now_iso() -> str:
    return (datetime.now(tz=timezone.utc).replace(microsecond=0)
            .isoformat().replace("+00:00", "Z"))


def _phase_label_for(bundle_dir: Path) -> str:
    """Best-effort name of the phase/run that produced a cache entry, derived
    from the active run dir (e.g. ``phase2_build`` → ``build``)."""
    run = current_run()
    name = run.name if run is not None else ""
    for tag in ("build", "plan", "validate"):
        if tag in name:
            return tag
    return name or "run"


def _bundle_data_inventory(bundle_dir: Path) -> dict[str, Any]:
    """A compact record of which data a run consumed, for the report's
    'using which data' column."""
    def _list(sub: str) -> list[str]:
        d = bundle_dir / sub
        return sorted(p.name for p in d.iterdir() if p.is_file()) if d.is_dir() else []
    return {
        "reference_data": _list("reference_data"),
        "input_data_present": (bundle_dir / "input_data").is_dir(),
        "public_data_present": (bundle_dir / "public_data").is_dir(),
    }


# ---------------------------------------------------------------------------
# Image preparation (the Docker-only replacement for per-run conda envs)
# ---------------------------------------------------------------------------

def _docker_image_present(image: str) -> bool:
    """True if the image already exists in the local Docker image store."""
    res = _bash(f"docker image inspect {shlex.quote(image)}", timeout=60)
    return res["exit_code"] == 0


def prepare_run_env(slug: str, force_recreate: bool = False,
                    root_dir: str | None = None) -> dict[str, Any]:
    """Ensure the bundle's docker_image is available locally before runs.

    The Docker-only replacement for the old per-run conda env: there is no
    environment to clone, because programs run inside the bundle's declared
    image exactly as on the platform. This checks that the image is present in
    the local Docker store and, if not, attempts a single ``docker pull``.

    The returned ``env_name`` field carries the image name for backward
    compatibility with callers that thread it into subsequent run calls (where
    it is ignored — the run resolves the image from competition.yaml itself).

    Returns ``{ok, image, env_name, present_locally, pulled, logs_dir, note,
    error}``.
    """
    resolved = resolve_execution_engine("auto")
    if resolved["error"]:
        return {"ok": False, "error": resolved["error"]}

    image = bundle_docker_image(slug, root_dir)
    logs = _run_logs_dir(slug, root_dir) / "env"
    logs.mkdir(parents=True, exist_ok=True)

    present = _docker_image_present(image)
    pulled = False
    if not present:
        pull = _bash(f"docker pull {shlex.quote(image)}",
                     stdout=logs / "pull.stdout", stderr=logs / "pull.stderr",
                     timeout=1800)
        present = pull["exit_code"] == 0
        pulled = present

    if not present:
        return {
            "ok": False, "image": image, "env_name": image,
            "present_locally": False, "pulled": False, "logs_dir": str(logs),
            "note": (f"docker_image {image!r} is not in the local image store and "
                     "could not be pulled. Build the autocodabench base images "
                     "locally (docker/build_and_push.sh, no --push needed), or set "
                     "the bundle's docker_image / AUTOCODABENCH_DOCKER_IMAGE to an "
                     "image that is available. See docker/README.md."),
            "error": f"docker image {image!r} unavailable (not local; pull failed)",
        }
    return {
        "ok": True, "image": image, "env_name": image,
        "present_locally": not pulled, "pulled": pulled, "logs_dir": str(logs),
        "note": (f"pulled {image}" if pulled else f"{image} already present locally"),
        "error": None,
    }


def install_env_extras(env_name: str, packages: list[str]) -> dict[str, Any]:
    """Adding packages at run time is not supported under Docker-only execution.

    The Codabench worker runs programs inside the bundle's ``docker_image`` and
    installs nothing; a locally pip-installed package would therefore make the
    bundle pass here but fail on the platform. The faithful fix is to declare a
    ``docker_image`` that already ships the dependency (a richer public image,
    or an autocodabench base image extended and rebuilt — see docker/README.md).
    Returns an error with that guidance rather than silently diverging from the
    platform.
    """
    return {
        "ok": False,
        "packages": packages or [],
        "error": ("install_env_extras is unavailable: autocodabench runs "
                  "exclusively through Docker, and the Codabench worker installs "
                  "nothing into the image. To add " + (", ".join(packages) if packages else "a dependency")
                  + ", set the bundle's docker_image to one that already ships it "
                  "(or extend an autocodabench base image and rebuild). "
                  "See docker/README.md."),
        "note": "no-op under Docker-only execution; change docker_image instead",
    }


# ---------------------------------------------------------------------------
# Subprocess scoring/ingestion runner
# ---------------------------------------------------------------------------

def _read_scores(output_dir: Path) -> dict[str, Any]:
    """Parse `scores.json` or `scores.txt` from the scoring output dir."""
    j = output_dir / "scores.json"
    if j.is_file():
        try:
            return {"format": "json", "scores": json.loads(j.read_text(encoding="utf-8"))}
        except json.JSONDecodeError as e:
            return {"format": "json", "scores": None,
                    "parse_error": f"scores.json malformed: {e}"}
    t = output_dir / "scores.txt"
    if t.is_file():
        scores: dict[str, Any] = {}
        for line in t.read_text(encoding="utf-8").splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                try:
                    scores[k.strip()] = float(v.strip())
                except ValueError:
                    scores[k.strip()] = v.strip()
        return {"format": "txt", "scores": scores}
    return {"format": None, "scores": None,
            "parse_error": "neither scores.json nor scores.txt found"}


def _run_submission_in_sandbox(
    slug: str, env_name: str, submission_dir: Path,
    label: str,
    extra_env: dict[str, str] | None = None,
    engine: str = "auto",
    root_dir: str | None = None,
    cache_kind: str | None = None,
) -> dict[str, Any]:
    """Stage a sandbox, run ingestion (if defined) + scoring, parse scores.

    `label` is used to scope the run-logs dir (e.g. "baseline", "sub_1.attempt_1").
    Programs execute inside the bundle's declared `docker_image`, exactly as the
    Codabench worker runs them. `engine` accepts "auto" or "docker" (both
    require Docker); `env_name` is ignored. The result records the engine and
    image used.

    Layout inside the sandbox (mounted under /app in the container):
      sandbox/
        program/                 # scoring_program (and ingestion_program if present)
        input/
          res/                   # ingestion output OR submission's prediction file(s)
          ref/                   # reference_data (held-out labels)
        output/                  # scoring writes scores.json here
        submission/              # the submission code being run
    """
    bundle_dir = resolve_bundle_dir(slug, root_dir)
    if not bundle_dir.exists():
        return {"ok": False, "error": f"bundle dir not found: {bundle_dir}"}
    if not submission_dir.exists():
        return {"ok": False, "error": f"submission dir not found: {submission_dir}"}

    resolved = resolve_execution_engine(engine)
    if resolved["error"]:
        return {"ok": False, "error": resolved["error"]}
    eng: str = resolved["engine"]
    engine_note = resolved["note"]
    image = bundle_docker_image(slug, root_dir)

    def _run_stage(program_subdir: str, raw_cmd: str,
                   out: Path, err: Path) -> dict[str, Any]:
        """Run one program stage inside the bundle's docker_image,
        worker-faithfully (program dir at /app/program, working dir there)."""
        full = _docker_run(image, sandbox, program_subdir, raw_cmd,
                           extra_env, has_ingestion)
        return _bash(full, cwd=None, stdout=out, stderr=err, env=None)

    logs = _run_logs_dir(slug, root_dir) / label
    logs.mkdir(parents=True, exist_ok=True)
    sandbox = logs / "sandbox"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True)

    # Stage the bundle pieces.
    (sandbox / "program").mkdir()
    (sandbox / "input" / "res").mkdir(parents=True)
    (sandbox / "input" / "ref").mkdir(parents=True)
    (sandbox / "output").mkdir()

    scoring_src = bundle_dir / "scoring_program"
    if scoring_src.exists():
        shutil.copytree(scoring_src, sandbox / "program" / "scoring_program")
    ingestion_src = bundle_dir / "ingestion_program"
    # An ingestion program "exists" only if its directory holds runnable
    # content. `init_bundle` creates an empty `ingestion_program/` skeleton
    # for every bundle, so testing the directory alone misclassifies a
    # λ-style (prediction-file) competition as γ-style and then fails on a
    # nonexistent ingestion script. Require an actual file.
    has_ingestion = ingestion_src.is_dir() and any(ingestion_src.iterdir())
    if has_ingestion:
        shutil.copytree(ingestion_src, sandbox / "program" / "ingestion_program")

    ref_src = bundle_dir / "reference_data"
    if ref_src.exists():
        for p in ref_src.iterdir():
            if p.is_file():
                shutil.copy2(p, sandbox / "input" / "ref" / p.name)
            else:
                shutil.copytree(p, sandbox / "input" / "ref" / p.name)
    input_src = bundle_dir / "input_data"
    if input_src.exists():
        shutil.copytree(input_src, sandbox / "input_data")
    public_src = bundle_dir / "public_data"
    if public_src.exists():
        shutil.copytree(public_src, sandbox / "public_data")
    sample_src = bundle_dir / "sample_data"
    if sample_src.exists():
        shutil.copytree(sample_src, sandbox / "sample_data")

    shutil.copytree(submission_dir, sandbox / "submission")

    # --- Stage 1: ingestion (γ-style) or copy predictions (λ-style) ---
    if has_ingestion:
        # ingestion_program/metadata.yaml has a `command:` we honor; the
        # fallback uses the canonical worker tokens so it resolves under
        # either engine.
        meta_path = sandbox / "program" / "ingestion_program" / "metadata.yaml"
        ing_cmd = _read_command_from_metadata(meta_path,
                    fallback="python3 $program/ingestion.py "
                             "$input_data $submission $input/res")
        ing = _run_stage("ingestion_program", ing_cmd,
                         logs / "ingestion_stdout.txt", logs / "ingestion_stderr.txt")
        if ing["exit_code"] != 0 or ing["timed_out"]:
            return {
                "ok": False, "stage": "ingestion",
                "engine": eng, "docker_image": image, "engine_note": engine_note,
                "ingestion": ing,
                "scoring": None,
                "score": None, "scores": None,
                "sandbox_dir": str(sandbox), "logs_dir": str(logs),
                "error": f"ingestion exit {ing['exit_code']} (timeout={ing['timed_out']})",
            }
    else:
        # λ-style: submission must contain predictions.* files
        for p in (sandbox / "submission").iterdir():
            if p.is_file() and p.name.startswith("predictions"):
                shutil.copy2(p, sandbox / "input" / "res" / p.name)
        # Also accept a `res/` subdir
        sub_res = sandbox / "submission" / "res"
        if sub_res.is_dir():
            for p in sub_res.iterdir():
                shutil.copy2(p, sandbox / "input" / "res" / p.name)

    # --- Stage 2: scoring ---
    meta_path = sandbox / "program" / "scoring_program" / "metadata.yaml"
    score_cmd = _read_command_from_metadata(meta_path,
                fallback="python3 $program/score.py $input $output")
    score_run = _run_stage("scoring_program", score_cmd,
                           logs / "scoring_stdout.txt", logs / "scoring_stderr.txt")

    scores_blob = _read_scores(sandbox / "output")

    ok = (score_run["exit_code"] == 0 and not score_run["timed_out"]
          and scores_blob.get("scores") is not None)
    total_duration = round(
        (ing["duration_s"] if has_ingestion else 0.0) + score_run["duration_s"], 2)

    if ok and cache_kind:
        write_execution_cache_entry(bundle_dir, cache_kind, {
            "kind": cache_kind, "slug": slug, "ok": True,
            "input_hash": bundle_content_hash(bundle_dir),
            "phase": _phase_label_for(bundle_dir),
            "docker_image": image,
            "duration_s": total_duration,
            "stage": "scoring",
            "scores": scores_blob.get("scores"),
            "scores_format": scores_blob.get("format"),
            "data": _bundle_data_inventory(bundle_dir),
            "logs_dir": str(logs),
            "timestamp": _utc_now_iso(),
        })

    return {
        "ok": ok,
        "stage": "scoring",
        "engine": eng, "docker_image": image, "engine_note": engine_note,
        "ingestion": ing if has_ingestion else None,
        "scoring": score_run,
        "scores": scores_blob.get("scores"),
        "scores_format": scores_blob.get("format"),
        "scores_parse_error": scores_blob.get("parse_error"),
        "duration_s": total_duration,
        "data": _bundle_data_inventory(bundle_dir),
        "sandbox_dir": str(sandbox),
        "logs_dir": str(logs),
        "error": None if ok
                 else (f"scoring exit {score_run['exit_code']}"
                       + (f" (timeout)" if score_run['timed_out'] else "")
                       + (f"; {scores_blob.get('parse_error')}" if scores_blob.get('parse_error') else "")),
    }


def _read_command_from_metadata(meta_path: Path, fallback: str) -> str:
    """Read `command:` from a Codabench metadata.yaml. Cheap parse — no PyYAML dep."""
    if not meta_path.is_file():
        return fallback
    for line in meta_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("command:"):
            cmd = s.split(":", 1)[1].strip()
            cmd = cmd.strip('"').strip("'")
            return cmd or fallback
    return fallback


def run_baseline_submission(slug: str, env_name: str = "",
                            subdir: str = "solution_baseline",
                            extra_env: dict[str, str] | None = None,
                            engine: str = "auto",
                            root_dir: str | None = None,
                            ) -> dict[str, Any]:
    """Run the bundle's own baseline through its scoring pipeline.

    The bundle ships `solutions/<subdir>/` as a working example. It runs
    inside the bundle's declared `docker_image` exactly as Codabench's worker
    would run a participant submission, so a clean run is evidence of platform
    behavior. Requires a Docker daemon; `env_name` is ignored (retained for
    signature compatibility).

    `extra_env` (optional) overrides per-subprocess env vars at process start
    time (passed as `-e` flags into the container). Use sparingly — the docker
    engine deliberately keeps the image's own defaults, as the platform does.
    """
    bundle_dir = resolve_bundle_dir(slug, root_dir)
    candidates = [
        bundle_dir / "solutions" / subdir,
        bundle_dir / "solutions" / "sample_code_submission",
        bundle_dir / "solutions" / "solution1",
        bundle_dir / "solution" / "sample_code_submission",
    ]
    sub_dir = next((c for c in candidates if c.is_dir()), None)
    if sub_dir is None:
        return {"ok": False,
                "error": f"no baseline submission found under bundle's solutions/ "
                         f"(checked: {[str(c) for c in candidates]})"}
    log_event("run_baseline_started", slug=slug, env_name=env_name,
              submission=str(sub_dir), engine=engine)
    res = _run_submission_in_sandbox(slug, env_name, sub_dir, label="baseline",
                                     extra_env=extra_env, engine=engine,
                                     root_dir=root_dir, cache_kind="baseline")
    log_event("run_baseline_finished", slug=slug, ok=res["ok"],
              engine=res.get("engine"), error=res.get("error"),
              score=res.get("scores"))
    return res


def run_user_submission(slug: str, env_name: str = "", submission_dir: str = "",
                        label: str = "submission",
                        extra_env: dict[str, str] | None = None,
                        engine: str = "auto",
                        root_dir: str | None = None,
                        ) -> dict[str, Any]:
    """Run an arbitrary submission directory through the bundle's scoring pipeline.

    `label` namespaces this run's logs (e.g. "sub_1.attempt_2"). Used by the
    reformat-and-run skill against a ground-truth submission after it has been
    adapted to the bundle's interface. Runs inside the bundle's `docker_image`,
    as `run_baseline_submission` does; `env_name` is ignored.

    `extra_env` (optional) overrides per-subprocess env vars at process
    start time.
    """
    sub_dir = Path(submission_dir).resolve()
    log_event("run_user_started", slug=slug, env_name=env_name,
              submission=str(sub_dir), label=label, engine=engine)
    res = _run_submission_in_sandbox(slug, env_name, sub_dir, label=label,
                                     extra_env=extra_env, engine=engine,
                                     root_dir=root_dir)
    log_event("run_user_finished", slug=slug, label=label, ok=res["ok"],
              engine=res.get("engine"), error=res.get("error"),
              score=res.get("scores"))
    return res


# ---------------------------------------------------------------------------
# Starting-kit notebook runner
# ---------------------------------------------------------------------------

def run_starting_kit(slug: str, env_name: str = "",
                     notebook_path: str | None = None,
                     extra_env: dict[str, str] | None = None,
                     root_dir: str | None = None,
                     ) -> dict[str, Any]:
    """Execute the bundle's starting-kit notebook end-to-end inside Docker.

    Looks for `README.ipynb` or `starting_kit/*.ipynb` at the bundle root and
    runs it with `jupyter nbconvert --to notebook --execute --inplace` *inside
    the bundle's docker_image* (which ships the notebook toolchain — see the
    autocodabench base images). nbconvert stops on the first cell error and
    exits nonzero, and writes the executed notebook (with outputs) back in
    place. The bundle directory is mounted at `/app` and
    is the working directory, so the kernel's CWD is the bundle root and the
    notebook's relative paths (e.g. `input_data/...`) resolve correctly. The
    executed notebook is written back to `<run>/run_logs/.../executed.ipynb`
    so a reviewer can scroll through cell outputs. `env_name` is ignored
    (retained for signature compatibility).
    """
    resolved = resolve_execution_engine("auto")
    if resolved["error"]:
        return {"ok": False, "error": resolved["error"]}

    bundle_dir = resolve_bundle_dir(slug, root_dir)
    if notebook_path:
        nb = Path(notebook_path).resolve()
    else:
        nb_candidates: list[Path] = [bundle_dir / "README.ipynb"]
        kit_dir = bundle_dir / "starting_kit"
        if kit_dir.is_dir():
            nb_candidates.extend(sorted(kit_dir.glob("*.ipynb")))
        nb = next((c for c in nb_candidates if c.is_file()), None)
    if nb is None or not nb.is_file():
        return {"ok": False,
                "error": "no starting-kit notebook found "
                         "(looked for README.ipynb / starting_kit/*.ipynb)"}

    logs = _run_logs_dir(slug, root_dir) / "starting_kit"
    logs.mkdir(parents=True, exist_ok=True)
    executed = logs / "executed.ipynb"

    image = bundle_docker_image(slug, root_dir)
    # Execute a temporary copy placed at the bundle root so nbclient's working
    # directory (the notebook's own directory) is the bundle root — then move
    # the executed copy into the logs dir and clean up the bundle.
    tmp_name = ".acb_executed.ipynb"
    tmp_in_bundle = bundle_dir / tmp_name
    shutil.copy2(nb, tmp_in_bundle)

    env = {"PYTHONUNBUFFERED": "1", **(extra_env or {})}
    env_flags = " ".join(f"-e {shlex.quote(f'{k}={v}')}" for k, v in env.items())
    # `nbconvert --execute --inplace` runs every cell, fails nonzero on the
    # first error, and writes outputs back. `--ExecutePreprocessor.timeout=-1`
    # disables the (default 30 s) per-cell limit so a legitimately long cell is
    # bounded by the outer wall-clock timeout instead of being killed mid-run.
    inner = (f"jupyter nbconvert --to notebook --execute --inplace "
             f"--ExecutePreprocessor.timeout=-1 /app/{shlex.quote(tmp_name)}")
    cmd = (f"docker run --rm {env_flags} "
           f"-v {shlex.quote(str(bundle_dir))}:/app:rw -w /app "
           f"{shlex.quote(image)} bash -c {shlex.quote(inner)}")
    log_event("run_starting_kit_started", slug=slug, notebook=str(nb), image=image)
    res = _bash(cmd, cwd=None,
                stdout=logs / "stdout.txt", stderr=logs / "stderr.txt",
                timeout=3600)
    # Recover the executed notebook into the logs dir; remove the bundle temp.
    try:
        if tmp_in_bundle.is_file():
            shutil.move(str(tmp_in_bundle), str(executed))
        else:
            shutil.copy2(nb, executed)
    except OSError:
        pass
    finally:
        if tmp_in_bundle.exists():
            try:
                tmp_in_bundle.unlink()
            except OSError:
                pass

    # Count cells executed by re-reading the notebook (best-effort, no nbformat dep)
    cells_executed = None
    try:
        nb_json = json.loads(executed.read_text(encoding="utf-8"))
        cells = nb_json.get("cells", [])
        cells_executed = sum(1 for c in cells
                             if c.get("cell_type") == "code"
                             and c.get("execution_count") is not None)
    except Exception:
        pass

    ok = res["exit_code"] == 0 and not res["timed_out"]
    if ok:
        write_execution_cache_entry(bundle_dir, "starting_kit", {
            "kind": "starting_kit", "slug": slug, "ok": True,
            "input_hash": bundle_content_hash(bundle_dir),
            "phase": _phase_label_for(bundle_dir),
            "docker_image": image,
            "duration_s": res["duration_s"],
            "cells_executed": cells_executed,
            "notebook_source": str(nb),
            "data": _bundle_data_inventory(bundle_dir),
            "logs_dir": str(logs),
            "timestamp": _utc_now_iso(),
        })
    log_event("run_starting_kit_finished", slug=slug, ok=ok,
              cells_executed=cells_executed, error=None if ok else res["stderr_tail"][:200])
    return {
        "ok": ok,
        "notebook_source": str(nb),
        "executed_notebook": str(executed),
        "cells_executed": cells_executed,
        "exit_code": res["exit_code"],
        "duration_s": res["duration_s"],
        "timed_out": res["timed_out"],
        "stdout_tail": res["stdout_tail"],
        "stderr_tail": res["stderr_tail"],
        "stdout_path": res["stdout_path"],
        "stderr_path": res["stderr_path"],
        "logs_dir": str(logs),
        "error": None if ok else
                 ("notebook timed out" if res["timed_out"]
                  else f"nbconvert execute exit {res['exit_code']}: {res['stderr_tail'][:200]}"),
    }


# ---------------------------------------------------------------------------
# Env teardown
# ---------------------------------------------------------------------------

def remove_run_env(env_name: str = "") -> dict[str, Any]:
    """No-op under Docker-only execution: there is no per-run environment to
    tear down. Containers run with ``--rm`` and remove themselves, and base
    images are shared, not per-run. Retained so finalize steps that call it
    keep working. ``env_name`` is ignored."""
    return {"ok": True, "env_name": env_name,
            "note": "no per-run environment under Docker-only execution "
                    "(containers run --rm; images are shared)"}
