# The pre-launch validation checklist of autocodabench: provenance, epistemic stratification, and comparative coverage

**Abstract.** This report documents the validation checklist applied by the
`autocodabench validate` command to a Codabench competition bundle prior to its
public launch, and evaluates that checklist against external evidence. We make
three contributions. First, we provide an authoritative provenance catalog: for
each of the nineteen registered checks we state the property it verifies, the
failure mode it is designed to prevent, and the literature or schema reference
from which it derives. Second, we formalise the epistemic stratification of the
checklist into three tiers — deterministic, model-judged, and human-attested —
and argue that this stratification is a precondition for the validator's central
guarantee, namely that every gating verdict is reproducible and contestable.
Third, we situate the checklist against three independent reference points: a
field report from a 215-participant teaching deployment of Codabench, the
official Codabench bundle template that constitutes an organiser's default
starting artefact, and the MLE-bench agentic benchmark. We then measure coverage
against the canonical sixteen-item best-practice checklist of the competition-design
literature and report, without inflation, that eleven items are addressed and
five remain uncovered. We characterise the uncovered items and identify, as the
most actionable finding, two declared-but-unconsumed entries in the validator's
fact schema. We conclude with an explicit statement of limitations: grounding
the discussion in organiser and stakeholder interviews, we delimit the broad
classes of failure — run-time worker reliability, live phase migration,
population-level cheating and overfitting, data-intrinsic correctness, and
platform identity and access control — that a pre-launch validator of a static
bundle artefact does not and cannot address, and which this work therefore does
not attempt to solve. Throughout, the analysis is intended to delimit the
contribution honestly rather than to claim completeness.

This report is a companion to two operational documents in the same directory:
[`verification-catalog.md`](./verification-catalog.md), which specifies the
mechanical behaviour of each check and test, and
[`scientific-validation.md`](./scientific-validation.md), which enumerates the
software's falsifiable claims and the procedures that test them. Whereas those
documents describe *how the checks execute*, the present work addresses the
prior questions of *why this particular set of checks was adopted* and *how far
its coverage extends*. The canonical source for design principles is Pavão et
al. (2024), *AI Competitions and Benchmarks: The Science Behind the Contests*,
which the project's `competition-design` knowledge module treats as
authoritative; chapter handles (e.g. Ch. 5) are reproduced verbatim from that
source.

---

## 1. Introduction

A competition bundle is the artefact a Codabench organiser uploads to
instantiate a competition: a directory comprising a machine-readable
configuration (`competition.yaml`), ingestion and scoring programs,
participant-facing documentation, baseline solutions, and reference data. The
correctness of a bundle is multi-dimensional. A bundle may be *structurally*
valid (it parses and uploads) yet *operationally* broken (its scoring pipeline
fails in the worker environment), and it may be both structurally and
operationally sound yet *methodologically* weak (its design admits leaderboard
overfitting, or its test set is too small to resolve the systems it ranks). Each
of these dimensions fails differently and is detectable by different means.

The `autocodabench validate` command is a pre-launch instrument that evaluates a
bundle across these dimensions and emits a structured report. Its design rests
on a single methodological commitment, developed in Section 2: a pre-launch
report must distinguish what has been *proven* from what has merely been
*asserted*, and only the former may determine launch-readiness. The remainder of
this report makes that commitment concrete (Section 2), catalogs the checks and
their provenance (Section 3), positions the checklist against external evidence
(Section 4), measures its coverage against the best-practice literature
(Section 5), states the limitations and scope boundaries of the approach
(Section 6), and concludes (Section 7).

---

## 2. The epistemic contract

The validator partitions every check into one of three tiers, each carrying a
distinct epistemic standing (`src/autocodabench/checks/base.py`). The partition
is load-bearing: it determines which verdicts are permitted to gate a launch.

**Table 1.** *Tiers of the validation framework and their verdict authority.*

| Tier | Source of the verdict | Emitted status | Gates launch? |
|------|-----------------------|----------------|---------------|
| Deterministic | Code computes the verdict from the bundle and, when execution is requested, from a real run | `PASS` / `FAIL` / `FINDING` | Yes (exclusively) |
| Judged | A language model grades a fixed rubric over the bundle's text | `FINDING` | No |
| Attestation | A criterion only a human can certify | `ATTESTATION_REQUIRED` | No |

Two properties follow from this partition, both deliberate.

**(P1) Only a reproducible, contestable verdict may gate.** The report's
top-level verdict, `ValidationReport.ok`, is defined as the absence of a
deterministic `FAIL`. Neither a language model's assessment nor a pending human
attestation alters this verdict. The justification is epistemic rather than
conservative: a gate must be reproducible (a second run on the same bundle must
reach the same verdict) and contestable (an organiser must be able to inspect
the code that produced it and challenge it), and only a code-computed verdict
satisfies both. This is the same principle that forbids a generating agent from
certifying its own output, articulated at greater length in
`scientific-validation.md` (§2).

