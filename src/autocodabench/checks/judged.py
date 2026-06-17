"""Judged checks — an LLM grades a rubric, through the same AgentBackend seam.

Judged verdicts are *advisory by construction*: they emit FINDINGs, never
PASS/FAIL gates. "Valid" is defined by executable checks, not by a model's
self-assessment; what a judge buys is coverage of semantic properties code
cannot see (do the pages contradict the config? is the metric direction
documented?).

Each judged check builds one rubric prompt, runs it as a tool-less backend
session, and parses a strict-JSON verdict. Unparseable output degrades to a
SKIPPED result — never to a silent pass.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..backends.base import AgentBackend, AgentTask
from .base import (
    Check,
    CheckContext,
    CheckResult,
    Dimension,
    Severity,
    Status,
    Tier,
    register,
)

_MAX_PAGE_CHARS = 16_000
_MAX_YAML_CHARS = 8_000


class JudgedCheck(Check):
    tier = Tier.JUDGED

    def build_prompt(self, ctx: CheckContext) -> str:  # pragma: no cover
        raise NotImplementedError

    async def run_judged(self, ctx: CheckContext, backend: AgentBackend) -> list[CheckResult]:
        missing = self.missing_facts(ctx)
        if missing:
            return [self.skipped(f"requires facts not provided: {', '.join(missing)}")]
        prompt = self.build_prompt(ctx)
        result = await backend.run(AgentTask(prompt=prompt, allowed_tools=[]))
        if not result.ok:
            return [self.skipped(f"judge run failed: {result.error or result.status}")]
        return self.parse_verdict(result.final_text)

    def parse_verdict(self, text: str) -> list[CheckResult]:
        blob = _extract_json(text)
        if blob is None or "findings" not in blob:
            return [self.skipped("judge returned no parseable JSON verdict")]
        findings = blob.get("findings") or []
        if not findings:
            return [self.passed("judge found no issues (advisory)")]
        out: list[CheckResult] = []
        for f in findings:
            if not isinstance(f, dict):
                continue
            out.append(self.finding(str(f.get("message", "")),
                                    where=str(f.get("where")) if f.get("where") else None))
        return out or [self.passed("judge found no issues (advisory)")]


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of the model's reply (fenced or bare)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    brace = text.find("{")
    if brace != -1:
        candidates.append(text[brace: text.rfind("}") + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    return None


def _bundle_texts(ctx: CheckContext) -> tuple[str, str]:
    yaml_text = ""
    yaml_path = ctx.bundle_dir / "competition.yaml"
    if yaml_path.is_file():
        yaml_text = yaml_path.read_text(encoding="utf-8", errors="replace")[:_MAX_YAML_CHARS]
    pages = []
    pages_dir = ctx.bundle_dir / "pages"
    if pages_dir.is_dir():
        for p in sorted(pages_dir.glob("*.md")):
            pages.append(f"### {p.name}\n\n" + p.read_text(encoding="utf-8", errors="replace"))
    # Some bundles ship page markdown at the bundle root (no pages/ dir).
    if not pages:
        for p in sorted(ctx.bundle_dir.glob("*.md")):
            pages.append(f"### {p.name}\n\n" + p.read_text(encoding="utf-8", errors="replace"))
    return yaml_text, "\n\n".join(pages)[:_MAX_PAGE_CHARS]


_MAX_KIT_CHARS = 6_000


def _starting_kit_text(ctx: CheckContext) -> str:
    """A compact listing + small text of the starting kit, so a judge can assess
    whether it documents the submission interface a participant must implement."""
    kit = ctx.bundle_dir / "starting_kit"
    if not kit.is_dir():
        return "(no starting_kit/ directory)"
    parts: list[str] = []
    files = sorted(p for p in kit.rglob("*") if p.is_file())
    parts.append("files: " + ", ".join(str(p.relative_to(kit)) for p in files[:40]))
    for p in files:
        if p.suffix.lower() in (".md", ".txt", ".py") and p.stat().st_size < 4000:
            parts.append(f"\n### {p.relative_to(kit)}\n"
                         + p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)[:_MAX_KIT_CHARS]


@register
class DocsConfigConsistency(JudgedCheck):
    """Do the participant-facing pages contradict the machine config?

    The classic failure: pages say "5 submissions per day", the YAML enforces
    10; pages say higher-is-better, the leaderboard sorts ascending. These
    ship silently and surface as participant disputes.
    """

    id = "judged-docs-config-consistency"
    how = "An LLM compares the pages against competition.yaml and reports contradictions."
    title = "Pages ↔ competition.yaml consistency (LLM-judged, advisory)"
    dimension = Dimension.DOCUMENTATION
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 11, Ch. 13)"

    def build_prompt(self, ctx: CheckContext) -> str:
        yaml_text, pages_text = _bundle_texts(ctx)
        return f"""You are auditing a Codabench competition bundle before launch.

