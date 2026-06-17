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
    'placeholder" (report). Proposal-level material — novelty, baseline ranges, '
    'detailed schedules, promotion, formal legal clauses — often lives in a '
    'separate proposal document, NOT these participant pages; its absence here is '
    'not by itself a finding. An educational or no-prize challenge needs far less '
    'formality than a high-stakes one. When genuinely in doubt, return an empty '
    'list.\n\n'
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
    template_section = "T9"
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
    template_section = "T4"
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
    template_section = "T8"
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
    template_section = "T5"
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
    template_section = "T3"
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


# ---------------------------------------------------------------------------
# Proposal-template judged checks — the prose-level sections of the published
# challenge-design roadmap (Pavão et al.) that code cannot read. See
# docs/validation-checklist-proposal.md §11. Each is a fixed rubric over the
# pages + competition.yaml, biased toward silence by the shared _JSON_FOOTER so
# a concise-but-adequate bundle passes with an empty findings list.
# ---------------------------------------------------------------------------


class _PagesRubric(JudgedCheck):
    """A judged check whose prompt is a fixed rubric over competition.yaml +
    pages. Subclasses set ``rubric`` — the '- report a finding when …' body.
    The shared calibration/format footer is appended automatically."""

    rubric: str = ""
    intro: str = "You are auditing a Codabench competition bundle before launch."

    def build_prompt(self, ctx: CheckContext) -> str:
        yaml_text, pages_text = _bundle_texts(ctx)
        return f"""{self.intro}

{self.rubric.strip()}

{_JSON_FOOTER}
--- competition.yaml ---
{yaml_text}

--- pages ---
{pages_text}
"""


@register
class AbstractStructure(_PagesRubric):
    """Does the overview/abstract cover the five elements a proposal abstract
    should state (motivation+impact, task+data, novelty, baselines+results,
    scientific questions)? An abstract missing these gives a reader no quick way
    to judge what the challenge is and why it matters."""

    id = "judged-abstract-structure"
    how = "An LLM checks the overview opens with the five standard abstract elements."
    title = "Abstract covers the five standard elements (LLM-judged, advisory)"
    dimension = Dimension.DOCUMENTATION
    template_section = "T0"
    severity = Severity.INFO
    citation = "Pavão et al. (Ch. 2)"
    rubric = """
The overview need not be a formal abstract. Report a SINGLE finding ONLY IF the
overview is essentially a stub that fails to convey even the basics — i.e. a
reader cannot tell BOTH what the task is AND why it matters. If the motivation
and the task are both present (even briefly), pass: do NOT require an explicit
novelty, baseline-results, or "scientific questions" section here — those
normally live in the proposal, not this page.
"""


@register
class KeywordsPresent(_PagesRubric):
    """Does the bundle give a reader quick topical orientation (keywords / tags /
    a one-line topic sentence)? Minor polish — flagged only when a reader gets no
    orientation at all."""

    id = "judged-keywords-present"
    how = "An LLM checks the pages give a reader quick topical orientation (keywords/tags)."
    title = "Topical keywords / orientation present (LLM-judged, advisory)"
    dimension = Dimension.DOCUMENTATION
    template_section = "T0"
    severity = Severity.INFO
    citation = "Pavão et al. (Ch. 2)"
    rubric = """
Keywords are optional polish. Report a SINGLE finding ONLY IF the pages give a
reader no quick topical orientation whatsoever — no keyword/tag line and no
opening sentence that names the domain and task. If the domain and task are
discernible from the first paragraph, pass with an empty list.
"""


@register
class BackgroundImpact(_PagesRubric):
    """Do the pages motivate the problem and state its anticipated impact, the
    audience, and a real-world scenario (the 'hook')? A challenge with no stated
    background or impact reads as an arbitrary exercise."""

    id = "judged-background-impact"
    how = "An LLM checks the pages motivate the problem and state impact, audience, and a real scenario."
    title = "Background & impact are stated (LLM-judged, advisory)"
    dimension = Dimension.DOCUMENTATION
    template_section = "T1"
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 2)"
    rubric = """
Read the background / overview and report a finding for each that is ABSENT:

- any background on the problem and the field(s) it touches
- the anticipated impact (economic, humanitarian, societal, scientific, …)
- a sense of who the audience is / why the task is relevant to them
- a real-life scenario the task corresponds to (or a justified abstraction)

Report only elements a reader could not find at all, not requests for more depth.
"""


