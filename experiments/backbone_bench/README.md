# backbone_bench — LLM backbones compared on the autocodabench tasks

The backend seam (`autocodabench.backends`) makes the model a measured
variable. This experiment benchmarks LLM backbones on the two jobs the
software gives them, using the repo's ground-truth instruments as the
oracles — so the comparison is apples-to-apples by construction (same
tool surface, same audit-trail format, same pass/fail criteria,
regardless of backbone).

## Axis A — validation/judging quality (runnable now)

*How good is a backbone at catching competition defects?*

`run_judge_bench.py` seeds known authoring defects into otherwise-clean
bundles (rebuilt deterministically from the replay fixture), runs the
validator, and measures per-defect catch rate plus the false-positive
rate on clean copies. The deterministic tier is backbone-independent and
serves as the sanity baseline (it must be 9/9 for any backbone — it
never touches the model); the LLM-judged tier is the backbone-sensitive
measurement.

```bash
# sanity baseline (no LLM at all)
python experiments/backbone_bench/run_judge_bench.py

# per backbone, ≥3 runs because the judged tier is stochastic
python experiments/backbone_bench/run_judge_bench.py --backend claude --runs 3
python experiments/backbone_bench/run_judge_bench.py --backend ollama:llama3.1 --runs 3
python experiments/backbone_bench/run_judge_bench.py --backend openai:gpt-4o-mini --runs 3
```

Results land under `results/<backbone>/results.{json,md}`. Defect
library: 9 deterministic-tier targets + 3 judged-tier targets
(pages↔config contradictions in submission caps, metric direction, and
phase dates). Extend by appending to `DEFECTS`.

## Axis B — bundle-creation quality (protocol)

*How good is a backbone at authoring a working competition?*

The instrument is the existing ground-truth harness
(`experiments/bundle_creation_test/`), run once per backbone per
competition, with its blinding rules unchanged. Per (backbone,
competition, run) the manifest already records every outcome column:

| Measure | Source |
|---|---|
| plan completeness (7 sections) | plan phase payload |
| structural validity | `validate_bundle` |
| runtime validity + attempts used (baseline ≤5, notebook ≤4) | implement phase payload |
| **score fidelity**: generated bundle scores the ground-truth submission within `expected_result.json` tolerance | log-audit verdicts |
| cost + turns | session results |

Report per backbone: success rate per stage over ≥3 runs × N
competitions, attempts-to-converge distributions, score deltas, cost.
`style-trans-fair` is the first ground-truth competition; the protocol
scales by adding more under
`experiments/bundle_creation_test/competitions/`.

Caveats for non-Claude backbones on axis B: the generic backend's plan
phase cannot read PDF proposals (text/markdown proposals only), and the
backbone must support native tool calling — both are recorded as
conditions of the run, not silently worked around.

## Reporting standards

Same as the rest of the project (`docs/scientific-validation.md` §4):
pinned model identifiers per run, ≥3 runs per stochastic condition,
dispersion reported, costs/tokens reported, raw logs retained.
