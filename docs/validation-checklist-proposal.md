# Toward a systematic pre-launch validation framework for Codabench competition bundles: a design proposal

**Abstract.** The `autocodabench validate` command currently applies nineteen
checks to a Codabench competition bundle before launch. Each check is
individually sourced to the competition-design literature or the platform
schema, but the set as a whole accreted incrementally and was never derived from
a stated standard of completeness; consequently the proportion of checkable
pre-launch properties that are in fact checked is presently unknown. This report
proposes a systematic reconstruction of the validation framework. We make three
proposals. First, we introduce a two-axis taxonomy — six *validation dimensions*
crossed with the existing *epistemic tiers* — under which every check is
classified, rendering structural gaps in coverage visible as unpopulated cells
of a matrix. Second, we derive from that taxonomy the full set of checks it
implies, comprising the nineteen existing checks (four proposed for refactoring)
and approximately thirty-five newly proposed checks, each specified by the
property it verifies, its tier, its gating behaviour, its required inputs, and
its citation. Third, we propose structural changes to the framework itself — a
declarative check specification crossed with three classifying axes (validation
dimension, epistemic tier, and competition protocol), an enforced fact-schema
contract, a conditional-gating mechanism, and an executable completeness
invariant — that make the suite self-describing and auditable against a named
standard. We state
explicitly, throughout, the classes of failure the framework does not attempt to
address, so that an expanded suite does not create the impression of solving
problems it structurally cannot. No implementation is described here; the report
is a design specification.

This proposal is the forward-looking companion to
[`validation-provenance-and-positioning.md`](./validation-provenance-and-positioning.md),
which catalogs the present nineteen checks, formalises the three-tier epistemic
contract, and enumerates the limitations (L1–L8) of validating a static bundle
artefact. Familiarity with that document is assumed; in particular, the
deterministic / judged / attestation tiers, the declare-then-verify fact
side-channel, and the limitations are taken as given. The evidentiary basis is
likewise shared: Pavão et al. (2024) as the design standard, the MLE-bench
correctness machinery as an adjacent reference, and the 2025 École Polytechnique
DataCamp debrief together with organiser stakeholder interviews (internal field
notes, 2026) as the record of empirical failure. Chapter handles (Ch. *N*)
reference Pavão et al.

---

## 1. Introduction

A pre-launch validator is useful in proportion to two properties: the fraction
of real failure modes its checks cover, and the trustworthiness of the verdicts
it issues. The companion document established the second property for the present
suite — every gating verdict is reproducible and cited — but left the first
unquantified. The provenance analysis additionally surfaced concrete deficiencies:
the most consequential data-leakage failures are delegated in their entirety to a
single human attestation; the official platform template's own
ascending-sorted-accuracy configuration would pass undetected; and two entries of
the fact schema, `unit_of_generalization` and `task_type`, are declared yet
consumed by no check.

These observations motivate a reconstruction rather than a piecemeal extension.
The objective of this report is to specify a framework in which the set of checks
is *derived* from an explicit standard of completeness, in which coverage is
*measurable* rather than asserted, and in which the boundary of what the approach
can establish is *declared* rather than implicit. Section 2 presents the
classifying taxonomy. Section 3 states the principles that constrain the
expansion. Section 4 presents the full proposed catalog, organised by dimension.
Section 5 reports the projected coverage. Section 6 specifies the refactoring of
existing checks. Section 7 proposes the structural changes to the framework.
Section 8 delimits the non-goals. Sections 9 and 10 address validation of the
framework and a suggested order of implementation. Section 11 re-derives the
coverage of Section 5 against an external standard — the published
challenge-proposal template — and specifies the template-driven checks that
expansion implies.

---

## 2. A two-axis taxonomy

We propose that every check be classified along two orthogonal axes, and that
this classification be declared in code (Section 7.1) rather than left implicit
in prose.

**Axis A — the validation dimension** identifies the kind of correctness at
stake and the object inspected. We propose six dimensions, intended to partition
the space of checkable pre-launch properties exhaustively:

- **D1 — Structural integrity.** The bundle parses, uploads, and is internally
  consistent. The object is the configuration and file tree; the standard is the
  Codabench schema.
- **D2 — Executable correctness.** The bundle executes and produces the scores it
  claims, reproducibly, within its declared resource envelope. The object is the
  bundle run in its declared image.
- **D3 — Methodological design.** The phase structure, submission economy,
  protocol level, and test-set sizing conform to the design literature. The
  object is the configuration interpreted against design rules.
- **D4 — Data integrity and leakage.** The data splits are disjoint, match the
  unit of generalisation, and do not expose the target; the metric suits the
  data. The object is the reference and input data, together with declared facts
  about it.
- **D5 — Documentation and consistency.** The participant-facing text is
  complete, unambiguous, and free of contradiction with the configuration. The
  object is the pages interpreted against the configuration.
- **D6 — Governance, ethics, and sustainability.** Review, datasheet, licensing,
  persistence, privacy, and prize legality. The object is the set of facts only a
  human can certify.