**(P2) A missing input yields a skip, never a silent pass.** Certain checks
require facts that cannot be recovered from the bundle alone — for example, the
anticipated error rate of top systems, the unit of generalisation implied by the
task, or whether monetary prizes are awarded. These are supplied through a
declared side-channel, `competition_facts.yaml`
(`src/autocodabench/checks/facts.py`), under a *declare-then-verify* protocol:
the organiser declares the fact and the check verifies a consequence of it. When
a required fact is absent, the check reports `SKIPPED` together with the
instruction needed to enable it. A skipped check conveys information; a check
that passed silently in the absence of its input would constitute a defect.

A third, orthogonal axis is **execution**. The default invocation of `validate`
is static, keyless, and independent of any container runtime. When execution is
requested, the validator additionally stages the Codabench sandbox and runs the
bundle's own baseline and starting-kit notebook inside the declared
`docker_image`, reproducing the platform worker's behaviour
(`src/autocodabench/checks/execution.py`). Execution-dependent checks are
deterministic and may gate. The evidential gain is qualitative: a report
asserting that "the scoring pipeline produced a score on real data, in the
declared image, in *t* seconds" is stronger than one asserting only that "the
configuration references a file that exists."

In the catalog that follows, checks are referenced by their registered
identifier.

---

## 3. Provenance catalog

The validator registers nineteen checks. Table 2 is the provenance index;
Sections 3.1–3.5 describe each check's mechanism and the failure it is designed
to prevent. References of the form "Ch. *N*" are chapter handles into Pavão et
al. (2024); "Codabench schema" denotes the platform's `Yaml-Structure.md`
bundle specification.

**Table 2.** *Registered checks, grouped by tier.*

| Identifier | Property verified | Tier | Severity | Reference |
|------------|-------------------|------|----------|-----------|
| `bundle-schema` | Configuration parses; referenced files exist; leaderboard keys are written by the scoring program | deterministic | blocker | Codabench schema |
| `baseline-execution` | The baseline runs end-to-end through scoring in the declared image | deterministic (exec.) | blocker | Ch. 5, Ch. 11 |
| `starting-kit-execution` | The starting-kit notebook executes cleanly in the declared image | deterministic (exec.) | warning | Ch. 5, Ch. 13 |
| `two-phase-structure` | A development phase and a final phase are both declared | deterministic | warning | Ch. 5, Ch. 11 |
| `dev-phase-duration` | The development phase spans at least ~40 days | deterministic | warning | Ch. 13 |
| `daily-submission-cap` | Development phases cap daily submissions (≈5–10) | deterministic | warning | Ch. 5 |
| `final-phase-submission-limit` | The final phase caps total submissions (≤3) | deterministic | warning | Ch. 5 |
| `leaderboard-sorting` | Every ranked column declares a sorting direction | deterministic | warning | Ch. 4; Codabench schema |
| `starting-kit` | A non-empty starting kit is shipped | deterministic | warning | Ch. 5, Ch. 13 |
| `baseline-solutions` | Baseline solutions are present and declared | deterministic | warning | Ch. 5 |
| `docker-image-pinned` | A worker image is pinned | deterministic | warning | Ch. 11 |
| `test-set-size` | The test set satisfies the 100/E sizing rule | deterministic | warning | Ch. 4 |
| `external-data-rule` | The external-data policy is documented in the pages | deterministic | warning | Ch. 5 |
| `judged-docs-config-consistency` | The pages do not contradict the configuration | judged | warning | Ch. 11, Ch. 13 |
| `attest-external-review` | External reviewers attempted the task pre-announcement | attestation | warning | Ch. 2 |
| `attest-leakage-probe` | Per-feature leakage was probed and excluded | attestation | warning | Ch. 3 |
| `attest-datasheet` | A datasheet / data nutrition label is published | attestation | warning | Ch. 3 |
| `attest-data-persistence` | The dataset has a license, persistent identifier, and post-competition home | attestation | warning | Ch. 3, Ch. 13 |
| `attest-game-of-skill` | Prize legality was confirmed | attestation | warning | Ch. 13 |

Each check carries its reference in its source definition, so that every line of
the rendered report constitutes a *cited claim* rather than an unattributed
judgement. This property renders the report auditable: a reviewer may verify
that any flagged issue corresponds to a documented principle.

### 3.1 The structural gate

