# Book-derived additions to the validation framework: high-value checks and a protocol-conditioning axis

**Abstract.** This addendum records a second, closer reading of Pavão et al.
(2025), *AI Competitions and Benchmarks: The Science Behind the Contests*,
undertaken specifically to identify checkable pre-launch properties not yet
reflected in the design proposal
([`validation-checklist-proposal.md`](./validation-checklist-proposal.md)). It is
deliberately scoped: of the roughly sixty candidate properties surfaced across
Chapters 2–5 and 11–13, this document advances only the high-value core — those
that are concretely computable from a static bundle artefact (or a declared fact,
or an execution probe the existing runner already supports), that correspond to a
documented real-world failure, and that the proposal does not already cover. We
make four contributions. First, and most consequentially, we propose a *third
classifying axis* — the competition **protocol type** — derived from the
per-protocol requirement matrix of Chapter 12, which both activates
protocol-specific requirements and suppresses spurious failures, and which
directly addresses the legibility problem that motivates the present work.
Second, we add a family of deterministic **structural lints** drawn from the
platform tutorial of Chapter 11, which catch the upload-time failures organisers
most frequently encounter. Third, we add a **scorer-robustness probe** under
degenerate input, from the judging analysis of Chapter 4. Fourth, we add a
**file-property leakage family** from the dataset-development material of
Chapters 2 and 3, covering leakage channels the proposal's split- and
target-based checks do not reach. Each addition is recorded with its chapter and
page provenance, its tier, its gating behaviour, and its relationship to an
existing or proposed check. No implementation is described; this is a design
specification, and the closing sections delimit what each addition cannot
establish and how each maps to a seeded defect in the validate-bench.

This addendum is a companion to, and does not supersede, the design proposal. It
assumes the proposal's two-axis taxonomy (six validation dimensions D1–D6 crossed
with the epistemic tiers), its five design principles, and the limitations
L1–L8 of [`validation-provenance-and-positioning.md`](./validation-provenance-and-positioning.md).
Chapter handles (Ch. *N*) and page numbers reference Pavão et al. (2025).

---

## 1. Scope and relationship to the proposal

The proposal derived an approximately forty-five-check catalog from a stated
standard of completeness — the sixteen-item smell test, the three leakage
categories, and the seven design sections. A second reading of the source
confirms that the proposal's backbone is faithful, but that three bodies of
material in the book are under-exploited: the platform-specific bundle mechanics
of the hands-on tutorial (Ch. 11), the metric- and ranking-correctness analysis
of the judging chapter (Ch. 4), and the protocol taxonomy of Chapter 12. The
present document advances the subset of that material meeting all three
admission criteria stated in the abstract; the remainder — governance
attestations, accessibility and equity declarations, post-challenge plans,
statistical-significance items requiring a submission population, and leakage
channels requiring a training run — is recorded as surveyed but deferred, and is
noted in Section 7 where it bears on the boundary of the approach.

The additions below are organised as the proposal's catalog is: by the property
verified, the tier, the gating behaviour, the inputs read, and a *novelty*
marker — **NEW** for a property no existing or proposed check addresses, or
**EXTENDS** `<check-id>` where it sharpens one.

---

## 2. A protocol-conditioning axis

### 2.1 Motivation