**Axis B — the epistemic tier** identifies who computes the verdict and whether
it may gate a launch. It is unchanged from the present framework: *deterministic*
(gates), *deterministic with execution* (gates; requires running the bundle),
*judged* (advisory), and *attestation* (human-only). As argued in the companion
document (§5.2), the tier of a check is not a free choice but is forced by the
nature of the property under inspection.

The taxonomy's purpose is diagnostic. The (dimension × tier) matrix exposes
structural gaps directly: a dimension with no deterministic members, or a
best-practice criterion with no covering check, appears as an empty cell. Each
check additionally carries a *design-section tag* — one of the seven Codabench
design sections the authoring phase already employs (task, data, metric,
baseline, rules, ethics, schedule) — for traceability to the authoring side, and
records its *citation* and *required inputs* (configuration, pages, data,
execution, or facts). These five attributes — dimension, tier, design section,
citation, and inputs — constitute the proposed *check specification* of
Section 7.1.

**Axis C — the protocol type.** A second reading of Pavão et al. (Ch. 12,
"Special designs and competition protocols") establishes that many checks are
implicitly conditional on the *protocol* of the competition — supervised,
AutoML, metalearning, time-series, reinforcement-learning, adversarial, or
confidential-data. Chapter 12's Table 1 (p. 289) is, in effect, a per-protocol
requirement matrix: it records, for each protocol, which of {shipped data,
multiple tasks, code submission, interactive design} is *mandatory* and which is
*conditional*. We propose recording this matrix as declarative data and gating
checks on a declared `competition_type` fact. This serves two ends a flat
catalog cannot. It *activates* protocol-specific requirements — an AutoML or
metalearning competition must ship multiple tasks and use code submission; a
reinforcement-learning competition must ship a runnable environment and express
its compute budget in environment steps rather than wall-clock seconds (p. 282).
And it *suppresses* false positives — for reinforcement-learning,
confidential-data, and adversarial protocols, Table 1 marks shipped data as
*conditional*, so a validator that unconditionally required a shipped test set
would wrongly fail a valid bundle. The second effect is the direct remedy for the
legibility problem that motivates this work: gating on protocol scopes the report
to the checks a competition's declared type actually implicates, and so *reduces*
the number of checks any single competition presents, even as it enlarges the
catalog. The protocol-conditional families (the reinforcement-learning and
confidential-data families in particular) and their provenance are specified in
the companion [`validation-checklist-proposal-addendum.md`](./validation-checklist-proposal-addendum.md),
Section 2.

---

## 3. Design principles

The following principles govern the selection and behaviour of the proposed
checks. Their purpose is to keep the expansion disciplined rather than maximal.

1. **Completeness is measured against a named standard, not asserted.** The
   coverage target is the union of (a) the sixteen-item pre-launch checklist of
   Pavão et al. (companion §5), (b) the three leakage categories of Ch. 3, and
   (c) the seven design sections. A check is justified by the named item it
   closes; an increase in the number of checks is not in itself an objective.

2. **A deterministic proxy is preferred to an attestation, and an attestation to
   silence.** Where a property is only partly observable from the artefact, a
   partial deterministic check that gates on the observable component is preferred
   to deferring the entire property to a human — for instance,
   split-identifier disjointness as a partial proxy for the full leakage probe.
   Where no component is observable, an explicit attestation is preferred to
   omission of the criterion.

3. **Gating may be conditional on declared facts.** A design weakness that is
   merely advisory in general may become an unambiguous defect once a fact is
   declared. We propose that a finding be permitted to *escalate to a gate* when a
   declared fact renders the defect certain — for example, a random split is a
   finding in general but a failure once `unit_of_generalization` is declared and
   the grouping variable is shown to straddle the split. The fact channel thereby
   *increases* rigour rather than merely unlocking advisories.

4. **Facts constitute a contract, not a convenience.** Every fact added to the
   schema must be consumed by at least one check; a declared-but-unconsumed fact —
   the present condition of `unit_of_generalization` and `task_type` — is treated
   as a defect of the framework itself.

5. **No check may claim what it cannot observe.** The limitations L1–L8 of the
   companion document are treated as non-goals (Section 8). No proposed check
   inspects the running platform, the participant population, or live phase
   migration; where a static proxy for a run-time concern exists — for instance,
   the coherence of the migration *configuration* — it is proposed explicitly as
   a proxy and labelled as such.

---

## 4. The proposed catalog

The catalog is organised by validation dimension. In each table, the status
column distinguishes existing checks proposed without change (E), existing checks
proposed for refactoring (R), and newly proposed checks (N); the dagger (N†)
marks checks implemented in the first build increment (Section 10.1). The tier column uses
*det* (deterministic), *exec* (deterministic with execution), *judged*, and
*attest*. The "Gate?" column indicates whether a negative verdict blocks launch,
possibly conditionally in the sense of principle 3. The "Inputs" column records
the objects the check reads. Identifiers for proposed checks are provisional.

### 4.1 D1 — Structural integrity