`bundle-schema` (blocker) is the sole check whose provenance is the platform
specification rather than the design literature. It delegates to the core schema
linter (`core/bundle_io.validate_bundle`) and verifies that `competition.yaml`
parses, that every referenced file exists, that programs carry runnable
metadata, and that the leaderboard keys the scoring program writes are
consistent with those the configuration declares. A bundle that fails this check
cannot be uploaded, so the check gates; it is the precondition under which the
remaining checks are meaningful. It is the structural analogue of MLE-bench's
content-integrity checksums (Section 4.3).

### 3.2 Design-tier deterministic checks

These checks read the configuration and bundle layout and compare them against
quantified rules from the literature. They emit `FINDING` rather than `FAIL`,
because a design weakness degrades a competition without rendering it unrunnable;
the decision to launch with a known weakness rests with the organiser, not the
tool.

- **`two-phase-structure`** (Ch. 5, Ch. 11) verifies that at least two phases are
  declared. A single-phase competition has no sequestered final test set, so the
  public leaderboard constitutes the final ranking and is liable to overfitting.
  Roelofs et al. (2019) observe that public/private overfitting is empirically
  uncommon on Kaggle; the literature attributes this to Kaggle's enforced
  private test and submission limits rather than to its absence as a risk.

- **`dev-phase-duration`** (Ch. 13) parses the first phase's dates and reports a
  finding when the development window is shorter than approximately forty days,
  below which participation is effectively restricted to those already engaged
  with the problem.

- **`daily-submission-cap`** (Ch. 5) reports a finding for any development phase
  whose `max_submissions_per_day` is absent or exceeds the conventional
  anti-overfitting range of five to ten. Daily caps constrain brute-force
  leaderboard probing more effectively than aggregate caps.

- **`final-phase-submission-limit`** (Ch. 5) reports a finding when a final phase
  permits more than three total submissions. The final phase exists to close the
  overfitting loophole on the sequestered test set; an unbounded submission count
  re-opens it.

- **`leaderboard-sorting`** (Ch. 4; Codabench schema) verifies that each ranked
  column declares a sorting direction, the omission of which silently inverts the
  ranking of any metric for which lower values are preferable. The check is
  limited to verifying that a direction is *declared*; whether the declared
  direction is *semantically correct* for the named metric is delegated to the
  judged tier (Section 3.4).

- **`starting-kit`** (Ch. 5, Ch. 13) verifies that a non-empty starting kit is
  shipped. The starting kit is identified in the literature as the single
  largest determinant of participation quality.

- **`baseline-solutions`** (Ch. 5) verifies that at least one baseline solution
  is present *and declared* in the configuration; an undeclared solution is inert,
  as the platform will not execute it. Two baselines are recommended — a trivial
  one to bound the metric and a competent one to indicate the headroom above it.

- **`docker-image-pinned`** (Ch. 11) verifies that a worker image is declared.
  Absent a pinned image, submissions execute against whatever default the queue
  provides, which may change over the competition's lifetime and break
  reproducibility.

### 3.3 Facts-gated deterministic checks

These checks consume `competition_facts.yaml`; in the absence of the required
fact they skip with an actionable instruction (property P2).

- **`test-set-size`** (Ch. 4; requires `anticipated_error_rate`) implements the
  *100/E rule*: resolving the top systems at an anticipated error rate E requires
  on the order of 100/E test examples. The check computes the required size and
  compares it against either the declared `test_set_size` or, in its absence, the
  row count of a single unambiguous reference CSV. Below the threshold,
  differences near the top of the leaderboard are not statistically resolvable.

- **`external-data-rule`** (Ch. 5; requires `external_data_allowed`) is a hybrid
  check: its deterministic component verifies that the participant-facing pages
  mention the external-data or pre-training policy, while the declared fact
  records the policy's content. Undeclared external data is identified in the
  literature as the most frequent cause of post-hoc disqualification disputes.

### 3.4 The judged tier

- **`judged-docs-config-consistency`** (Ch. 11, Ch. 13). A language model is
  presented with the configuration and the participant-facing pages and
  instructed to report only *contradictions* it can quote from both sources —
  for instance, pages promising a daily submission limit the configuration does
  not enforce, or prose stating that higher scores are better while the
  leaderboard sorts ascending. The output is parsed as strict JSON; unparseable
  output degrades to `SKIPPED` rather than to a pass. This tier covers semantic
  consistency that deterministic code cannot read, and is advisory by
  construction (property P1): the model's judgement never gates a launch.

### 3.5 The attestation tier

These are launch criteria from the literature that no quantity of code or model
judgement can verify. The validator surfaces them as unchecked boxes so that
they cannot be silently omitted, and does not represent them as having been
verified.

- **`attest-external-review`** (Ch. 2): at least one — preferably three —
  external reviewers attempted the task before announcement, identified as one of
  the four pillars of a successful challenge and the least expensive means of
  detecting an ill-posed task.