Compare the machine configuration (competition.yaml) against the
participant-facing pages. Report every CONTRADICTION between what the pages
promise and what the config enforces. Look specifically at:

- phase names, dates, and durations
- submission limits (per-day and total)
- metric names and ranking direction (higher- vs lower-is-better vs the
  leaderboard `sorting`)
- submission format the pages describe vs what the scoring program implies
- prizes, rules, or data access promised in pages but absent from config

Only report contradictions you can quote from both sides. Do not report
style issues or missing information — contradictions only.

Respond with ONLY a JSON object, no other text:
{{"findings": [{{"where": "<page or yaml locator>", "message": "<contradiction, quoting both sides>"}}]}}

If there are no contradictions: {{"findings": []}}

--- competition.yaml ---
{yaml_text}

--- pages ---
{pages_text}
"""


# A plain string (not an f-string), so single braces are literal: the embedding
# build_prompt f-strings insert this verbatim via {_JSON_FOOTER}.
#
# The leading calibration matters: these are advisory completeness/clarity
# rubrics, and without it the judge flags *any* concise page as "incomplete" —
# firing on minimal-but-valid bundles (a 100% false-positive rate on the demo).
# The instruction biases toward silence so a finding signals a real, material
# gap rather than a wish for more prose.
_JSON_FOOTER = (
    'Calibrate carefully. A concise bundle that covers the essentials must pass '
    'with an EMPTY findings list — do not flag brevity, polish, or "could say '
    'more", and a small or demo competition need not spell out every clause. '
    'BUT a section that is essentially empty, gutted, or missing the core '
    'information a participant actually needs IS a material gap and must be '
    'reported. Distinguish "concise but adequate" (pass) from "absent or '
    'placeholder" (report).\n\n'
    'Respond with ONLY a JSON object, no other text:\n'
    '{"findings": [{"where": "<page/section locator>", "message": "<the material '
    'gap, specific and actionable>"}]}\n'
    'If nothing is materially missing: {"findings": []}\n'
)


@register
class RulesCompleteness(JudgedCheck):
    """Do the participant-facing rules/terms cover the launch-critical clauses?

    A pre-launch competition whose rules omit eligibility, the tie-break, prize
    governance, submission IP/licensing, or an anti-fraud policy invites disputes
    that have no documented resolution. An LLM can read the terms and report which
    expected clauses are absent — a deterministic keyword scan would be brittle.
    """

    id = "judged-rules-completeness"
    how = "An LLM reads the rules/terms pages for missing launch-critical clauses."
    title = "Rules cover the launch-critical clauses (LLM-judged, advisory)"
    dimension = Dimension.DOCUMENTATION
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 13, Ch. 4, Ch. 2)"

    def build_prompt(self, ctx: CheckContext) -> str:
        yaml_text, pages_text = _bundle_texts(ctx)
        return f"""You are auditing a Codabench competition bundle before launch.

Read the participant-facing pages (especially any Terms / Rules) and report which
of the launch-critical RULES clauses are ABSENT or left unstated. Check for:

- eligibility (who may participate; any exclusions)
- disqualification criteria (what gets a submission/participant removed)
- the tie-break rule (how exact ties on the metric are resolved — it must be
  deterministic, e.g. earliest submission, not a significance test)
- prize-award governance, IF prizes exist (who judges, on what criteria, appeals)
- intellectual-property / licensing of submitted code or solutions
- an anti-fraud / multiple-account policy
- a code of conduct or communication norms

Report one finding per clause that is genuinely missing from the pages. Do not
invent requirements the competition's nature does not need (e.g. prize governance
when there are no prizes). Quote or point to where you looked.

{_JSON_FOOTER}
--- competition.yaml ---
{yaml_text}

--- pages ---
{pages_text}
"""


@register
class TaskFramingClarity(JudgedCheck):
    """Is the task framed clearly, with a single focused objective?

    Chapter 2 stresses reducing a challenge to one clear objective and stating the
    scientific question and its motivation; force-fitting disparate objectives into
    one ranking is a named pitfall. This judges the *clarity* of the framing, which
    code cannot assess.
    """

    id = "judged-task-framing"
    how = "An LLM judges whether the overview states a single, clear task with motivation."
    title = "Task is clearly framed with a single objective (LLM-judged, advisory)"
    dimension = Dimension.DOCUMENTATION
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 2)"

    def build_prompt(self, ctx: CheckContext) -> str:
        yaml_text, pages_text = _bundle_texts(ctx)
        return f"""You are auditing a Codabench competition bundle before launch.

Read the overview / task description and judge whether the task is framed clearly.
Report a finding for each problem you find:

- the scientific question or prediction task is vague or unstated
- the motivation / why-it-matters is absent
- the competition does NOT reduce to a single clear objective — e.g. it force-fits
  several disparate goals or metrics into one ranking (Pavão Ch. 2 names this an
  anti-pattern; separate tracks would be the fix)