| id | St. | Verifies | Tier | Gate? | Inputs | Cite |
|----|-----|----------|------|-------|--------|------|
| `bundle-schema` | E | Configuration parses; referenced files exist; leaderboard keys are written by the scorer | det | yes | config | schema |
| `phase-task-references` | N | Every `phases[].tasks` index resolves to a declared task | det | yes | config | schema |
| `solution-task-wiring` | N | Each declared solution maps to a task on which the platform will run it | det | yes | config | schema; Ch. 5 |
| `scores-leaderboard-mapping` | N | Every leaderboard column key is produced by the scoring program, and conversely (no orphan columns, no unranked scores) | det | yes | config, code | schema; Ch. 4 |
| `leaderboard-well-formed` | N† | Each leaderboard declares a key; column keys and indices are unique | det | yes | config | Ch. 11 |
| `archive-entry-points-at-root` | N | Program and submission archives are zipped flat, with the entry-point file at the archive root | det | yes | bundle | Ch. 11 |
| `referenced-assets-resolve` | N | The logo and every declared page resolve; the docker image carries an explicit version tag | det | yes/cond. | config, bundle | Ch. 11 |

The present `bundle-schema` check already subsumes much of this dimension, but as
a single monolithic linter. We propose decomposing the structural concerns into
named checks, so that a failure identifies *which* structural invariant was
violated and so that the coverage matrix represents structural integrity as a
populated dimension rather than a single opaque gate. The underlying linter need
not change; only the granularity of its reporting increases.

### 4.2 D2 — Executable correctness

| id | St. | Verifies | Tier | Gate? | Inputs | Cite |
|----|-----|----------|------|-------|--------|------|
| `baseline-execution` | E | The baseline runs through ingestion and scoring in the declared image | exec | yes | execution | Ch. 5, 11 |
| `starting-kit-execution` | E | The starting-kit notebook executes cleanly | exec | no | execution | Ch. 5, 13 |
| `baseline-score-reproduction` | N | The shipped baseline reproduces a declared expected score within tolerance | exec | conditional | execution, facts | Ch. 11; MLE-bench |
| `scorer-sensitivity` | N | Perturbing the prediction alters the score (the scorer is neither constant nor input-insensitive) | exec | yes | execution | Ch. 4, 11 |
| `scorer-degenerate-input-robust` | N | The scorer returns a finite, in-range score or a cleanly handled error on degenerate predictions (all-one-class, constant, empty, NaN, out-of-range) — never an uncaught exception or a NaN on the leaderboard | exec | yes | execution | Ch. 4 |
| `scoring-determinism` | N | Two runs of the baseline yield identical scores (no hidden nondeterminism in scoring) | exec | no | execution | Ch. 11 |
| `baseline-ordering` | N | The competent baseline outranks the trivial baseline under the declared sorting | exec | no | execution | Ch. 5 |
| `resource-envelope` | N | Records baseline peak memory and wall-clock time, and compares them against declared limits where provided | exec | no | execution, facts | Ch. 11, 13 |

The check `baseline-score-reproduction` imports MLE-bench's golden-score
regression mechanism into the organiser's validator (companion §4.3): given a
declared `expected_baseline_scores` fact, it asserts that the bundle in fact
produces those scores, thereby detecting silent drift in the scoring program or
the data. The check `scorer-sensitivity` addresses a severe failure that
`baseline-execution` alone cannot — a scoring program that returns a constant or
ignores the submission executes without error — and `baseline-ordering` provides
the empirical complement to the static direction checks of D5: if the trivial
baseline outranks the competent one, the ranking direction is wrong in fact, not
merely in declaration.

### 4.3 D3 — Methodological design

| id | St. | Verifies | Tier | Gate? | Inputs | Cite |
|----|-----|----------|------|-------|--------|------|
| `two-phase-structure` | E | A development phase and a final phase are declared | det | no | config | Ch. 5, 11 |
| `dev-phase-duration` | E | The development phase spans at least ~40 days | det | no | config | Ch. 13 |
| `daily-submission-cap` | E | Development phases cap daily submissions (≈5–10) | det | no | config | Ch. 5 |
| `final-phase-submission-limit` | E | The final phase caps total submissions (≤3) | det | no | config | Ch. 5 |
| `test-set-size` | E | The 100/E sizing rule is satisfied | det | no | facts, data | Ch. 4 |
| `final-phase-code-submission` | N | The final phase requires code (γ) rather than result (λ) submission | det | conditional | config, facts | Ch. 5, 11 |
| `protocol-level-declared` | N | The protocol level (λ/α/β/γ) is declared and consistent with the presence of an ingestion program | det | no | config, facts | Ch. 2, 12 |
| `schedule-coherence` | N | Phase dates are expressed in UTC, monotonic, non-overlapping, and frozen | det | no | config | Ch. 13 |
| `migration-config-coherence` | N | The final phase references test data distinct from the development phase, and its window opens after the development window closes — a static proxy for the migration the validator cannot exercise live (L2) | det | no | config | Ch. 5 |
| `sub-baseline-filter-declared` | N | A policy excluding sub-trivial-baseline submissions from the final ranking is declared | judged | no | pages, config | Ch. 5, 11 |
| `public-leaderboard-fraction` | N | The public/private split fraction lies within a defensible range (the overfitting–feedback tension) | det | no | facts | Ch. 5 |

