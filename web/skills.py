"""Skill loading utilities for the AutoCodabench web UI.

Reads SKILL.md files from the packaged skills directory and strips YAML
frontmatter, returning only the body text used as the agent system prompt.
"""
from __future__ import annotations

from pathlib import Path

from autocodabench.agent.prompts import skills_dir as _acb_skills_dir

_SKILLS_ROOT = _acb_skills_dir()


def _resolve_skill(*candidates: str) -> Path:
    """Return the path to the first existing SKILL.md among the candidates."""
    for name in candidates:
        p = _SKILLS_ROOT / name / "SKILL.md"
        if p.exists():
            return p
    return _SKILLS_ROOT / candidates[0] / "SKILL.md"


def load_skill_body(*candidates: str) -> str:
    """Load a skill's body text with YAML frontmatter stripped.

    Accepts one or more candidate skill directory names and returns the body
    of the first one found. Returns an empty string if none exist.
    """
    path = _resolve_skill(*candidates)
    if not path.exists():
        return ""
    body = path.read_text(encoding="utf-8")
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            body = body[end + 4:].lstrip()
    return body