The proposal classifies each check by *dimension* and *tier*. Chapter 12 ("Special
designs and competition protocols", Tu & Pavão) demonstrates that a third
attribute is latent in many checks: the **protocol type** of the competition.
Table 1 (p. 289) is, in effect, a per-protocol requirement matrix — for each of
the supervised, AutoML, metalearning, time-series, reinforcement-learning,
adversarial, and confidential-data protocols, it records which of {shipped data,
multiple tasks, code submission, interactive design} is *mandatory* and which is
*conditional*.

We propose that `competition_type` be declared as a fact and that checks be
gated on it. This serves two purposes that a flat catalog cannot. It **activates**
requirements that apply only under a given protocol — for instance, that an
AutoML or metalearning competition must ship multiple tasks and must be a
code-submission competition (p. 289), or that a metalearning competition must
express meta-training and meta-test as two sequential phases (p. 280). And it
**suppresses** failures that do not apply — for reinforcement-learning,
confidential-data, and adversarial competitions, Table 1 marks shipped data as
*conditional*, so a validator that unconditionally required a shipped test set
would wrongly fail a valid bundle of those types.

The second effect is the direct remedy for the legibility concern that motivates
this whole line of work. By scoping the report to the checks a competition's
declared type actually implicates, an organiser is shown the requirements
relevant to their design rather than the union of all requirements across all
designs. The protocol axis therefore *reduces* the number of checks any single
competition sees, even as it increases the catalog's total size.

### 2.2 The requirement matrix

We propose recording the matrix of Table 1 (p. 289) as declarative data and
deriving from it a single check — `protocol-requirements` — that, given a
declared `competition_type`, asserts the mandatory components are present and
relaxes the conditional ones. The matrix as the book states it:

**Table A.** *Per-protocol mandatory ( + ) and conditional ( ~ ) bundle components
(after Pavão et al. 2025, Table 1, p. 289).*

| Protocol | Data shipped | Multiple tasks | Code submission | Interactive |
|----------|:---:|:---:|:---:|:---:|
| Supervised | + | ~ | ~ | ~ |
| AutoML | + | + | + | ~ |
| Metalearning | + | + | + | ~ |
| Time series | + | ~ | ~ | ~ |
| Reinforcement learning | ~ | ~ | + | + |
| Adversarial | ~ | ~ | ~ | + |
| Confidential data | ~ | ~ | ~ | ~ |

### 2.3 Two conditional families

Two protocols carry enough internal structure to warrant a small family of
gated checks rather than a single matrix assertion.

The **reinforcement-learning family** (Ch. 12, pp. 281–284), gated on
`competition_type == reinforcement_learning`:

- *`rl-environment-present`* — the simulator or environment ships in the bundle
  (or is pinned in the declared image) and can be instantiated and stepped once
  in a smoke run. The chapter is explicit that "the quality of environment
  determines the quality of the whole competition" (p. 282). Tier: deterministic
  (presence) with an execution probe. Novelty: NEW.
- *`rl-budget-in-steps`* — the per-episode and total compute budget is expressed
  in **environment steps, not wall-clock seconds**, so evaluation is invariant
  across hardware (p. 282); and a fixed evaluation-run count is declared (the
  NetHack design used 512 development runs and 4 096 final runs, p. 284). Tier:
  deterministic over a declared fact. Novelty: EXTENDS the proposal's
  `resource-envelope` with a protocol-specific unit.

The **confidential-data family** (Ch. 12, pp. 287–289), gated on a declared
`data_confidential` fact with a `confidential_mode ∈ {synthetic, blind_on_real}`:

- *`confidential-blind-no-shipped-data`* — when `blind_on_real`, the bundle ships
  **no real test data** (it resides on organiser-owned workers the platform
  cannot read, p. 289), an **output-log size cap** is declared to prevent
  leakage of sensitive data through logs (p. 289), and a sample/artificial
  dataset plus a baseline are shipped so participants can develop without the
  real data (p. 289). Tier: deterministic for the structural assertions,
  attestation for worker ownership. Novelty: NEW; the output-log cap in
  particular is a concrete anti-leakage check with no analog in the proposal.
- *`confidential-synthetic-utility-privacy`* — when `synthetic`, the author
  attests that both the *utility* (resemblance to real data) and the *privacy*
  (non-leakage of real points) of the generator were evaluated (p. 288). Tier:
  attestation. Novelty: NEW.

A third, cross-cutting check follows from the same chapter and the supervised
protocol (pp. 277, 279) and aligns precisely with the repository's existing
data-isolation invariant:

- *`code-submission-label-isolation`* — for any code-submission protocol, the
  directory the submitted code reads must contain features only; the test labels
  must reside solely on the scoring side. The chapter states that "participants
  must not have access to the test data … the final evaluation … conducted
  blindly … through the submission of code" (p. 279). Tier: deterministic
  (filesystem inspection of the input versus reference split). Novelty: NEW;
  closely related to the proposed `target-absent-from-public-test` but distinct
  in that it concerns the *runtime input directory* exposed to submitted code,
  not the public test files.

---

## 3. Structural lints from the platform tutorial

Chapter 11 ("Hands-on tutorial", Pavão) is the book's only direct account of the
Codabench bundle's mechanics, and it yields deterministic checks that catch the
upload-time failures organisers most frequently encounter. These are the
cheapest additions in this document and the most reliably mutate-testable.

- *`archive-entry-points-at-root`* — submission and program archives must be
  zipped **without a wrapping directory**, with the entry-point file (e.g.
  `metadata`) at the archive root. The chapter identifies this as the single
  most common mistake: "It is important to zip the files without directory
  structure" (p. 267). Tier: deterministic (inspect archive entries). Novelty:
  NEW.
- *`leaderboard-well-formed`* — each leaderboard declares a non-empty `key`;
  **exactly one** column is marked the primary (ranking) column — neither zero
  nor several; each aggregate column declares a computation and an `apply_to`
  list whose referenced sub-columns all exist; and the submission rule is a valid
  enumeration value (`Force Last` or `Add And Delete Multiple`) (pp. 272–273,
  Fig. 17). Tier: deterministic. Novelty: NEW (the proposal's
  `scores-leaderboard-mapping` checks that scorer outputs and column keys agree,
  but not the primary-column cardinality, the required key, or the
  aggregate-reference resolution).
- *`reference-data-not-participant-visible`* — files in the hidden reference
  (ground-truth) role must not also appear in the participant-visible public-data
  or input-data roles, nor in a starting-kit-embedded copy of the bundle. The
  chapter defines the reference data as "kept hidden to the participants, making
  it only accessible by the scoring program" (p. 263) and notes that a
  bundle-in-the-kit must be shipped "without the ground truth" (p. 264). Tier:
  deterministic (cross-role filename and content-hash diff). Novelty: NEW; a
  structural complement to the proposed leakage family and a natural fit with the
  repository's data-leakage invariant.
- *`referenced-assets-resolve`* — every referenced asset exists: the logo file
  (conventionally `logo.png`), every declared HTML or Markdown page, and a
  well-formed Docker image reference carrying an **explicit tag** rather than an
  implicit `latest`, which the chapter ties to reproducibility — "every candidate
  is judged in the same way, the competition does not get deprecated" (pp. 263,
  265). Tier: deterministic; runs without a Docker daemon, complementing the
  existing `docker_preflight`. Novelty: EXTENDS the structural decomposition of
  `bundle-schema`.