The checks `final-phase-code-submission` and `protocol-level-declared` close
companion smell-test item 9, which `final-phase-submission-limit` addresses only
by submission count, and respond directly to a documented field failure: an
experienced organiser who configured result submission having omitted code
submission entirely (companion §6, L5). The check `migration-config-coherence` is
the in-scope static response to the phase-migration difficulty organisers report
(L2): the validator cannot rehearse the live migration, but it can verify that
the configuration driving it is coherent. The check `sub-baseline-filter-declared`
closes item 11 at the level of documentation, the enforcement of the filter being
a platform responsibility (L3).

### 4.4 D4 — Data integrity and leakage

| id | St. | Verifies | Tier | Gate? | Inputs | Cite |
|----|-----|----------|------|-------|--------|------|
| `attest-leakage-probe` | E | Per-feature leakage was probed and excluded (human) | attest | no | — | Ch. 3 |
| `target-absent-from-public-test` | N | The public test files do not contain the label or target column | det | conditional | data, facts | Ch. 3; MLE-bench |
| `split-identifier-disjointness` | N | The train, public-test, and reference identifier sets are pairwise disjoint | det | yes | data | Ch. 3; MLE-bench |
| `split-matches-generalization-unit` | N | When `unit_of_generalization` is declared, the grouping variable does not straddle the train/test split | det | conditional | data, facts | Ch. 3, 4 |
| `metric-suits-class-balance` | N | When `task_type` is declared, the chosen metric is appropriate to it (e.g. not bare accuracy on an imbalanced task) | det | no | config, facts | Ch. 4 |
| `intrinsic-duplicate-scan` | N | Exact or near-duplicate records across splits are flagged (intrinsic leakage) | det | no | data | Ch. 3 |
| `reference-data-not-participant-visible` | N† | No reference (ground-truth) file appears, byte-for-byte, under a participant-visible role (`public_data`/`input_data`) | det | yes | data | Ch. 11, 3 |
| `file-property-leakage-probe` | N | The target is not predictable from file size on disk, image resolution, filename tokens/timestamps, or filesystem mtime | det | no | data | Ch. 3, 2 |
| `embedded-metadata-stripped` | N | Image files carry no embedded EXIF metadata (camera, timestamp, GPS) that could correlate with the target | det | no | data | Ch. 3 |
| `record-order-non-informative` | N | Record/file order does not encode the target (not saved class-by-class; ties not broken in label order) | det | no | data | Ch. 2, 3 |
| `sequestration-attested` | R | Private test labels are sequestered from the leaderboard server (human; presently implicit in `two-phase-structure`) | attest | no | — | Ch. 5, 11 |

This dimension is the largest deficiency of the present suite (companion §5.1)
and the principal divergence from MLE-bench (§4.3). The checks
`target-absent-from-public-test` and `split-identifier-disjointness` are the two
highest-value additions of this proposal: they convert the most catastrophic
leakage failures from a single human attestation into deterministic gates, and
both are computable from data the bundle already ships. The checks
`split-matches-generalization-unit` and `metric-suits-class-balance` are the first
to *consume* the two latent facts (principle 4), thereby closing smell-test items
4 and 13.

### 4.5 D5 — Documentation and consistency

| id | St. | Verifies | Tier | Gate? | Inputs | Cite |
|----|-----|----------|------|-------|--------|------|
| `judged-docs-config-consistency` | E | The pages do not contradict the configuration | judged | no | pages, config | Ch. 11, 13 |
| `external-data-rule` | R | The external-data policy is documented (deterministic component) and declared (fact); the present hybrid is split into two named checks | det | no | pages, facts | Ch. 5 |
| `leaderboard-sorting` | E | Each ranked column declares a sorting direction | det | no | config | Ch. 4; schema |
| `metric-direction-semantics` | N† | The declared sorting direction matches the known direction of the named metric (e.g. accuracy must not sort ascending) | det | no | config | Ch. 4 |
| `metric-interior-optimum-sort` | N | For a metric whose optimum is an interior point (e.g. adversarial-accuracy at 0.5), the column ranks by distance to the declared optimum, not plain asc/desc | det | cond. | config, facts | Ch. 4 |
| `scorer-shipped-to-participants` | N | A scorer identical to the leaderboard metric ships in the starting kit, eliminating local-versus-submission score disputes | det | no | bundle | Ch. 11 |
| `starting-kit-completeness` | R | The kit contains a loader, a dummy model, a training loop, a scorer, and a packager — not merely a non-empty folder | det | no | bundle | Ch. 5, 13 |
| `compute-envelope-documented` | N | The pages document the maximum RAM, wall-clock time, and accelerator availability | det | no | pages, facts | Ch. 11, 13 |
| `rules-completeness` | N | Disqualification criteria, the tie-break rule, and eligibility are stated before launch | judged | no | pages | Ch. 4, 13 |

The check `metric-direction-semantics` is the deterministic check that would have
detected the official template's ascending-sorted-accuracy configuration
(companion §4.2); it requires only a small metric-to-direction lookup table. The
check `rules-completeness` closes smell-test item 15 and extends the existing
judged rubric. The refactor `starting-kit-completeness` upgrades the present
file-count check to verify the kit's *contents*, which are the actual determinant
of sub-one-hour participation (item 1).