@register
class NoveltyPositioning(_PagesRubric):
    """Do the pages position the challenge against prior challenges/benchmarks —
    stating what is new, or that it is a new edition reusing/extending earlier
    data? Unstated novelty makes a challenge hard to place scientifically."""

    id = "judged-novelty-positioning"
    how = "An LLM checks the pages state how the challenge differs from prior challenges/benchmarks."
    title = "Novelty is positioned vs prior work (LLM-judged, advisory)"
    dimension = Dimension.DOCUMENTATION
    template_section = "T2"
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 2)"
    rubric = """
Report a finding ONLY IF the pages say nothing about how this challenge relates
to prior work — neither a difference from earlier challenges/benchmarks, nor a
statement that it is new, part of a series, or reuses/extends existing data. A
brief positioning sentence is sufficient; do not demand a literature review.
"""


@register
class DataQuantityJustified(_PagesRubric):
    """Do the pages justify that the dataset is large enough for conclusive
    results, will be available after the contest, and that ground truth is held
    confidential? These are the data-quality claims a benchmark rests on."""

    id = "judged-data-quantity-justified"
    how = "An LLM checks the pages justify dataset size, post-contest availability, and GT confidentiality."
    title = "Data quantity & availability justified (LLM-judged, advisory)"
    dimension = Dimension.DATA
    template_section = "T3"
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 3)"
    rubric = """
Report a SINGLE finding ONLY IF the data documentation is a stub that gives a
participant no usable sense of the dataset at all. If the data, its source, and
roughly what it contains are described, pass — do NOT require explicit sentences
about size-adequacy, post-contest availability, or ground-truth confidentiality,
which usually live in the proposal or a datasheet rather than this page.
"""


@register
class TaskScenario(_PagesRubric):
    """Do the pages connect the task to a concrete real-world scenario (or justify
    the abstraction)? A task with no application framing is hard for participants
    to reason about."""

    id = "judged-task-scenario"
    how = "An LLM checks the pages tie the task to a real-world scenario or justify the abstraction."
    title = "Task tied to an application scenario (LLM-judged, advisory)"
    dimension = Dimension.DOCUMENTATION
    template_section = "T4"
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 2)"
    rubric = """
Report a finding ONLY IF the pages describe the task with no connection to any
real-world scenario or application AND give no justification for the abstraction.
A single sentence linking the task to a use-case is sufficient.
"""


@register
class TaskDifficulty(_PagesRubric):
    """Do the pages argue the task is challenging but solvable — neither trivial
    nor impossible? Calibrating difficulty is a core design responsibility; the
    measured baseline gap is the evidence."""

    id = "judged-task-difficulty"
    how = "An LLM checks the pages argue the task is challenging but solvable (e.g. a baseline-to-headroom gap)."
    title = "Task difficulty is calibrated (LLM-judged, advisory)"
    dimension = Dimension.METHODOLOGICAL
    template_section = "T4"
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 5)"
    rubric = """
Report a SINGLE finding ONLY IF the pages give NO indication anywhere that the
task is non-trivial yet solvable. A baseline reference, a mention of difficulty,
an evident challenge framing, or a clearly real-world task all count — any one of
these is enough to pass. Detailed difficulty calibration lives in the proposal.
"""


