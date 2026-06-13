"""Phase prompts, loaded from the skill files shipped inside the package.

Prompts live in ``autocodabench/skills/<name>/SKILL.md`` rather than as
Python strings because they are the versioned behavioral contract for each
phase: a document diffs, reviews, and audits like code, whereas a string
buried in a module does not (each skill's sibling README records its
provenance). This module loads a skill body (frontmatter stripped) and
appends the runtime footer for the surface on which it runs — one loading
mechanism shared by the pipeline and the web UI, so the contracts cannot
drift between surfaces.
"""
from __future__ import annotations

from importlib import resources
from pathlib import Path

_SKILLS_PACKAGE = "autocodabench.skills"


def skills_dir() -> Path:
    """Filesystem path of the packaged skills (works for wheel + editable)."""
    return Path(str(resources.files(_SKILLS_PACKAGE)))


def load_skill(name: str) -> str:
    """Return a skill's body without its YAML frontmatter."""
    path = skills_dir() / name / "SKILL.md"
    if not path.is_file():
        raise FileNotFoundError(f"skill not found: {path}")
    body = path.read_text(encoding="utf-8")
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            body = body[end + 4:].lstrip()
    return body


_NON_INTERACTIVE_PLAN_FOOTER = """

---

## Runtime note (non-interactive CLI)

You are running headless via the `autocodabench create` command line — there
is NO web interface in this session. There is no "workspace panel", no "phase
bar", no "Advance to Phase 2" button, and nothing for the user to click. Do
NOT mention any of those, and do not tell the user to click, press, or open
anything. The plan file is written to disk; refer to it only by its path
(`specs/implementation_plan.md`).

There is no user to ask. Do NOT ask scoping questions. Make reasonable,
conservative assumptions for every unresolved design dimension, state each
assumption explicitly in the plan (so a human can revise it later), and
produce the COMPLETE implementation plan in this single session. Save it with
`autocodabench_snapshot_spec(filename="implementation_plan.md", body=...)`
before finishing.

For the §3 hand-off message, the closing call-to-action is simply a plain
sentence such as: "Phase 2 — Competition Creation will now run automatically
and build the bundle from this plan." Then stop.
"""

_BUILD_FOOTER = """

---

## Runtime note (non-interactive CLI)

You are running headless via the `autocodabench create` command line — there
is NO web interface. Do not mention a workspace panel, phase bar, download
drawer, or Publish form, and do not tell the user to click anything; refer to
artifacts by their file paths. The locked plan is at
`<run>/specs/implementation_plan.md` — call `autocodabench_current_run`,
read the plan with the Read tool, then execute this skill end-to-end
(generate bundle files → validate → zip) without waiting for instructions.
"""


def plan_system_prompt() -> str:
    return load_skill("plan") + _NON_INTERACTIVE_PLAN_FOOTER


def build_system_prompt() -> str:
    return load_skill("autocodabench-implement") + _BUILD_FOOTER
