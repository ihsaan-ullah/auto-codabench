"""Attestation items — facts only a human can certify.

These are real launch criteria from the competition-design checklist that no
amount of code or LLM judgment can verify. The validator surfaces them as
unchecked boxes so they are impossible to forget, and never pretends to have
checked them.
"""
from __future__ import annotations

from .base import (
    Check,
    CheckContext,
    CheckResult,
    Dimension,
    REGISTRY,
    Severity,
    Status,
    Tier,
    register,
)


class _Attestation(Check):
    tier = Tier.ATTESTATION
    dimension = Dimension.GOVERNANCE
    severity = Severity.WARNING
    statement: str = ""
    # What an LLM should look at in the bundle to give a tailored suggestion for
    # this human-only criterion (used only when validation runs with a backend).
    llm_guidance: str = ""

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        return [self.attestation(self.statement)]

    async def assess(self, ctx: CheckContext, backend) -> list[CheckResult]:
        """LLM-assisted variant: keep the human attestation, but replace the
        generic statement with a short, tailored note grounded in this bundle.

        The verdict stays ATTESTATION_REQUIRED — the LLM advises, it does not
        certify a human-only criterion — except where the deterministic ``run``
        already resolves the item (e.g. ``prizes=false``)."""
        missing = self.missing_facts(ctx)
        if missing:
            return [self.skipped(
                f"requires facts not provided: {', '.join(missing)} — add them to "
                f"competition_facts.yaml to enable this check")]
        base = self.run(ctx)
        out: list[CheckResult] = []
        for r in base:
            if r.status != Status.ATTESTATION_REQUIRED:
                out.append(r)  # already resolved deterministically (e.g. auto-pass)
                continue
            note = await self._llm_note(ctx, backend)
            out.append(self.attestation(note or self.statement))
        return out

    async def _llm_note(self, ctx: CheckContext, backend) -> str | None:
        from ..backends.base import AgentTask
        from .judged import _bundle_texts
        yaml_text, pages_text = _bundle_texts(ctx)
        prompt = f"""You advise a competition organizer before launch about a
HUMAN-VERIFIED criterion that code cannot check.

Criterion: {self.statement}

What to assess: {self.llm_guidance or 'whether the bundle shows readiness for this criterion'}

Read the bundle below and write a SHORT note (1–3 sentences), specific and
tailored to THIS bundle: what it already shows that is relevant, and concretely
what the organizer should still verify or add before launch. Cite specifics from
the bundle; do not invent facts. Plain prose only — no preamble, no JSON, no
bullet list.

--- competition.yaml ---
{yaml_text}

--- pages ---
{pages_text}
"""
        try:
            result = await backend.run(AgentTask(prompt=prompt, allowed_tools=[]))
        except Exception:
            return None
        if not result.ok or not result.final_text:
            return None
        note = " ".join(result.final_text.split()).strip()
        return (note[:500].rstrip() + "…") if len(note) > 500 else note or None


def is_attestation_id(check_id: str) -> bool:
    c = REGISTRY.get(check_id)
    return bool(c) and c.tier == Tier.ATTESTATION


async def run_attestation_assessments(ctx: CheckContext, backend,
                                      on_check=None) -> list[CheckResult]:
    """Run the LLM-assisted variant of every registered attestation check.
    ``on_check`` (optional) receives start/done events for live CLI progress."""
    out: list[CheckResult] = []
    for check in REGISTRY.values():
        if isinstance(check, _Attestation):
            if on_check:
                on_check({"event": "start", "title": check.title})
            res = await check.assess(ctx, backend)
            if on_check:
                on_check({"event": "done", "title": check.title, "results": res})
            out.extend(res)
    return out


@register
class ExternalReviewAttestation(_Attestation):
    id = "attest-external-review"
    template_section = "T8"
    llm_guidance = "Whether the bundle is reviewable end-to-end (a runnable baseline, starting kit, clear task) so a reviewer could attempt it; note that ≥1 external reviewer must still actually solve it."
    how = "Cannot be read from the bundle — surfaced for human confirmation; an LLM can suggest what to verify."
    title = "External proposal review"
    citation = "Pavão et al. (Ch. 2)"
    statement = ("At least one external reviewer (ideally 3+) attempted the task "
                 "before announcement — one of the four pillars of successful "
                 "challenges, and the cheapest dead-end-task catch available.")


@register
class LeakageProbeAttestation(_Attestation):
    id = "attest-leakage-probe"
    template_section = "T3"
    llm_guidance = "From the data/feature descriptions, which columns or signals look most leak-prone, and remind that each must be probed with a single-feature model."
    how = "Requires a training run — surfaced for human confirmation; an LLM can suggest likely leak sources."
    title = "Per-feature leakage probe"
    dimension = Dimension.DATA
    citation = "Pavão et al. (Ch. 3)"
    statement = ("A model was trained on each candidate leaky feature alone and "
                 "confirmed not to beat the trivial baseline (covers ground-truth-"
                 "in-features, duplicate entities, and processing leakage).")


@register
class DatasheetAttestation(_Attestation):
    id = "attest-datasheet"
    template_section = "T3"
    llm_guidance = "What provenance, license, consent, and known-bias information the pages already give, and what a published datasheet should still add."
    how = "Cannot be read from the bundle — surfaced for human confirmation; an LLM can draft a datasheet checklist."
    title = "Datasheet / data nutrition label"
    citation = "Pavão et al. (Ch. 3)"
    statement = ("A datasheet (Gebru et al.) covering provenance, consent, known "
                 "biases, and intended use is published with the dataset.")