### 4.6 D6 — Governance, ethics, and sustainability

| id | St. | Verifies | Tier | Gate? | Inputs | Cite |
|----|-----|----------|------|-------|--------|------|
| `attest-external-review` | E | At least one external reviewer attempted the task | attest | no | — | Ch. 2 |
| `attest-datasheet` | E | A datasheet / data nutrition label is published | attest | no | — | Ch. 3 |
| `attest-data-persistence` | E | A license, persistent identifier, and post-competition home exist | attest | no | — | Ch. 3, 13 |
| `attest-game-of-skill` | E | Prize legality is confirmed (auto-passes when `prizes: false`) | attest | no | facts | Ch. 13 |
| `attest-privacy-budget` | N | For sensitive data, k-anonymity, differential privacy, or consent is established (auto-passes when data is declared non-sensitive) | attest | no | facts | Ch. 3, 12 |
| `attest-winner-reproducibility` | N | A policy requiring winners to submit reproducible code and a writeup before prize award is declared | attest | no | facts | Ch. 5, 13 |
| `attest-evergreen-plan` | N | A post-competition hosting plan (≥12-month leaderboard, archived scoring image) exists | attest | no | facts | Ch. 11, 13 |

These additions extend the human-attested tier to cover the privacy
(Ch. 3, 12), reproducibility (Ch. 5), and persistence (Ch. 13) criteria the
literature treats as launch requirements. Following the established
`attest-game-of-skill` pattern, each is fact-gated to resolve automatically when
inapplicable, so that the attestation burden scales with the competition's actual
exposure rather than being imposed uniformly.

---

## 5. Projected coverage

The proposal would expand the suite from nineteen to approximately fifty-five
checks. More consequentially, it would populate every cell of the
(dimension × tier) matrix and provide a covering check for every open item of the
best-practice checklist. Table 1 summarises the intended end-state.

**Table 1.** *Projected coverage by validation dimension.*

| Dimension | Det. | Exec. | Judged | Attest. | Smell-test items closed |
|-----------|------|-------|--------|---------|-------------------------|
| D1 Structural | 4 | — | — | — | (platform schema) |
| D2 Executable | — | 7 | — | — | 1, 6 |
| D3 Methodological | 9 | — | 1 | — | 2\*, 8, 9, 10, 11 |
| D4 Data and leakage | 5 | — | — | 2 | 3, 4, 13 |
| D5 Documentation | 6 | — | 2 | — | 1, 6, 15 |
| D6 Governance | — | — | — | 7 | 5, 12, 14, 16 |

(\* Item 2, sequestration of the private test set, remains an attestation; the
methodological checks supply only a structural proxy.)

All sixteen checklist items would then possess a covering check. The items that
remain attestation-only — item 3 in part, and items 5, 12, 14, and 16 — are
precisely those the limitations analysis identified as unobservable from the
artefact. This residual is the intended end-state rather than a deficiency.

Section 11 strengthens this projection by re-deriving coverage against an
*external* standard — the published challenge-proposal template — rather than the
internal (dimension × tier) matrix alone; the two agree on the end-state size
(~53–55 checks) by independent routes.

---

## 6. Refactoring of existing checks

Beyond the new checks, four existing checks (marked R in Section 4) are proposed
for refactoring. The intent is to systematise the suite rather than to alter any
verdict.

1. *Decompose `bundle-schema`* into the named structural checks of D1, so that
   structural failures are reported individually and the dimension is visibly
   populated. The underlying linter is unchanged; only its reporting granularity
   increases.
2. *Split `external-data-rule`* into its deterministic component (the pages
   mention the policy) and its fact component (the content of the policy), as two
   named checks in D5, eliminating the present hybrid that resists classification.
3. *Upgrade `starting-kit`* to `starting-kit-completeness`, verifying the kit's
   contents against the Ch. 5 component list rather than counting files.
4. *Make sequestration explicit* as `sequestration-attested`, rather than leaving
   it implicit within `two-phase-structure`, so that smell-test item 2 possesses
   a check of its own even though it must remain an attestation.

---

## 7. Systematisation of the framework

The set of checks is only half of the proposal; the framework itself must change
so that the set is self-describing and auditable against the standard of
principle 1.

### 7.1 Declarative check specifications

Each check should declare its five taxonomy attributes — dimension, tier,
design section, citation, and required inputs — as structured metadata rather
than prose. At present the tier and citation are class attributes, but the
dimension, design section, and inputs are implicit. With all five declared, three
capabilities follow. The `checks list` command could render the
(dimension × tier) coverage matrix directly from the registry rather than as a
flat enumeration. A *completeness invariant* could be asserted within the
keyless unit suite — that every checklist item, every leakage category, and every
design section maps to at least one registered check — thereby converting
"completeness against a named standard" from a documentary claim into an
executable test. And the report could group findings by dimension, which is more
legible to an organiser than the present ordering by severity alone.

### 7.2 The fact schema as an enforced contract

