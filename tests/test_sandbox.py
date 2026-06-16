"""The filesystem sandbox: a phase may only read what it was given."""
from pathlib import Path

from autocodabench.backends.sandbox import FsSandbox


def _sb(tmp_path):
    allowed = tmp_path / "run"
    allowed.mkdir()
    return FsSandbox([str(allowed)]), allowed


def test_mcp_tools_always_allowed(tmp_path):
    sb, _ = _sb(tmp_path)
    assert sb.check("mcp__autocodabench__autocodabench_init_bundle",
                    {"slug": "x"}) is None


def test_shell_and_network_tools_denied(tmp_path):
    sb, allowed = _sb(tmp_path)
    # Even a command that names an in-root path is denied: Bash is an escape.
    assert sb.check("Bash", {"command": f"cat {allowed}/x"}) is not None
    assert sb.check("WebFetch", {"url": "https://example.com"}) is not None
    assert sb.check("Task", {"prompt": "go"}) is not None


def test_read_inside_root_allowed(tmp_path):
    sb, allowed = _sb(tmp_path)
    assert sb.check("Read", {"file_path": str(allowed / "specs" / "plan.md")}) is None


def test_read_outside_root_denied(tmp_path):
    sb, _ = _sb(tmp_path)
    outside = tmp_path / "ground_truth" / "bundle" / "competition.yaml"
    assert sb.check("Read", {"file_path": str(outside)}) is not None


def test_glob_without_path_denied(tmp_path):
    sb, allowed = _sb(tmp_path)
    # Path-less search would default to cwd and walk the whole tree.
    assert sb.check("Glob", {"pattern": "**/*.csv"}) is not None
    # …but an explicit in-root path is fine.
    assert sb.check("Glob", {"path": str(allowed), "pattern": "**/*.csv"}) is None


def test_local_tool_names_and_path_arg(tmp_path):
    """The OpenAI-compat backend's canonical tool names use a `path` arg."""
    sb, allowed = _sb(tmp_path)
    assert sb.check("read_file", {"path": str(allowed / "data.csv")}) is None
    assert sb.check("read_file", {"path": str(tmp_path / "elsewhere.csv")}) is not None


def test_data_root_extends_access(tmp_path):
    run = tmp_path / "run"; run.mkdir()
    data = tmp_path / "input" / "sample_data"; data.mkdir(parents=True)
    sb = FsSandbox([str(run), str(data)])
    assert sb.check("Read", {"file_path": str(data / "labels0.csv")}) is None
    assert sb.check("Read", {"file_path": str(tmp_path / "secret.csv")}) is not None