- **`attest-leakage-probe`** (Ch. 3): a model trained on each candidate leaky
  feature in isolation was confirmed not to exceed the trivial baseline, covering
  ground-truth-in-features, duplicate-entity, and processing leakage.
- **`attest-datasheet`** (Ch. 3): a datasheet (Gebru et al.) documenting
  provenance, consent, biases, and intended use is published.
- **`attest-data-persistence`** (Ch. 3, Ch. 13): the dataset has an explicit
  license, a persistent identifier, and a decided post-competition home.
- **`attest-game-of-skill`** (Ch. 13; requires `prizes`): where prizes are
  awarded, legal counsel has confirmed the applicable game-of-skill jurisdiction
  rules. When the organiser declares `prizes: false`, the check resolves to
  `PASS` rather than demanding the attestation — an illustration of how a
  declared fact narrows the residual human burden.

---

## 4. Comparative positioning

A checklist is informative only insofar as it corresponds to real failure. This
section triangulates the checklist against three independent reference points:
the difficulties practitioners report (Section 4.1), the artefact an organiser
begins from (Section 4.2), and the correctness machinery of an adjacent mature
system (Section 4.3).

### 4.1 A field report: the 2025 École Polytechnique DataCamp

The most direct evidence of community difficulty available to this project is a
debrief from the 2025 DataCamp at École Polytechnique (Institut Polytechnique de
Paris), at which Codabench was used for the first time by a Master's-level cohort
of 215 participants across three research-grade challenges, with participants
additionally acting as organisers of their own competitions. The eight reported
difficulties partition into *platform and infrastructure* concerns, which a
bundle validator cannot address, and *bundle-authoring* concerns, which fall
within its remit. Table 3 records the mapping.

**Table 3.** *Reported difficulties (Letournel & Moreau, 2026) and validator coverage.*

| # | Reported difficulty | Class | Addressed by |
|---|---------------------|-------|--------------|
| 1 | Compute-worker unreliability; lost credits | infrastructure | — (out of scope) |
| 2 | Collaborators cannot administer queues | platform | — (out of scope) |
| 3 | Frequent submission failures; difficult to re-run blocked jobs | bundle + platform | `baseline-execution`, `starting-kit-execution` |
| 4 | Cross-validation not implementable (ingestion/scoring separated) | platform architecture | — (out of scope) |
| 5 | Organiser cannot easily inspect hidden scores to detect overfitting | platform + design | `two-phase-structure`, `daily-submission-cap`, `final-phase-submission-limit` (prevention) |
| 6 | Request to publish the leaderboard after grading | platform feature | — (out of scope) |
| 7 | Each upload instantiates a new competition; competitions are expended during authoring | workflow | the local-validation premise |
| 8 | Documentation is unintuitive; no simple worked example | onboarding | `starting-kit`, `judged-docs-config-consistency`; agentic authoring |

Two mappings are sufficiently strong to constitute the validator's principal
value proposition for this audience.

First, difficulty #3 — frequent submission failures — is precisely the failure
mode the execution tier is constructed to pre-empt. A substantial fraction of
"submission failed" reports originate not in participant code but in a bundle
whose scoring or ingestion path does not execute in the worker image.
`baseline-execution` runs the bundle's own baseline through ingestion and scoring
in the declared image before launch and gates on failure; `starting-kit-execution`
performs the analogous check on the onboarding notebook in an advisory capacity.
A defect that would otherwise manifest as a large number of failed participant
submissions is thereby converted into a single deterministic pre-launch `FAIL`.

Second, difficulty #7 — the expenditure of competitions during authoring — is
addressed by the premise of local validation itself. Because each Codabench
upload instantiates a fresh competition, the platform's only native feedback
loop for an authoring error is to upload, observe the failure, abandon the
competition, and re-upload. The `validate` command relocates this loop off the
platform: the organiser iterates against a local report until the bundle is
structurally valid and its baseline executes, and uploads once. The validator
does not remedy the platform's absence of differential upload, but it removes
most of the demand for it.