- the input the participant gets and the output they must produce are unclear

Only report substantive clarity problems, not style. Point to where you looked.

{_JSON_FOOTER}
--- competition.yaml ---
{yaml_text}

--- pages ---
{pages_text}
"""


@register
class SubmissionInstructionsSufficient(JudgedCheck):
    """Could a participant actually produce a valid first submission?

    The single biggest participation lever is a first-hour submission. That needs
    the exact submission format and the interface (file layout / function
    signatures) documented in the pages and the starting kit. A judge can read both
    and report whether a newcomer has enough to submit.
    """

    id = "judged-submission-instructions"
    how = "An LLM checks the pages + starting kit document the submission format and interface."
    title = "Submission format + interface are documented (LLM-judged, advisory)"
    dimension = Dimension.DOCUMENTATION
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 2, Ch. 11)"

    def build_prompt(self, ctx: CheckContext) -> str:
        yaml_text, pages_text = _bundle_texts(ctx)
        kit_text = _starting_kit_text(ctx)
        return f"""You are auditing a Codabench competition bundle before launch.

Judge whether a NEW participant has enough to make a valid first submission. Read
the pages and the starting kit, then report a finding for each gap:

- the exact submission format is not specified (file name(s), columns/shape, the
  order rows must follow, zip layout)
- for a code submission, the interface the participant must implement is
  undocumented (which file, which function/class signatures, entry point)
- there is no runnable example / template in the starting kit to copy
- the local-testing path (how to score their own predictions before submitting)
  is missing

Only report gaps that would actually block or confuse a newcomer.

{_JSON_FOOTER}
--- competition.yaml ---
{yaml_text}

--- pages ---
{pages_text}

--- starting kit ---
{kit_text}
"""


@register
class EvaluationExplained(JudgedCheck):
    """Is the evaluation metric and ranking explained well enough to act on?

    Distinct from the docs↔config *contradiction* check: this catches
    *under-explanation* — a metric named but not explained, or a ranking whose
    direction and tie handling a participant cannot infer.
    """

    id = "judged-evaluation-explained"
    how = "An LLM checks the evaluation page explains the metric and how ranking is decided."
    title = "Metric and ranking are explained (LLM-judged, advisory)"
    dimension = Dimension.DOCUMENTATION
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 4)"

    def build_prompt(self, ctx: CheckContext) -> str:
        yaml_text, pages_text = _bundle_texts(ctx)
        return f"""You are auditing a Codabench competition bundle before launch.

Read the Evaluation page (and the leaderboard config) and report ONLY a material
under-explanation of the evaluation:

- the primary metric is named but never explained, so a reader cannot tell what
  it measures; OR
- the metric is not identifiable at all; OR
- how the winner / final ranking is decided is genuinely ambiguous.

Do NOT report these — they are adequate as-is:
- the metric is explained in prose even if its numeric range is not spelled out;
- the ranking direction is conveyed by the leaderboard `sorting`, even if the page
  does not also say "higher is better" in words;
- ties are handled in the config or mentioned only briefly.

Report under-explanation, not contradictions (a separate check covers those).

{_JSON_FOOTER}
--- competition.yaml ---
{yaml_text}

--- pages ---
{pages_text}
"""


@register
class DataDescriptionAdequate(JudgedCheck):
    """Does the data documentation let a participant understand the dataset?

    Chapter 3/5: participants need the dataset size, the split structure, what is
    public vs hidden, the external-data policy, and licensing/provenance — at a
    level they can act on.
    """

    id = "judged-data-description"
    how = "An LLM checks the data page documents size, splits, visibility, and data policy."
    title = "Data is documented adequately (LLM-judged, advisory)"
    dimension = Dimension.DOCUMENTATION
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 3, Ch. 5)"

    def build_prompt(self, ctx: CheckContext) -> str:
        yaml_text, pages_text = _bundle_texts(ctx)
        return f"""You are auditing a Codabench competition bundle before launch.

Read the Data page and report findings where the data documentation is inadequate
for a participant:

- the dataset size / number of examples is not given
- the split structure (train / public test / private test) is unclear
- what is public versus hidden (and that test labels are sequestered) is unstated
- the external-data / pre-trained-model policy is absent
- licensing or provenance of the data is missing

Only report substantive omissions a participant would need.

{_JSON_FOOTER}
--- competition.yaml ---
{yaml_text}

--- pages ---
{pages_text}
"""


async def run_judged_checks(ctx: CheckContext, backend: AgentBackend) -> list[CheckResult]:
    from .base import REGISTRY

    results: list[CheckResult] = []
    for check in REGISTRY.values():
        if isinstance(check, JudgedCheck):
            results.extend(await check.run_judged(ctx, backend))
    return results