@register
class MetricJustified(_PagesRubric):
    """Do the pages justify *why* the chosen metric measures success on this task,
    not merely name it? A metric that is asserted but not motivated can fail to
    reward the behaviour the challenge cares about."""

    id = "judged-metric-justified"
    how = "An LLM checks the pages justify why the metric assesses the task, beyond naming it."
    title = "Metric choice is justified (LLM-judged, advisory)"
    dimension = Dimension.METHODOLOGICAL
    template_section = "T5"
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 4)"
    rubric = """
Justification = a connection between the metric and what the competition cares
about. It can be explicit ("we use AUC because classes are imbalanced") or
implicit in the metric's own definition (a per-group / geometric-mean accuracy
that is clearly built to reward fairness across groups is justified). Report a
SINGLE finding ONLY IF the metric is merely named — with at most its direction or
tie-break — and the pages draw NO link between it and the task's goal or
structure. Naming "balanced accuracy" with no mention of why balance matters here
is such a case; defining a grouped metric that embodies the task's fairness aim
is not.
"""


@register
class ErrorBarsDescribed(_PagesRubric):
    """Do the pages account for how meaningful score differences between
    participants are — error bars, significance, or noise? Minor for most
    challenges; flagged only when the ranking leans on fine distinctions with no
    account of their reliability."""

    id = "judged-error-bars"
    how = "An LLM checks whether score-difference significance / error bars are addressed when the ranking needs it."
    title = "Score-difference significance addressed (LLM-judged, advisory)"
    dimension = Dimension.METHODOLOGICAL
    template_section = "T5"
    severity = Severity.INFO
    citation = "Pavão et al. (Ch. 4)"
    rubric = """
Many competitions reasonably omit this. Report a SINGLE finding ONLY IF the
evaluation clearly hinges on fine distinctions between participants (e.g. a
single-number leaderboard deciding prizes) AND the pages give no account at all
of error bars, significance, or measurement noise. Otherwise pass.
"""


@register
class JudgingProtocol(_PagesRubric):
    """For human/subjective judging, are the criteria specific and orthogonal, the
    tie-break defined, and the judges' qualifications given? Only applies when the
    organizer declares human_judging=true."""

    id = "judged-judging-protocol"
    how = "When human_judging is declared, an LLM checks the judging criteria, tie-break, and judge qualifications."
    title = "Human-judging protocol is specified (LLM-judged, advisory)"
    dimension = Dimension.GOVERNANCE
    template_section = "T5"
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 4)"
    requires_facts = ("human_judging",)
    rubric = """
This challenge uses human / subjective judging. Report a finding for each that is
ABSENT from the pages:

- judging criteria that are specific and as orthogonal (non-overlapping) as possible
- how ties between judges are broken
- who the judges are / what qualifies them

Report only genuinely missing elements.
"""

    async def run_judged(self, ctx: CheckContext, backend: AgentBackend) -> list[CheckResult]:
        if ctx.facts.human_judging is False:
            return [self.passed("no human/subjective judging declared — judging protocol N/A")]
        return await super().run_judged(ctx, backend)


@register
class BaselineRange(_PagesRubric):
    """Do the pages document a *range* of baselines — from a trivial bound to a
    competent/state-of-the-art method — and a meaningful gap between them? A
    single baseline cannot show the task has headroom worth competing for."""

    id = "judged-baseline-range"
    how = "An LLM checks the pages describe a range of baselines (trivial→SOTA) and the performance gap."
    title = "Baseline range (trivial→SOTA) documented (LLM-judged, advisory)"
    dimension = Dimension.METHODOLOGICAL
    template_section = "T6"
    severity = Severity.INFO
    citation = "Pavão et al. (Ch. 5)"
    rubric = """
Baselines are usually shipped in the starting kit or described in the proposal,
not the overview. Report a SINGLE finding ONLY IF the pages actively present
results or assert the task is competition-worthy YET give no baseline and no
sense of headroom anywhere, and no starting-kit baseline exists. A competition
that simply does not discuss baselines on its participant pages should pass.
"""