The expanded `CompetitionFacts` would introduce, in addition to the existing six
fields, the provisional fields `expected_baseline_scores`,
`split_grouping_column`, `public_test_fraction`, `compute_envelope` (RAM,
wall-clock time, accelerator), `protocol_level`, `sensitive_data`, and
`winner_reproducibility_required`. In accordance with principle 4, a unit test
should assert that every fact field is referenced by the `requires_facts`
declaration of at least one check. The two presently orphaned fields,
`unit_of_generalization` and `task_type`, would be the first brought under this
contract, by the new checks of D4.

### 7.3 Conditional gating

We propose a verdict path by which a finding escalates to a failure when a
declared fact renders the defect certain (principle 3). This is the mechanism by
which the fact channel raises rigour rather than merely unlocking advisories:
`split-matches-generalization-unit` advises in the absence of the fact but gates
when `unit_of_generalization` is declared and violated; `baseline-score-reproduction`
and `target-absent-from-public-test` gate only when their enabling fact or data is
present. The top-level definition of `ok` — the absence of a deterministic
failure — is unchanged; only the set of conditions that produce a failure grows.

### 7.4 Check families and suite versioning

Related checks should be grouped into named *families* — for instance, the D4
leakage family — so that the command-line interface and the report may summarise
at family granularity. The check suite should additionally carry a
`suite_version`, recorded in every stored validation report, so that the
statement "the bundle passed validation" is unambiguous once the suite is large
enough that the claim depends on which generation of checks produced it.

---

## 8. Non-goals

For transparency, and consistently with limitations L1–L8 of the companion
document, the following are outside the scope of this proposal and are addressed
by no proposed check:

- run-time worker reliability, submission liveness, and queue or status reporting
  (L1);
- *live* phase migration, as distinct from static migration-configuration
  coherence (L2);
- the detection or enforcement of cheating, duplicate accounts, probing attacks,
  or in-flight overfitting, all of which are defined over a participant
  population and a submission time series (L3);
- the *full* per-feature leakage probe, which requires a training run (L4); only
  the deterministic split and target proxies of D4 are proposed;
- adjudication of the scientific merit or novelty of the task (L5), deferred to
  the external-review attestation;
- identity, collaboration, enrolment, and access control (L6);
- live platform-API operations — incremental update, administrative submission,
  and submission simulation (L7);
- statistical aggregation over a population of submissions, such as confidence
  intervals and significance testing across many submissions (L8); single-baseline
  statistical sanity, such as `baseline-ordering`, is in scope, whereas population
  statistics are not.

Stating these explicitly ensures that the expanded suite does not create the
impression of addressing failures it structurally cannot.

---

## 9. Validation of the framework

Each newly proposed deterministic check should be accompanied, prior to being
considered complete, by a corresponding seeded defect in the validate-bench
instrument (`benchmark/autocodabench_validate_bench/`): a clean bundle is mutated
to introduce exactly the flaw the check targets, and the instrument measures
whether the check detects it. The reported quantity is a per-tier catch rate, so
that the assertion "the validator detects this defect" is itself an executable
and measured result rather than a claim — the same discipline the companion
document applies to the present suite.

---

## 10. Suggested order of implementation

The following ordering, by ratio of value to effort, is advisory and is not part
of the framework proposal proper.

- **P0 (highest value, low effort, data already present).**
  `target-absent-from-public-test`, `split-identifier-disjointness`,
  `metric-direction-semantics`, and the consumption of the two latent facts via
  `split-matches-generalization-unit` and `metric-suits-class-balance`. These
  close the most consequential gaps — leakage, the template's direction defect,
  and the principle-4 violations — and require no new infrastructure.
- **P1 (high value, moderate effort).** The execution-tier additions
  `baseline-score-reproduction`, `scorer-sensitivity`, and `baseline-ordering`,
  which reuse the existing runner; the `metric-suits-class-balance` lookup table;
  and `rules-completeness` and `final-phase-code-submission`.
- **P2 (framework systematisation).** The declarative check specification
  (§7.1), the completeness invariant, the fact-contract test, conditional gating
  (§7.3), and the decomposition of `bundle-schema`.
- **P3 (governance breadth and remaining structural and documentation checks).**
  The new D6 attestations, together with `migration-config-coherence`,
  `schedule-coherence`, `compute-envelope-documented`,
  `scorer-shipped-to-participants`, and the introduction of check families and
  suite versioning.

### 10.1 Implementation status (first increment)

A first build increment has landed, advancing the framework and the
highest-value deterministic checks (marked N† in Section 4):

- *Framework.* The validation-dimension axis (Section 2) is now declared in code:
  every registered check carries a `Dimension`, a keyless unit test asserts the
  invariant that each check declares a dimension and a citation, and both the
  `checks list` command and the report group by dimension — the legibility change
  motivated in Section 1.
- *Checks.* `metric-direction-semantics` (the official-template
  ascending-accuracy catcher), `leaderboard-well-formed` (key present, column
  keys and indices unique), and `reference-data-not-participant-visible` (no
  byte-identical ground-truth file in a participant role) are implemented and
  gate where appropriate; `docker-image-pinned` was extended to require an
  explicit, non-floating image tag.