- *`submission-layout-consistent`* — the presence of an ingestion program
  implies a code-submission sample (which must itself carry a `metadata` file at
  its root), and its absence implies a result-submission sample (pp. 263, 267).
  Tier: deterministic. Novelty: EXTENDS the proposed
  `final-phase-code-submission` from a methodological declaration to a structural
  cross-check between the ingestion program and the shipped sample.

---

## 4. Scorer robustness under degenerate input

Chapter 4 ("How to judge a competition", Pavão) repeatedly notes that common
metrics are fragile on degenerate inputs — accuracy and precision/recall break
under a single predicted class, R² is undefined at zero target variance (p. 112),
and ratio-based fairness metrics divide by a group rate that can be zero
(p. 116). A scoring program that crashes, returns NaN or ±∞, or silently inflates
on such inputs is a latent launch defect that `baseline-execution` cannot detect,
because the baseline produces a well-formed prediction.

- *`scorer-degenerate-input-robust`* — feed the scoring program a battery of
  synthetic prediction files — all-one-class, constant-valued, empty,
  containing NaN or ±∞, and out-of-range (for example a probability exceeding
  one) — and assert that it returns a finite, in-range score or raises a cleanly
  handled error, and in no case produces an uncaught exception, a NaN on the
  leaderboard, or an inflated score. Tier: deterministic with execution
  (single-baseline, no submission population required). Novelty: EXTENDS the
  proposed `scorer-sensitivity` from a non-constancy test to an adversarial
  edge-case test.

A closely related and equally cheap deterministic addition from the same chapter
concerns non-monotone metrics:

