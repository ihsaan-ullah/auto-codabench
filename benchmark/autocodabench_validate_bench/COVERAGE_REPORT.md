# autocodabench validator — coverage report

_Generated: 2026-06-16 22:55 UTC_  ·  backbone (judged tier): `claude:claude-opus-4-8`

This report measures how reliably `autocodabench validate` catches seeded authoring defects, by tier, on each instrument. Deterministic checks are backbone-independent and run keylessly; judged checks are LLM-graded and reported with a per-defect catch rate over repeated runs (consistency) plus the clean-bundle false-positive rate.

## 1. Suite coverage (27 checks)

Checks per validation dimension × epistemic tier.

| Dimension | dete | judg | atte | total |
|---|:--:|:--:|:--:|:--:|
| D1-structural | 2 | · | · | 2 |
| D2-executable | 4 | · | · | 4 |
| D3-methodological | 5 | · | · | 5 |
| D4-data-leakage | 1 | · | 1 | 2 |
| D5-documentation | 4 | 6 | · | 10 |
| D6-governance | · | · | 4 | 4 |

## 2. Deterministic tier — per-instrument catch (keyless)

### Instrument: `demo`  ·  recall 13/13 = 1.000

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

### Instrument: `style-trans-fair`  ·  recall 7/8 = 0.875

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

_Not applicable to this instrument (5):_ `missing-page` (mutation not applicable: [Errno 2] No such file or directory: '/var/folders/75/dkkrhjmn3_3bb60_lr69vxz80000gn/T/coverage-q91com22/gt/_probe/_probe-missing-page/pages/overview.md'); `unwritten-leaderboard-key` (mutation not applicable: defect seed failed: '"balanced_accuracy"' not found in scoring_program/score.py); `final-unlimited` (target check already fires on the clean bundle); `kit-missing` (target check already fires on the clean bundle); `leaderboard-key-collision` (mutation not applicable: list index out of range)

## 3. Judged tier — catch rate + consistency

Each judged defect was seeded and validated **5 times**; the catch rate is the consistency signal. Clean-bundle false positives are over 5 runs.

**Per-defect recall (catch rate over runs):**

| defect | target check | catch rate |
|---|---|:--:|
| caps-contradiction | `judged-docs-config-consistency` | 5/5 = 1.00 |
| metric-direction-contradiction | `judged-docs-config-consistency` | 5/5 = 1.00 |
| phase-dates-contradiction | `judged-docs-config-consistency` | 5/5 = 1.00 |
| vague-task | `judged-task-framing` | 2/5 = 0.40 |
| no-submission-format | `judged-submission-instructions` | 0/5 = 0.00 |
| unexplained-metric | `judged-evaluation-explained` | 5/5 = 1.00 |
| sparse-data-doc | `judged-data-description` | 5/5 = 1.00 |
| gutted-rules | `judged-rules-completeness` | 5/5 = 1.00 |

_Mean judged recall: 0.800._

**Per-check clean-bundle false-positive rate:**

| judged check | FP rate |
|---|:--:|
| `judged-docs-config-consistency` | 1/5 = 0.20 |
| `judged-rules-completeness` | 1/5 = 0.20 |
| `judged-task-framing` | 0/5 = 0.00 |
| `judged-submission-instructions` | 0/5 = 0.00 |
| `judged-evaluation-explained` | 0/5 = 0.00 |
| `judged-data-description` | 0/5 = 0.00 |

