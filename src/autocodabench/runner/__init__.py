"""Runtime counterpart of core: scoring/ingestion/notebook execution.

Docker-only: programs (and the starting-kit notebook) run inside the bundle's
declared ``docker_image`` exactly as the Codabench worker runs them. A missing
Docker daemon is a hard error; the former conda engine has been removed.
"""
from .execution import (
    bundle_content_hash,
    bundle_docker_image,
    cached_run,
    docker_daemon_status,
    docker_image_overridden,
    docker_preflight,
    emulation_allowed,
    emulation_guidance,
    image_arch_status,
    install_env_extras,
    prepare_run_env,
    read_execution_cache,
    remove_run_env,
    resolve_execution_engine,
    run_baseline_submission,
    run_starting_kit,
    run_user_submission,
    write_execution_cache_entry,
)

__all__ = [
    "bundle_content_hash",
    "bundle_docker_image",
    "cached_run",
    "docker_daemon_status",
    "docker_image_overridden",
    "docker_preflight",
    "emulation_allowed",
    "emulation_guidance",
    "image_arch_status",
    "install_env_extras",
    "prepare_run_env",
    "read_execution_cache",
    "remove_run_env",
    "resolve_execution_engine",
    "run_baseline_submission",
    "run_starting_kit",
    "run_user_submission",
    "write_execution_cache_entry",
]