- *`metric-interior-optimum-sort`* — for a metric whose optimum lies at an
  interior point rather than an extremum — the canonical case being the
  adversarial-accuracy metric of generative-privacy tasks, whose ideal value is
  0.5, not 1.0 (p. 118, Fig. 3) — neither ascending nor descending leaderboard
  sorting is correct; the column must rank by distance to the declared optimum.
  Tier: deterministic over a declared `metric_optimum` fact. Novelty: EXTENDS the
  proposed `metric-direction-semantics`, which assumes a monotone metric.

---

## 5. The file-property leakage family

The leakage material of Chapter 2 (Appendix C, pp. 58–59) and Chapter 3
(pp. 70–92) describes leakage channels that the proposal's identifier-disjointness
and target-absence checks do not reach, and several are statically computable
from the data the bundle already ships. The unifying observation is that
information about the target can leak through the *physical encoding* of the data
rather than its content.

- *`file-property-leakage-probe`* — for a bundle whose data are files (notably
  images or audio), test whether the target is predictable from file properties
  alone: size on disk, image resolution or encoding, tokens or timestamps
  embedded in filenames, and filesystem modification times. The chapter documents
  the canonical real-world instance, a whale-detection competition in which an
  AUROC of 0.997 was obtained from size-on-disk and a filename timestamp alone
  (Ch. 3, p. 88; Ch. 2, p. 58). Tier: deterministic (compute a separability
  statistic between each property and the label on the labelled splits). Novelty:
  NEW.
- *`embedded-metadata-stripped`* — image files carry no embedded metadata (EXIF
  camera make and model, capture timestamp, GPS) that could correlate with the
  target; the chapter advises that files "be stripped of any associated
  metadata, especially with images" (Ch. 3, p. 70). Tier: deterministic (parse
  headers; flag non-empty metadata). Novelty: NEW.