Difficulty #5 warrants a qualification. An organiser's inability to *observe*
overfitting on the platform is not within a bundle validator's reach; however,
the design-tier checks address the same concern one step earlier, at the level
of *prevention*. A two-phase structure with capped development submissions and a
final phase limited to at most three submissions is the literature's standard
defence against the overfitting the organiser was unable to detect (Ch. 5).
Prevention at authoring time and observability at run time are complementary, and
the validator owns the former. The remaining difficulties (#1, #2, #4, #6) are
properties of the platform deployment and architecture and lie outside the scope
of a bundle validator; we record them to delimit the contribution rather than to
claim it.

### 4.2 The status quo: the official Codabench bundle template

The artefact from which a new organiser begins is the official Codabench bundle
template, a minimal runnable example competition. Inspection of its
configuration is instructive, as it reveals that the default starting artefact
itself instantiates several of the design weaknesses the validator is built to
detect. By inspection of the template's `competition.yaml`:

- A single phase is declared, so `two-phase-structure` would emit a `FINDING` and,
  in the absence of a final phase, `final-phase-submission-limit` would report
  `SKIPPED`;
- No `max_submissions_per_day` is declared, so `daily-submission-cap` would emit
  a `FINDING`;
- No `docker_image` is declared in the configuration (the image is built
  out-of-band from a `Dockerfile`), so `docker-image-pinned` would emit a
  `FINDING`;
- The starting-kit notebook is shipped at the bundle root rather than under a
  `starting_kit/` directory, so `starting-kit` would emit a `FINDING` under the
  convention the check enforces;
- The leaderboard sorts a test-accuracy column in ascending order.
  `leaderboard-sorting` would *pass*, since a direction is declared. This
  outcome correctly illustrates the check's documented limitation (Section 3.2):
  a suspect *direction* for a higher-is-better metric is the class of semantic
  error reserved for the judged consistency check, not the deterministic one.

The observation is not that the template is poorly constructed — it is a
deliberately minimal teaching scaffold, for which several of these properties are
appropriate — but a methodological one: the gap between a *runnable* bundle and a
*well-designed* competition is real and is invisible at the platform's starting
line. The validator renders this gap explicit and cited, which is precisely the
organiser-facing guidance that difficulty #8 of the field report identified as
missing, delivered as an executable report rather than as prose documentation.

### 4.3 An adjacent system: MLE-bench

MLE-bench (Chan et al., OpenAI) is the closest mature system in the surrounding
literature, and the comparison is informative precisely because the two systems
address different problems. MLE-bench is a curated benchmark of seventy-five
expert-prepared Kaggle competitions, used to evaluate machine-learning *agents*;
autocodabench is a tool that assists *organisers* in authoring and validating
*novel* competitions. The contrast in correctness machinery follows from this
difference in purpose.

**Table 4.** *Correctness machinery of MLE-bench and `autocodabench validate`.*

| Dimension | MLE-bench | `autocodabench validate` |
|-----------|-----------|--------------------------|
| Object validated | A known competition, re-prepared from source | A novel, organiser-authored bundle |
| Correctness oracle | Golden-score regression; checksum integrity; gold-earns-gold and sample-does-not-medal invariants | Schema lint; design-rule findings; in-image baseline and notebook execution |
| Ranking standard | Medal thresholds from the historical leaderboard | Design-time structural checks; no historical reference exists for a novel task |
| Leakage handling | Per-competition preparation scripts assert disjoint splits; known leaks catalogued manually | Human attestation (`attest-leakage-probe`); `test-set-size`; no automated split audit |
| Submission-format validation | Per-metric validators (column presence, row count, identifier alignment, value range) | Delegated to the bundle's scoring program, exercised by `baseline-execution` |
| Contamination enforcement | Post-hoc rule-violation and plagiarism detection over agent logs | Out of scope (no submissions exist pre-launch) |

Three transferable observations follow.

1. *Golden-score regression as a correctness oracle.* MLE-bench pins an expected
   score for each competition's sample submission and asserts it under change,
   thereby detecting silent regressions in grading or data preparation.
   autocodabench possesses an equivalent capability in its benchmark layer — the
   create-bench auditor reproduces a ground-truth submission's score within
   tolerance (`benchmark/`) — but this is an evaluation instrument rather than a
   check the organiser runs on their own bundle. A prospective validator-tier
   check could assert that the shipped baseline reproduces a declared expected
   score.

2. *Submission-format validation as an emergent property of execution.* MLE-bench
   validates submission shape explicitly because it grades a high volume of agent
   submissions; autocodabench instead exercises the bundle's *own* scoring
   program end-to-end via `baseline-execution`, which transitively establishes
   the format contract for at least the baseline. Each approach is appropriate to
   its setting: an explicit validator for a high-throughput grader, an execution
   oracle for a pre-launch bundle.

3. *Automated split-leakage auditing as the principal absent capability.*
   MLE-bench's preparation scripts assert train/test identifier disjointness and
   column consistency at preparation time. autocodabench currently delegates all
   leakage detection to a single human attestation. The per-feature probe of the
   literature (Ch. 3) is difficult to automate without the raw data and the
   grouping variable; a partial deterministic check — identifier disjointness
   across the splits a bundle ships — is, however, attainable and would convert
   one attestation into a gate. This is recorded as a gap in Section 5.

---

## 5. Coverage against the best-practice checklist

The `competition-design` knowledge module distils Pavão et al. (2024) into a
sixteen-item pre-launch checklist (its §8). Treating that checklist as the
best-practice reference, Table 5 reports the tier by which each item is covered.
The entry "—" denotes a genuine gap.

**Table 5.** *Best-practice checklist (Pavão et al., §8) and validator coverage.*

| # | Checklist item (abbreviated) | Ch. | Covered by | Tier |
|---|------------------------------|-----|------------|------|
| 1 | Submission feasible within one hour from the starting kit | 5, 13 | `starting-kit`, `starting-kit-execution` | det. / det.-exec. |
| 2 | Private test set sequestered from participants | 5, 11 | partial: `two-phase-structure` | det. |
| 3 | Each leaky feature alone does not beat the trivial baseline | 3 | `attest-leakage-probe` | attestation |
| 4 | Split matches the unit of generalisation | 3, 4 | — (fact declared, no check) | — |
| 5 | At least one external reviewer attempted the task | 2 | `attest-external-review` | attestation |
| 6 | Primary metric is a single named function with a scorer | 4 | partial: `bundle-schema`, `baseline-execution` | det. |
| 7 | Confidence intervals reported on baseline scores | 4 | — | — |
| 8 | Development phase of at least 40 days | 13 | `dev-phase-duration` | det. |
| 9 | Final phase is code-submission, ≤3 per team | 5 | partial: `final-phase-submission-limit` (count only) | det. |
| 10 | Development submission limits (5–10/day) | 5 | `daily-submission-cap` | det. |
| 11 | Sub-baseline submissions filtered before final ranking | 5, 11 | — | — |
| 12 | Datasheet / data nutrition label published | 3 | `attest-datasheet` | attestation |
| 13 | Class balance checked; balance-aware metric chosen | 4 | — (fact `task_type` declared, no check) | — |
| 14 | Dataset license, persistent URL, post-competition home | 3, 13 | `attest-data-persistence` | attestation |
| 15 | Tie-break and disqualification rules published before submission #1 | 4, 13 | — | — |
| 16 | If prizes are awarded, legal confirmed game of skill | 13 | `attest-game-of-skill` | attestation |

Seven further checks extend coverage beyond the sixteen-item checklist:
Codabench-specific structural validation (`bundle-schema`), reproducibility
(`docker-image-pinned`), two-phase structure as a standalone check
(`two-phase-structure`), statistical test-set sizing (`test-set-size`),
leaderboard direction hygiene (`leaderboard-sorting`), in-image execution
(`baseline-execution`), and pages/configuration consistency
(`judged-docs-config-consistency`).

### 5.1 Coverage summary and the structure of the gaps

Of the sixteen checklist items, eleven are addressed — five by deterministic
checks and six by attestations — and five are uncovered. The uncovered items
fall into three identifiable classes; characterising the class is more
informative than enumerating the items.

*Statistical-rigour gaps (items 7, 11).* Reporting confidence intervals on
baseline scores and filtering sub-baseline submissions prior to final ranking
both require computing and comparing scores across submissions. Both are
feasible in principle once `baseline-execution` has produced a score, and are the
most tractable additions.

*Data-aware gaps (items 4, 13).* Verifying that the split matches the unit of
generalisation, and that the metric is appropriate to the class balance, requires
inspecting the *data* rather than the configuration. We note in particular that
the facts `unit_of_generalization` and `task_type` are *already declared* in the
`CompetitionFacts` schema (`src/autocodabench/checks/facts.py`) and are seeded in
the demo fixture, yet *no registered check consumes either of them*: the
side-channel is provisioned for checks that do not yet exist. This is the most
actionable finding of this report — two latent facts await the checks that would
give them effect — and it aligns with the split-audit observation drawn from
MLE-bench (Section 4.3).

*Policy-text gaps (item 15).* Tie-breaking and disqualification rules are
free-text policy of the kind the judged tier is well suited to audit — whether a
tie-break rule exists in the pages, and whether it is unambiguous — yet no judged
rubric currently targets it. This is a natural extension of
`judged-docs-config-consistency`.

The two "partial" entries are recorded as matters of quality, not absence:
`final-phase-submission-limit` verifies the submission *count* but not that the
final phase is *code-submission* (item 9), and `two-phase-structure` is a
necessary but not sufficient proxy for a sequestered private test (item 2).

### 5.2 The gaps are a consequence of the epistemic contract

The coverage pattern is not arbitrary; it follows directly from the contract of
Section 2. Items decidable from the configuration are realised as deterministic
checks. Items requiring the raw data and a training run — per-feature leakage,
split granularity — are realised either as attestations, where no proxy exists in
the bundle, or remain unimplemented, where a proxy exists but has not been built.
Items that are human or legal facts — external review, prize legality — are
attestations of necessity. The validator does not attempt to automate what it
cannot observe; it instead renders the unobservable explicit and the observable
executable. The gaps in Table 5 are therefore a faithful map of the boundary
between what a pre-launch artefact reveals and what only the data, a training
run, or a human can establish.

---

## 6. Limitations and scope boundaries

The coverage gaps of Section 5 concern individual items of the design checklist.
This section addresses a larger question: which *classes* of real failure lie
outside the reach of the approach altogether. The discussion is grounded not in
the literature but in the difficulties that organisers report in practice — the
2025 DataCamp debrief (Section 4.1) and a set of stakeholder interviews with
experienced Codabench organisers (internal field notes, 2026). The recurring
theme across that evidence is that the majority of reported pain is *operational*,
*longitudinal*, or *population-level*, whereas the object this work validates is
a *static bundle artefact* inspected *once*, *before any participant exists*. The
limitations below follow directly from that mismatch, and we state them as
properties this work does **not** attempt to solve.

**(L1) Run-time worker reliability and submission liveness.** The single most
emphasised failure in the interviews is that submissions fail or hang in a
pending state at run time — severe enough that one deployment engaged a dedicated
engineering team specifically to ensure that submissions would not fail or pend,
and repeatedly contacted organisers on each worker failure. The execution tier
(`baseline-execution`) establishes that the bundle's scoring pipeline *can*
execute in the declared image on a single host at validation time; it cannot
establish that the live queue will provision a worker, that the worker will not
stall, or that transient infrastructure faults will not terminate a submission
mid-run. The requested remedy — a server-originated status channel that reports
"the worker could not be reached; your submission is dead" — is a property of the
running platform, not of the artefact, and is outside scope.

**(L2) Live phase migration.** Organisers report that transitioning between
phases is a persistent source of trouble, and explicitly request a facility to
*test the migration* before it occurs. The validator verifies that a development
and a final phase are *declared* (`two-phase-structure`) and that phase dates
parse (`dev-phase-duration`), but it does not exercise the live migration: the
swap to the sequestered test data, the re-computation of the leaderboard on the
private set, and the date-gated transition itself. Validating a static
configuration is not equivalent to rehearsing a stateful, time-triggered
platform operation, and we do not attempt the latter.

**(L3) Population-level and longitudinal properties: cheating, overfitting, and
probing.** Several reported concerns — detection of duplicate accounts,
identification of cheaters by anomalously high submission counts, in-flight
detection of leaderboard overfitting, and enforcement of disqualification once a
submission quota is exceeded — are intrinsically defined over a *population of
participants* and a *time series of submissions*. None of these objects exists at
validation time. The validator can surface design-time preventive levers (the
submission caps and two-phase structure of Section 3.2) and can verify that a
disqualification rule is *documented*, but it can neither detect nor enforce the
behaviours in question. No pre-launch inspection of an artefact can observe
conduct that comes into being only after launch.

**(L4) Data-intrinsic correctness.** The properties of greatest scientific
consequence — the absence of feature, entity, and processing leakage; the
alignment of the train/test split with the unit of generalisation; and the
appropriateness of the metric to the class balance — require the *raw data* and,
in the leakage case, a *training run* on candidate features. The validator does
not ingest or audit the dataset itself; it relegates leakage to a human
attestation (`attest-leakage-probe`) and leaves the split-granularity and
class-balance facts (`unit_of_generalization`, `task_type`) unconsumed
(Section 5.1). A partial deterministic proxy — identifier disjointness across the
splits a bundle ships — is attainable (Section 4.3) but unimplemented; the full
probe is not addressable from the artefact alone.

**(L5) Scientific merit of the task and metric.** The validator checks that a
ranking direction is declared (`leaderboard-sorting`), that the pages do not
contradict the configuration (`judged-docs-config-consistency`), and that a
scorer executes (`baseline-execution`); it does not, and does not attempt to,
judge whether the metric is the *right* metric for the task, whether the task is
non-trivial, or whether a competition is the appropriate instrument at all. These
are the questions the literature assigns to external proposal review (Ch. 2), and
the validator accordingly defers them to a human attestation
(`attest-external-review`) rather than simulating a verdict it cannot justify.
One interview corroborates the failure mode this guards against — an experienced
organiser who, by his own account, configured a competition for result
submission having forgotten to consider code submission — but the remedy for
forgotten design decisions is review and authoring guidance, not artefact
validation.

**(L6) Identity, collaboration, and access control.** A substantial share of
reported friction concerns account- and identity-level features: management of
collaborators, submission limits that differ inside and outside a collaboration,
domain-restricted enrolment (for example, admitting any address from a given
university by pattern), and the burden of phone-based verification. These have no
representation in the bundle artefact and are properties of the platform's
account and authorisation model. They are entirely outside the scope of a bundle
validator.

**(L7) Live platform operations via API.** Organisers request the ability to
*update* a running competition from a whole bundle (rather than instantiating a
new one on each upload), to submit on a participant's behalf as an administrator,
and to simulate submissions for testing. This work provides a one-shot upload
utility for a validated bundle; it does not implement incremental or differential
update of a live competition, administrative submission, or live-submission
simulation. These are platform-API operations on a running competition, distinct
from pre-launch validation of an artefact, and are not attempted here.

**(L8) Statistical guarantees and robustness of evidence.** Two further limits
bound the strength of even the evidence the validator does produce. First, the
statistical-rigour items of Section 5 — confidence intervals on baseline scores,
significance testing between top entries, multi-seed ranking, and filtering of
sub-baseline submissions — are not implemented. Second, the execution oracle runs
*one* baseline, *once*, on *one* host (architecture fit is reported but may be
emulated). It is therefore existence evidence — a score was produced — rather
than a guarantee of robustness across the submission distribution, across
hardware, or under concurrent load, and it does not measure or enforce the
resource envelope (memory ceiling, wall-clock limit, accelerator availability)
that the literature recommends documenting (Ch. 11, Ch. 13).

Taken together, L1–L8 describe a single boundary. The validator is a static, and
optionally single-execution, inspection of an artefact conducted before launch;
the failures it cannot address are those that are constituted by the running
platform (L1, L2, L7), by the participant population over time (L3), by the raw
data (L4), by human scientific judgement (L5), by the identity system (L6), or by
statistical aggregation over many runs (L8). We regard the explicit statement of
this boundary as a requirement of the methodological contract of Section 2: a
tool that draws the limit of what it can establish is more trustworthy than one
that obscures it.

---

## 7. Conclusion

The `autocodabench validate` command operationalises the competition-design
literature as a tiered, cited, and partly executable checklist whose every gating
verdict is reproducible and whose every advisory is sourced. Evaluated against a
215-participant deployment, its execution tier addresses the bundle-side fraction
of the field's most frequently reported failure — submission failures arising
from bundles that do not execute — while the complementary run-time fraction,
worker reliability and submission liveness, remains outside its reach by
construction (Section 6, L1); and its local-validation premise removes most of
the demand for the platform's absent differential-upload workflow. Evaluated against the
official Codabench template, it renders explicit the otherwise-invisible gap
between a runnable bundle and a well-designed competition. Evaluated against
MLE-bench, it shares a commitment to executable correctness oracles while
addressing the complementary problem of validating novel rather than curated
competitions, and it inherits two concrete improvement targets: golden-score
regression on the shipped baseline, and partial automated leakage auditing.

Against the canonical sixteen-item best-practice checklist the validator covers
eleven items and is explicit about the five it does not, of which two —
`unit_of_generalization` and `task_type` — are already provisioned in the fact
schema and await only the checks that would consume them. That residual
constitutes the clearest near-term development agenda. Stating it plainly is
itself part of the methodological contract this report exists to uphold: a
validator earns trust not by asserting completeness, but by drawing the boundary
of what it has proven.

---

## References

Chan, J., et al. *MLE-bench: Evaluating Machine Learning Agents on Machine
Learning Engineering.* OpenAI. Repository and accompanying documentation
(Section 4.3).

Gebru, T., et al. *Datasheets for Datasets.*

Letournel, A.-C., & Moreau, T. (2026). Field debrief, "REX dataCamp 2025 on
Codabench usage." Laboratoire Interdisciplinaire des Sciences du Numérique
(LISN) and Institut Polytechnique de Paris (Section 4.1).

Stakeholder interviews with experienced Codabench organisers (internal field
notes, 2026), recording operational difficulties with worker reliability, phase
migration, collaboration and access control, and live-update workflows
(Section 6).

Pavão, A., et al. (2024). *AI Competitions and Benchmarks: The Science Behind the
Contests.* Chapter handles (Ch. *N*) throughout reference this volume, via the
project's `competition-design` knowledge module
(`src/autocodabench/skills/competition-design/SKILL.md`). Principles attributed
to Donoho (2017, the Common Task Framework), Roelofs et al. (2019, leaderboard
overfitting), and Blum & Hardt (2015, the Ladder mechanism) are cited as they
appear within this volume and the design module.

Codabench bundle schema, `Yaml-Structure.md` (platform documentation); the
official Codabench bundle template (Section 4.2).

Companion documents: [`verification-catalog.md`](./verification-catalog.md);
[`scientific-validation.md`](./scientific-validation.md).
```