- *Measurement.* Each new deterministic check has a corresponding seeded defect
  in the validate-bench defect library, exercised by the keyless unit suite for
  both catch (recall) and specificity (no false positive on the clean bundle),
  per Section 9.

The remaining P0–P3 items, the protocol-conditional families (Section 2, Axis C),
and the execution-tier additions (notably `scorer-degenerate-input-robust`) are
the subsequent increments.

---

## 11. Coverage against the published proposal template

Sections 4–5 derive coverage from an *internal* construct — the
(dimension × tier) matrix. This section strengthens the completeness argument by
re-deriving it against an *external, published* standard: the challenge-proposal
template of the "Challenge design roadmap" (Pavão et al., Ch. 2; with Ch. 3–5,
11, 13 for individual sub-points). That template is the community's own answer to
"what does a well-designed competition contain?" Treating each of its fifteen
sections as a property that *should* be checkable converts "is the suite
comprehensive?" from an assertion into a traceable matrix, and gives organisers a
named standard against which our coverage can be audited.

### 11.1 The bucket constraint

`validate` inspects a *bundle*, not a *proposal*. Each template sub-point falls
into exactly one bucket, and the bucket forces the only honest tier:

| Bucket | Evidence lives in | Forced tier |
|---|---|---|
| **A — Machine-encoded** | `competition.yaml`, programs, leaderboard config | Deterministic (may gate) |
| **B — Participant-facing prose** | `pages/*.md` | Judged (advisory FINDING) |
| **C — Proposal-only / off-platform** | organiser team, promotion, conference support, live logistics | Attestation (surfaced, never gated) |

Two limits follow and are stated rather than hidden: (i) Bucket-C sections are
genuinely absent from most bundles — we surface them as attestation boxes, never
implying the bundle proves them; (ii) judged checks verify that the pages *claim*
a property, not that reality satisfies it. **Gating discipline is unchanged**
(Section 3): only deterministic checks gate; the expansion is overwhelmingly
advisory.

A **proposal-aware mode** lifts limit (i) where possible: when `validate` runs
inside the create pipeline, or is given `--proposal PATH` (reusing
`core/proposal.py:pdf_to_text`), the Bucket-B/C checks additionally read the input
proposal text. Standalone `validate <bundle>` reads only `pages/`; a check whose
source text is absent returns SKIPPED-with-reason, never a silent pass.

### 11.2 Before — current coverage of the template

Legend ● full · ◐ partial · ○ none, over today's 27 checks (D = dimension/Type).

| # | Template section | Bucket | Cov. | Current checks |
|---|---|---|---|---|
| T0 | Abstract & keywords | B | ○ | — |
| T1 | Background & impact | B | ○ | — |
| T2 | Novelty | B/C | ○ | — |
| T3 | Data | A/B/C | ◐ | `judged-data-description`, `attest-datasheet`, `attest-data-persistence`, `attest-leakage-probe`, `reference-data-not-participant-visible` |
| T4 | Tasks & application scenarios | B | ◐ | `judged-task-framing` |
| T5 | Metrics & evaluation methods | A/B | ◐ | `judged-evaluation-explained`, `metric-direction-semantics`, `leaderboard-sorting`, `leaderboard-well-formed` |
| T6 | Baselines, code & material | A/B | ● | `baseline-solutions`, `baseline-execution`, `starting-kit`, `starting-kit-execution` |
| T7 | Tutorial & documentation | B | ○ | — |
| T8 | Protocol | A/B | ◐ | `two-phase-structure`, `judged-submission-instructions` |
| T9 | Rules | A/B | ◐ | `judged-rules-completeness`, `daily-submission-cap`, `final-phase-submission-limit`, `external-data-rule` |
| T10 | Schedule & readiness | A/B | ◐ | `dev-phase-duration`, `two-phase-structure` |
| T11 | Challenge promotion | C | ○ | — |
| T12 | Organising team | C | ○ | — |
| T13 | Resources & prizes | A/C | ◐ | `attest-game-of-skill` |
| T14 | Support requested | C | ○ | — (out of scope, §11.5) |

Six of fifteen sections are uncovered: the entire proposal-quality front half
(T0–T2, T7) and the off-platform sections (T11, T12). The executable heart (T6)
and the machine-config checks are strong; the prose front half is empty — which
is the concrete sense in which the present suite "feels limited."

### 11.3 After — the template-derived checks

~26 new checks (≈9 deterministic, ≈13 judged, ≈4 attestation), each filed under
an existing Type and carrying a chapter citation. **Bold** = new; `(det)` gates,
`(judged)`/`(attest)` advise.

- **T0 Abstract & keywords** → D5: **`judged-abstract-structure`** (five abstract
  elements present), **`judged-keywords-present`**, **`challenge-type-declared`**
  (det; fact `challenge_type`; gates the live-only conditionals).
- **T1 Background & impact** → D5: **`judged-background-impact`** (motivation,
  impact class, audience estimate, real-scenario hook).
- **T2 Novelty** → D5: **`judged-novelty-positioning`** (new vs series vs recycled
  data; differences from prior challenges).