@register
class DataPersistenceAttestation(_Attestation):
    id = "attest-data-persistence"
    template_section = "T3"
    llm_guidance = "Whether the pages state a data license, a persistent URL/DOI, and a post-competition home — flag which are present and which are missing."
    how = "Cannot be read from the bundle — surfaced for human confirmation; an LLM can flag missing license/DOI cues."
    title = "Dataset license and post-competition home"
    citation = "Pavão et al. (Ch. 3, Ch. 13)"
    statement = ("The dataset has an explicit license, a persistent identifier or "
                 "URL, and a decided post-competition home — benchmarks whose data "
                 "dies after the leaderboard close are not benchmarks.")


@register
class GameOfSkillAttestation(_Attestation):
    id = "attest-game-of-skill"
    template_section = "T13"
    llm_guidance = "If prizes are offered, what skill-vs-chance and jurisdiction considerations apply, and remind to obtain legal confirmation."
    how = "Auto-passes when prizes=false; otherwise surfaced for legal confirmation, LLM-assisted."
    title = "Prize legality (game of skill)"
    citation = "Pavão et al. (Ch. 13)"
    requires_facts = ("prizes",)
    statement = ("Legal confirmed 'game of skill' jurisdiction rules for the "
                 "prize structure.")

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        if ctx.facts.prizes is False:
            return [self.passed("facts declare prizes=false — no prize-law exposure")]
        return [self.attestation(self.statement)]


# ---------------------------------------------------------------------------
# Proposal-template attestations (Pavão et al. roadmap) — proposal-only /
# off-platform criteria the bundle cannot prove. See
# docs/validation-checklist-proposal.md §11.
# ---------------------------------------------------------------------------


@register
class DeprecatedDatasetAttestation(_Attestation):
    id = "attest-deprecated-dataset"
    template_section = "T3"
    dimension = Dimension.DATA
    llm_guidance = ("From the dataset name and description, note any known recall/"
                    "deprecation risk and remind the organizer to search "
                    "'<dataset name> deprecated' and check the venue's deprecated-"
                    "dataset list before reusing it.")
    how = ("Cannot be read from the bundle — surfaced for human confirmation; needs the "
           "dataset_name fact, and an LLM drafts the due-diligence note.")
    title = "Dataset is not deprecated / recalled"
    citation = "Pavão et al. (Ch. 3)"
    requires_facts = ("dataset_name",)
    statement = ("The dataset has been confirmed not deprecated or recalled — recycled "
                 "datasets are sometimes withdrawn for bias or ethical reasons; search "
                 "'<dataset> deprecated' and the venue's deprecated-dataset list.")


@register
class PiiConsentAttestation(_Attestation):
    id = "attest-pii-consent"
    template_section = "T3"
    dimension = Dimension.GOVERNANCE
    llm_guidance = ("Whether the pages suggest the data involves human subjects or PII, "
                    "and what consent / ethics-committee / minimisation evidence the "
                    "organizer should hold.")
    how = "Cannot be read from the bundle — surfaced for human confirmation; an LLM can flag PII risk."
    title = "PII minimised and consent / ethics approval obtained"
    citation = "Pavão et al. (Ch. 3)"
    statement = ("Personally identifiable information is minimised and, where real human-"
                 "subject data is used, informed consent (and ethics-committee approval "
                 "where applicable) has been obtained.")


@register
class PromotionPlanAttestation(_Attestation):
    id = "attest-promotion-plan"
    template_section = "T11"
    dimension = Dimension.GOVERNANCE
    llm_guidance = ("What audience the pages imply, and concrete promotion channels "
                    "(mailing lists, talks) plus under-represented-group outreach the "
                    "organizer should plan.")
    how = "Cannot be read from the bundle — surfaced for human confirmation; an LLM can draft a promotion checklist."
    title = "Promotion plan, including under-represented outreach"
    citation = "Pavão et al. (Ch. 2)"
    statement = ("A plan exists to promote participation (mailing lists, invited talks, "
                 "etc.) and to attract participants from groups under-represented in "
                 "challenge programs.")


@register
class OrganizingTeamAttestation(_Attestation):
    id = "attest-organizing-team"
    template_section = "T12"
    dimension = Dimension.GOVERNANCE
    llm_guidance = ("Which organizing roles the bundle/pages already evidence, and which "
                    "of the required roles (coordinators, data providers, platform admins, "
                    "baseline providers, beta testers, evaluators) plus diversity the "
                    "organizer should still confirm.")
    how = "Cannot be read from the bundle — surfaced for human confirmation; an LLM can list the roles to staff."
    title = "Organizing team covers the required roles"
    citation = "Pavão et al. (Ch. 2)"
    statement = ("The organizing team covers the required roles — coordinators, data "
                 "providers, platform administrators, baseline-method providers, beta "
                 "testers, and evaluators — with relevant competence and a diversity note.")


@register
class LiveLogisticsAttestation(_Attestation):
    id = "attest-live-logistics"
    template_section = "T10"
    dimension = Dimension.GOVERNANCE
    llm_guidance = ("For a live/on-site challenge, what on-site schedule, organizer-vs-"
                    "participant-provided resources, registration, and connectivity the "
                    "organizer must arrange.")
    how = "Auto-passes unless challenge_type=live; otherwise surfaced for human confirmation, LLM-assisted."
    title = "Live-challenge on-site logistics arranged"
    citation = "Pavão et al. (Ch. 2)"
    requires_facts = ("challenge_type",)
    statement = ("For this live/on-site challenge, the on-site schedule, the split of "
                 "organizer- vs participant-provided resources, registration, and "
                 "connectivity have been arranged.")

    def run(self, ctx: CheckContext) -> list[CheckResult]:
        if str(ctx.facts.challenge_type).strip().lower() != "live":
            return [self.passed(
                f"challenge_type='{ctx.facts.challenge_type}' is not live — "
                "on-site logistics N/A")]
        return [self.attestation(self.statement)]
