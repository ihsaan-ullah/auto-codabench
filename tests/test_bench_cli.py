"""Keyless tests for the benchmark CLI guard (force an explicit Claude model)."""
import pytest

from autocodabench.bench.cli import require_explicit_model


@pytest.mark.parametrize("spec", [None, "claude"])
def test_bare_claude_is_rejected(spec):
    with pytest.raises(SystemExit) as e:
        require_explicit_model(spec, None)
    assert "exact Claude model" in str(e.value)


def test_claude_with_inline_model_ok():
    require_explicit_model("claude:claude-opus-4-8", None)   # no raise


def test_claude_with_model_flag_ok():
    require_explicit_model("claude", "claude-opus-4-8")      # no raise


@pytest.mark.parametrize("spec", [
    "ollama:llama3.1", "openai:gpt-4o", "http://gpu:8000/v1#Qwen2.5-72B"])
def test_non_claude_specs_pass(spec):
    require_explicit_model(spec, None)                       # already name a model