- **T3 Data** → D4/D6: existing five + **`judged-data-quantity-justified`**
  (size adequacy, post-contest availability, GT confidentiality),
  **`data-license-declared`** (det, advisory; explicit licence token),
  **`attest-deprecated-dataset`** (fact `dataset_name`; LLM drafts the "<name>
  deprecated" due-diligence note), **`attest-pii-consent`**.
- **T4 Tasks** → D5/D3: existing + **`judged-task-scenario`**,
  **`judged-task-difficulty`** (cross-referenced to the measured baseline gap).
- **T5 Metrics & evaluation** → D3/D5: existing four + **`judged-metric-justified`**
  (why this metric measures success), **`judged-error-bars`**,
  **`judged-judging-protocol`** (fact `human_judging`: orthogonal criteria,
  tie-break, judge qualifications).
- **T6 Baselines** → D2/D5: existing four + **`judged-baseline-range`**
  (trivial→SOTA spread + gap), **`judged-starting-kit-parity`** (kit mirrors eval
  conditions), **`judged-equitable-resources`** (fact `special_hardware`).
- **T7 Tutorial & documentation** → D5: **`judged-tutorial-material`** (white
  paper / FAQ / notebooks referenced).
- **T8 Protocol** → D5/D6: existing two + **`submission-mode-declared`** (det;
  result vs code submission), **`judged-protocol-described`**,
  **`judged-cheating-prevention`**.
- **T9 Rules** → D5/D6: existing four + **`judged-account-policy`** (single/multiple
  accounts, anonymity), **`judged-rules-immutability`**.
- **T10 Schedule & readiness** → D3/D5: existing two + **`phase-dates-monotonic`**
  (det; dates parse, ordered, non-overlapping), **`review-window-present`** (det,
  advisory), **`judged-schedule-adequacy`** (~90 dev days + review window +
  readiness statement).
- **T11 Promotion** → D6: **`attest-promotion-plan`** (plan + under-represented
  outreach; LLM-tailored guidance).
- **T12 Organising team** → D6: **`attest-organizing-team`** (required roles, bios,
  diversity).
- **T13 Resources & prizes** → D6: existing + **`prize-structure-declared`** (det;
  fact `prizes`).
- **Live conditionals** (T1/T5/T10/T13, gated on `challenge_type=live`):
  **`attest-live-logistics`**.

This carries the suite from 27 to ~53 checks and lifts every section off ○ except
T14. The deterministic gate grows by ~9 narrow checks; the rest is advisory, as
the bucket constraint requires. The new attestations finally consume the
`unit_of_generalization` / `task_type` fact entries flagged in the companion
provenance document, and add facts `challenge_type`, `human_judging`,
`special_hardware`, `dataset_name`, `data_license` under the same
declare-then-verify contract (Section 7.2): absent fact ⇒ SKIPPED with
instructions.

### 11.4 Supporting changes

1. **`CompetitionFacts`** gains the five facts above.
2. **Proposal-aware text source** — `judged._bundle_texts` optionally includes the
   input-proposal text; a `--proposal PATH` flag on `validate`.
3. **Template traceability is documentation-only** (decided): `checklist_coverage()`
   / `checks --json` gains a `template_section` field (T0–T13) and this section is
   its narrative home, but the rendered `checks`/`validate` tables gain **no** new
   column — the Type and LLM-as-a-judge columns stay as they are, tables stay
   readable.

### 11.5 Declared limits

T14 (support requested) and the off-platform half of T11/T12 are not bundle
properties; they remain attestations. Beta-testing, external review, ethics
approval, and deprecation status are human acts the tool prompts for and drafts
guidance on but cannot certify. No new check gates from prose: a thin-on-prose
bundle still passes the gate, by design.

### 11.6 Order of implementation and measurement

Per the increment discipline of Section 10, and decided for this round, the
**deterministic batch ships first** (`data-license-declared`,
`phase-dates-monotonic`, `review-window-present`, `submission-mode-declared`,
`prize-structure-declared`, `challenge-type-declared`, …): immediate gate value,
keyless tests, low risk. The judged batch follows only after each new check's
clean-bundle false-positive rate is calibrated ≤ 0.20 (the bar held to the
existing five judged checks); the attestation batch and proposal-aware mode come
last.

Coverage is **measured, not asserted**: each new deterministic check gets a
matching opaque defect in the validate-bench mutator (`bench/defects.py`) — e.g.
scramble phase dates, strip the licence token, collapse the review window, remove
the submission-mode statement — and each new judged check extends the existing
content-gutting defects, reporting per-check recall and clean false-positive rate
over N runs exactly as `benchmark/autocodabench_validate_bench/full_report.py`
does today.

---

## References

As in [`validation-provenance-and-positioning.md`](./validation-provenance-and-positioning.md):
Pavão et al. (2024), *AI Competitions and Benchmarks: The Science Behind the
Contests*; MLE-bench (Chan et al., OpenAI); the 2025 École Polytechnique DataCamp
debrief (Letournel & Moreau, 2026); organiser stakeholder interviews (internal
field notes, 2026); the Codabench bundle schema and the official Codabench
template. Companion documents in this directory:
`validation-provenance-and-positioning.md`, `verification-catalog.md`,
`scientific-validation.md`.
