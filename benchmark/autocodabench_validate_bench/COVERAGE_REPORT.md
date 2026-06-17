# autocodabench validator — coverage report

_Generated: 2026-06-17 08:24 UTC_  ·  backbone (judged tier): `claude:claude-opus-4-8`

This report measures how reliably `autocodabench validate` catches seeded authoring defects, by tier, on each instrument. Deterministic checks are backbone-independent and run keylessly; judged checks are LLM-graded and reported with a per-defect catch rate over repeated runs (consistency) plus the clean-bundle false-positive rate.

## 1. Suite coverage (57 checks)

Checks per validation dimension × epistemic tier.

| Dimension | dete | judg | atte | total |
|---|:--:|:--:|:--:|:--:|
| 1. Structural | 2 | · | · | 2 |
| 2. Executable | 4 | · | · | 4 |
| 3. Methodological | 7 | 4 | · | 11 |
| 4. Data & leakage | 1 | 1 | 2 | 4 |
| 5. Documentation | 6 | 15 | · | 21 |
| 6. Governance | 2 | 5 | 8 | 15 |

## 2. Deterministic tier — per-instrument catch (keyless)

### Instrument: `demo`  ·  recall 19/19 = 1.000

| defect | target check | caught |
|---|---|:--:|
| missing-page | `bundle-schema` | ✅ |
| unwritten-leaderboard-key | `bundle-schema` | ✅ |
| no-daily-cap | `daily-submission-cap` | ✅ |
| short-dev-phase | `dev-phase-duration` | ✅ |
| no-sorting | `leaderboard-sorting` | ✅ |
| final-unlimited | `final-phase-submission-limit` | ✅ |
| kit-missing | `starting-kit` | ✅ |
| single-phase | `two-phase-structure` | ✅ |
| docker-unpinned | `docker-image-pinned` | ✅ |
| docker-latest-tag | `docker-image-pinned` | ✅ |
| metric-sorting-inverted | `metric-direction-semantics` | ✅ |
| leaderboard-key-collision | `leaderboard-well-formed` | ✅ |
| reference-leaked-to-input | `reference-data-not-participant-visible` | ✅ |
| phase-dates-inverted | `phase-dates-monotonic` | ✅ |
| final-phase-open-ended | `review-window-present` | ✅ |
| data-license-stripped | `data-license-declared` | ✅ |
| prizes-undocumented | `prize-structure-declared` | ✅ |
| submission-mode-unstated | `submission-mode-declared` | ✅ |
| challenge-type-invalid | `challenge-type-declared` | ✅ |

### Instrument: `style-trans-fair`  ·  recall 10/12 = 0.833

| defect | target check | caught |
|---|---|:--:|
| no-daily-cap | `daily-submission-cap` | ✅ |
| short-dev-phase | `dev-phase-duration` | ✅ |
| no-sorting | `leaderboard-sorting` | ✅ |
| single-phase | `two-phase-structure` | ✅ |
| docker-unpinned | `docker-image-pinned` | ✅ |
| docker-latest-tag | `docker-image-pinned` | ✅ |
| metric-sorting-inverted | `metric-direction-semantics` | ❌ |
| reference-leaked-to-input | `reference-data-not-participant-visible` | ✅ |
| phase-dates-inverted | `phase-dates-monotonic` | ✅ |
| final-phase-open-ended | `review-window-present` | ✅ |
| prizes-undocumented | `prize-structure-declared` | ❌ |
| challenge-type-invalid | `challenge-type-declared` | ✅ |

_Not applicable to this instrument (7):_ `missing-page` (mutation not applicable: [Errno 2] No such file or directory: '/var/folders/75/dkkrhjmn3_3bb60_lr69vxz80000gn/T/coverage-2xkq2s91/gt/_probe/_probe-missing-page/pages/overview.md'); `unwritten-leaderboard-key` (mutation not applicable: defect seed failed: '"balanced_accuracy"' not found in scoring_program/score.py); `final-unlimited` (target check already fires on the clean bundle); `kit-missing` (target check already fires on the clean bundle); `leaderboard-key-collision` (mutation not applicable: list index out of range); `data-license-stripped` (target check already fires on the clean bundle); `submission-mode-unstated` (mutation not applicable: defect seed failed: no submission language to strip)

## 3. Judged tier — catch rate + consistency

Each judged defect was seeded and validated **3 times**; the catch rate is the consistency signal. Clean-bundle false positives are over 3 runs.

**Per-defect recall (catch rate over runs):**

| defect | target check | catch rate |
|---|---|:--:|
| caps-contradiction | `judged-docs-config-consistency` | 3/3 = 1.00 |
| metric-direction-contradiction | `judged-docs-config-consistency` | 3/3 = 1.00 |
| phase-dates-contradiction | `judged-docs-config-consistency` | 3/3 = 1.00 |
| vague-task | `judged-task-framing` | 3/3 = 1.00 |
| no-submission-format | `judged-submission-instructions` | 0/3 = 0.00 |
| unexplained-metric | `judged-evaluation-explained` | 3/3 = 1.00 |
| sparse-data-doc | `judged-data-description` | 3/3 = 1.00 |
| gutted-rules | `judged-rules-completeness` | 3/3 = 1.00 |
| gutted-abstract | `judged-abstract-structure` | 3/3 = 1.00 |
| gutted-background | `judged-background-impact` | 3/3 = 1.00 |
| unjustified-metric | `judged-metric-justified` | 0/3 = 0.00 |
| gutted-protocol | `judged-protocol-described` | 0/3 = 0.00 |
| sparse-data-quantity | `judged-data-quantity-justified` | 3/3 = 1.00 |

_Mean judged recall: 0.769._

**Per-check clean-bundle false-positive rate (lower = better precision):**

| judged check | demo | style-trans-fair |
|---|:--:|:--:|
| `judged-abstract-structure` | 0/3 | 0/3 |
| `judged-account-policy` | 0/3 | 0/3 |
| `judged-background-impact` | 0/3 | 0/3 |
| `judged-baseline-range` | 0/3 | 0/3 |
| `judged-cheating-prevention` | 0/3 | 0/3 |
| `judged-data-description` | 2/3 | 2/3 |
| `judged-data-quantity-justified` | 0/3 | 0/3 |
| `judged-docs-config-consistency` | 1/3 | 3/3 |
| `judged-equitable-resources` | 0/3 | 0/3 |
| `judged-error-bars` | 0/3 | 0/3 |
| `judged-evaluation-explained` | 0/3 | 0/3 |
| `judged-judging-protocol` | 0/3 | 0/3 |
| `judged-keywords-present` | 0/3 | 0/3 |
| `judged-metric-justified` | 0/3 | 2/3 |
| `judged-novelty-positioning` | 0/3 | 0/3 |
| `judged-protocol-described` | 0/3 | 0/3 |
| `judged-rules-completeness` | 1/3 | 3/3 |
| `judged-rules-immutability` | 0/3 | 0/3 |
| `judged-schedule-adequacy` | 0/3 | 0/3 |
| `judged-starting-kit-parity` | 0/3 | 0/3 |
| `judged-submission-instructions` | 0/3 | 1/3 |
| `judged-task-difficulty` | 0/3 | 0/3 |
| `judged-task-framing` | 0/3 | 1/3 |
| `judged-task-scenario` | 0/3 | 0/3 |
| `judged-tutorial-material` | 0/3 | 0/3 |