@register
class StartingKitParity(_PagesRubric):
    """Does the starting kit let participants develop and test under conditions
    identical to the evaluation platform? A kit that cannot reproduce the scoring
    locally forces blind submissions."""

    id = "judged-starting-kit-parity"
    how = "An LLM checks the pages + starting kit let participants test under the same conditions as evaluation."
    title = "Starting kit mirrors evaluation conditions (LLM-judged, advisory)"
    dimension = Dimension.DOCUMENTATION
    template_section = "T6"
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 5)"

    def build_prompt(self, ctx: CheckContext) -> str:
        yaml_text, pages_text = _bundle_texts(ctx)
        kit_text = _starting_kit_text(ctx)
        return f"""{self.intro}

Judge whether the starting kit lets a participant develop and test their solution
under conditions close to the evaluation platform. Be lenient: any local-eval
path counts — a scoring script, an example/`readme` notebook that shows how to
produce a submission, or a stated way to check predictions locally. Report a
SINGLE finding ONLY IF there is clearly NO local-eval path AND the kit's interface
obviously diverges from the platform (different file format or entry point) so
local results would not transfer. If in doubt, pass.

{_JSON_FOOTER}
--- competition.yaml ---
{yaml_text}

--- pages ---
{pages_text}

--- starting kit ---
{kit_text}
"""


@register
class EquitableResources(_PagesRubric):
    """When entering needs special hardware or heavy compute, do the pages address
    equitable access for under-resourced participants? Only applies when the
    organizer declares special_hardware=true."""

    id = "judged-equitable-resources"
    how = "When special hardware is declared, an LLM checks the pages address equitable resource access."
    title = "Equitable resource access addressed (LLM-judged, advisory)"
    dimension = Dimension.GOVERNANCE
    template_section = "T6"
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 5)"
    requires_facts = ("special_hardware",)
    rubric = """
Entering this challenge needs special hardware or significant compute. Report a
finding ONLY IF the pages make no provision for participants who cannot afford it
— no free/granted compute, no alternative track, and no acknowledgement of the
barrier. A stated provision (even a screening-based grant) is sufficient.
"""

    async def run_judged(self, ctx: CheckContext, backend: AgentBackend) -> list[CheckResult]:
        if ctx.facts.special_hardware is False:
            return [self.passed("no special hardware declared — equitable-access criterion N/A")]
        return await super().run_judged(ctx, backend)


@register
class TutorialMaterial(_PagesRubric):
    """Do the pages reference tutorial material — a white paper, FAQ, notebooks,
    a video — beyond the bare task description? Onboarding material is a major
    participation lever, especially for newcomers to the domain."""

    id = "judged-tutorial-material"
    how = "An LLM checks the pages reference tutorial material (white paper, FAQ, notebooks, video)."
    title = "Tutorial / documentation material referenced (LLM-judged, advisory)"
    dimension = Dimension.DOCUMENTATION
    template_section = "T7"
    severity = Severity.INFO
    citation = "Pavão et al. (Ch. 2)"
    rubric = """
Report a SINGLE finding ONLY IF the pages provide no onboarding material beyond
the bare task statement — no white paper / reference, no FAQ, no tutorial
notebook, no walkthrough. A starting-kit notebook or a linked paper counts as
present.
"""


@register
class ProtocolDescribed(_PagesRubric):
    """Do the pages describe the challenge protocol — what participants do, what
    they submit, the evaluation procedure, the phase structure, and that there is
    a leaderboard? The protocol is the contract participants operate under."""

    id = "judged-protocol-described"
    how = "An LLM checks the pages describe the protocol: what is submitted, the procedure, phases, leaderboard."
    title = "Challenge protocol is described (LLM-judged, advisory)"
    dimension = Dimension.DOCUMENTATION
    template_section = "T8"
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 2)"
    rubric = """
Report a finding ONLY IF the participant pages never state what a participant
SUBMITS or HOW a submission becomes a score. A page that gives only motivation /
background — with no submission, evaluation, or phase information anywhere — is
such a case and must be reported. If what-to-submit and the scoring procedure are
both conveyed (even briefly), pass; the phase list and an explicit leaderboard
mention are nice-to-have, not required.
"""