- *`record-order-non-informative`* — the order of records or files reveals
  nothing about the target: row index does not correlate with the label, files
  are not saved class-by-class, and ties are not broken in label order. The
  chapter cites both the image case ("all cat images saved first, followed by dog
  images … files should be randomized", Ch. 2, p. 59) and the tabular tie-break
  case from the TalkingData competition (Ch. 3, p. 79). Tier: deterministic
  (runs test or rank correlation of index against label). Novelty: NEW.

These three are the statically detectable subset of the chapter's leakage
catalog. The chapter's other channels — preprocessing statistics fit on the
combined train-and-test data, and background or context features that predict the
class — are detectable only with a training run and are therefore out of scope as
deterministic gates (Section 7).

---

## 6. Provenance summary

**Table B.** *The high-value core, with source provenance, tier, and novelty. Tier
abbreviations as in the proposal: det = deterministic, exec = deterministic with
execution, attest = attestation. Gating "cond." denotes a verdict conditional on a
declared fact or protocol per proposal principle 3.*

| Proposed check | §  | Tier | Gate? | Provenance |
|----------------|:--:|------|-------|------------|
| `protocol-requirements` | 2.2 | det | cond. | Ch. 12, Table 1, p. 289 |
| `rl-environment-present` | 2.3 | exec | cond. | Ch. 12, pp. 281–282 |
| `rl-budget-in-steps` | 2.3 | det | cond. | Ch. 12, pp. 282, 284 |
| `confidential-blind-no-shipped-data` | 2.3 | det | cond. | Ch. 12, pp. 288–289 |
| `confidential-synthetic-utility-privacy` | 2.3 | attest | no | Ch. 12, p. 288 |
| `code-submission-label-isolation` | 2.3 | det | cond. | Ch. 12, pp. 277, 279 |
| `archive-entry-points-at-root` | 3 | det | yes | Ch. 11, p. 267 |
| `leaderboard-well-formed` | 3 | det | yes | Ch. 11, pp. 272–273 |
| `reference-data-not-participant-visible` | 3 | det | yes | Ch. 11, pp. 263–264 |
| `referenced-assets-resolve` | 3 | det | yes | Ch. 11, pp. 263, 265 |
| `submission-layout-consistent` | 3 | det | yes | Ch. 11, pp. 263, 267 |
| `scorer-degenerate-input-robust` | 4 | exec | yes | Ch. 4, pp. 112, 116, 118 |
| `metric-interior-optimum-sort` | 4 | det | cond. | Ch. 4, p. 118 |
| `file-property-leakage-probe` | 5 | det | no | Ch. 3, p. 88; Ch. 2, p. 58 |
| `embedded-metadata-stripped` | 5 | det | no | Ch. 3, p. 70 |
| `record-order-non-informative` | 5 | det | no | Ch. 3, pp. 59, 79 |

---

## 7. Caveats and validity boundaries

Three qualifications constrain the foregoing, and are stated explicitly so that
the additions are not read as more than they are.

First, **exact platform field names require confirmation.** Chapter 11 names the
bundle's files and form fields — `competition.yaml`, the program `metadata`
file, `logo.png`, the leaderboard `key`, primary column, computation, and
submission rule, and the public/input/reference data roles — but it is a
walkthrough and rarely prints the exact YAML key spellings. The *constraints*
recorded in Section 3 are sound; their *encoding* must be confirmed against the
Codabench bundle schema before implementation. This is a translation risk, not a
substantive one.

Second, **two protocol checks rest on inference rather than direct statement.**
The book does not explicitly mandate fixed random seeds for stochastic
reinforcement-learning environments, nor explicitly prohibit network access for
sandboxed code submission; both follow from the chapter's reproducibility and
isolation language but are not stated verbatim. They are therefore omitted from
the core of Section 2 and would, if added later, be advisory rather than gating.

Third, **the deferred material is deferred for cause.** The leakage channels that
require a training run — preprocessing leakage and background predictivity
(Ch. 3) — and the ranking-stability and winner-significance analyses that require
a population of submissions (Ch. 4, pp. 125–131) fall under the proposal's
limitations L3, L4, and L8 and are not deterministic gates. The governance,
accessibility, and post-challenge-plan attestations surveyed in Chapters 5 and 13
are admissible as attestation-tier checks but were excluded from this core on the
scope criterion, not on validity; they remain available for a later governance
expansion.

---

## 8. Mapping to the validate-bench

Every deterministic addition in Section 6 corresponds to a clean seeded defect in
the validate-bench instrument (`benchmark/autocodabench_validate_bench/`), and
none requires the checking agent to read ground truth — preserving the
data-leakage isolation that is a code invariant of the benchmark. Indicative
mutations of a clean bundle, each isolating one check:

- re-zip a program or sample submission inside a wrapping directory
  (`archive-entry-points-at-root`);
- mark two leaderboard columns as primary, or reference a non-existent
  sub-column in an aggregate (`leaderboard-well-formed`);
- copy a reference-data label file into the public-data role
  (`reference-data-not-participant-visible`);
- delete the referenced logo, or pin the image to an implicit `latest`
  (`referenced-assets-resolve`);
- introduce a scorer that returns NaN on an all-one-class prediction
  (`scorer-degenerate-input-robust`);
- set the leaderboard sort ascending on an accuracy metric, or descending on an
  interior-optimum metric (`metric-interior-optimum-sort`);
- rename test files so a class token or a monotone timestamp predicts the label,
  or leave EXIF capture data in the images (`file-property-leakage-probe`,
  `embedded-metadata-stripped`);
- save the test files class-by-class so file order predicts the label
  (`record-order-non-informative`).

Each defect yields a per-check catch-rate, making "the validator detects this
flaw" an executable and measured result rather than a claim, in keeping with the
discipline the proposal applies to the existing suite.

---

## References

As in [`validation-checklist-proposal.md`](./validation-checklist-proposal.md)
and [`validation-provenance-and-positioning.md`](./validation-provenance-and-positioning.md):
Pavão, Guyon and Viegas, eds. (2025), *AI Competitions and Benchmarks: The
Science Behind the Contests* — in this addendum, Chapters 2 (Challenge design
roadmap, incl. Appendix C), 3 (Dataset development), 4 (How to judge a
competition), 5 (Towards impactful challenges), 11 (Hands-on tutorial), 12
(Special designs and competition protocols, Tu & Pavão), and 13 (Practical
issues). The Codabench bundle schema and the official Codabench template.