@register
class CheatingPrevention(_PagesRubric):
    """Do the rules address cheating detection and prevention? Without a stated
    anti-cheating stance, disputes over multi-accounting, label leakage, or
    collusion have no documented basis."""

    id = "judged-cheating-prevention"
    how = "An LLM checks the rules/pages address cheating detection and prevention."
    title = "Cheating prevention is addressed (LLM-judged, advisory)"
    dimension = Dimension.GOVERNANCE
    template_section = "T8"
    severity = Severity.INFO
    citation = "Pavão et al. (Ch. 2, Ch. 5)"
    rubric = """
Submission caps (per-day / total) ARE a recognised anti-probing measure, and a
final phase scored on hidden data or a code-submission setup also limit cheating
— all of these count. Report a SINGLE finding ONLY IF a competitive challenge
addresses integrity in NO way at all (no submission limits, no final phase, no
review, no account/leakage policy). A low-stakes educational challenge passes.
"""


@register
class AccountPolicy(_PagesRubric):
    """Do the rules state the account / anonymity policy — single vs multiple
    accounts and whether anonymous entries are allowed? Ambiguity here is a
    common source of disqualification disputes."""

    id = "judged-account-policy"
    how = "An LLM checks the rules state the single-vs-multiple-account and anonymity policy."
    title = "Account & anonymity policy stated (LLM-judged, advisory)"
    dimension = Dimension.GOVERNANCE
    template_section = "T9"
    severity = Severity.INFO
    citation = "Pavão et al. (Ch. 13)"
    rubric = """
Report a SINGLE finding ONLY IF this is a competitive / prize-bearing challenge
whose rules nonetheless say nothing about multiple accounts or anonymity. An
educational or no-prize challenge does not need an account policy — pass it.
"""


@register
class RulesImmutability(_PagesRubric):
    """Do the rules state that they are fixed for the duration (with an amendment
    policy if changes become necessary)? Serious competitors need a stable,
    well-defined set of winning conditions."""

    id = "judged-rules-immutability"
    how = "An LLM checks the rules state they are fixed for the duration, with an amendment policy."
    title = "Rules stability / amendment policy stated (LLM-judged, advisory)"
    dimension = Dimension.GOVERNANCE
    template_section = "T9"
    severity = Severity.INFO
    citation = "Pavão et al. (Ch. 13)"
    rubric = """
An educational or no-prize challenge does not need an explicit amendment policy —
pass it. Report a SINGLE finding ONLY IF this is a competitive / prize-bearing
challenge whose rules give no indication that the winning conditions are fixed for
the duration. A short stability clause is sufficient.
"""


@register
class ScheduleAdequacy(_PagesRubric):
    """Does the schedule leave adequate time — preparation, a development window
    (~90 days is the norm), and post-close review — and state what is already
    ready? A compressed schedule with no review window invites a rushed launch."""

    id = "judged-schedule-adequacy"
    how = "An LLM checks the pages present a schedule with adequate development and review time."
    title = "Schedule leaves adequate time (LLM-judged, advisory)"
    dimension = Dimension.DOCUMENTATION
    template_section = "T10"
    severity = Severity.WARNING
    citation = "Pavão et al. (Ch. 5)"
    rubric = """
Report a finding ONLY IF the schedule is clearly inadequate or unstated:

- no timeline is given at all, OR
- the participant development window is plainly too short (well under ~90 days)
  for the difficulty implied, OR
- there is no time reserved after submissions close for organizer review/analysis
  before results are published.

If a reasonable timeline with a development window and a review buffer is
conveyed, pass.
"""


async def run_judged_checks(ctx: CheckContext, backend: AgentBackend,
                            on_check=None) -> list[CheckResult]:
    """Run every registered judged check. ``on_check`` (optional) receives
    ``{"event": "start"|"done", "title": ..., "results": [...]}`` events so the
    CLI can show live, per-check progress while the LLM works."""
    from .base import REGISTRY

    results: list[CheckResult] = []
    for check in REGISTRY.values():
        if isinstance(check, JudgedCheck):
            if on_check:
                on_check({"event": "start", "title": check.title})
            res = await check.run_judged(ctx, backend)
            if on_check:
                on_check({"event": "done", "title": check.title, "results": res})
            results.extend(res)
    return results
