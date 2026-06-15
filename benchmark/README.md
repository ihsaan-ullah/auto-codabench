# autocodabench benchmarks

Quantitative, reproducible measurement of the two tasks the library delegates
to an LLM. Both harnesses are **pure-SDK orchestrators**: every model action
goes through `autocodabench.backends` (the Claude Agent SDK *or* any
OpenAI-compatible endpoint — Ollama, vLLM, OpenAI, LiteLLM), with the same
20-tool surface and the same `tool_calls/` audit trail regardless of backbone.
There is no `claude -p` shell-out, no ambient `.mcp.json`, and no `.claude/`
symlink dependency — so a run is reproducible on any machine, including an
offline GPU worker, and the **backbone is a measured variable**.

| benchmark | question | status |
|-----------|----------|--------|
| [`autocodabench_create_bench`](autocodabench_create_bench/) | Does a PDF proposal become a working bundle that reproduces the ground-truth scores? | **live** (needs a backend + Docker) |
| [`autocodabench_validate_bench`](autocodabench_validate_bench/) | Does `validate` catch known, injected bundle defects? | **live** (deterministic tier is keyless) |

Contributed runs roll up into a committed [`LEADERBOARD.md`](LEADERBOARD.md)
(`python benchmark/scripts/aggregate.py`).

## Running create-bench

```bash
pip install -e .                       # the library (provides the backends + bench lib)
# Claude (subscription or ANTHROPIC_API_KEY):
python benchmark/autocodabench_create_bench/run.py --competition style-trans-fair --backend claude:claude-opus-4-8
# Local, keyless, offline (Ollama serving a tool-calling model):
python benchmark/autocodabench_create_bench/run.py --competition style-trans-fair --backend ollama:llama3.1 --runs 3
# Any OpenAI-compatible endpoint:
python benchmark/autocodabench_create_bench/run.py --backend openai:gpt-4o
python benchmark/autocodabench_create_bench/run.py --backend "http://gpu-node:8000/v1#Qwen2.5-72B-Instruct"
```

A Docker daemon is required — the bundle is executed exactly as the Codabench
worker runs it. The instruments (`competitions/<name>/`) carry heavy upstream
data that is gitignored; populate it per each competition's `README.md` before
a run.

### What create-bench measures

For one competition × one backbone (see `autocodabench_create_bench/run.py`):

- **plan** — completeness (the 7 design sections present in the plan).
- **build** — a bundle was produced and passes the deterministic schema lint.
- **execution** — the baseline and the starting-kit notebook run inside the
  bundle's Docker image (the library's own execution checks).
- **score fidelity** (the headline) — each ground-truth submission is adapted
  to the bundle and scored, then the produced score is compared to that
  submission's `expected_result.json` **within tolerance**. The
  *score-agreement rate* is the fraction within tolerance.
- **cost / turns**, and the **missing-information inventory** (what the model
  had to infer because the proposal didn't say).

The model that authors the bundle never sees `ground_truth/**`; the model that
adapts/scores a submission never sees `expected_result.json`; the auditor that
reads the expected score is deterministic Python (`autocodabench.bench.audit`).
The isolation is enforced by what each phase is handed, not by prompt wording.

## Running validate-bench

This one needs **no backend and no Docker** for its deterministic tier — the
clean bundle is rebuilt from the shipped replay fixture and the targeted checks
are pure code. A backbone is only needed for the judged tier.

```bash
pip install -e .
# Deterministic tier only (keyless, offline, ~1 s):
python benchmark/autocodabench_validate_bench/run.py
# Judged tier — the backbone-sensitive measurement (any OpenAI-compatible model):
python benchmark/autocodabench_validate_bench/run.py --backend claude:claude-opus-4-8 --runs 3
python benchmark/autocodabench_validate_bench/run.py --backend ollama:llama3.1 --runs 5
```

### What validate-bench measures

It seeds each known defect from `autocodabench.bench.defects` into an otherwise
clean bundle, runs `validate`, and records whether the expected check fired —
reporting **precision / recall / F1 per tier**:

- **deterministic** — backbone-independent sanity baseline; ~1.0 by
  construction (the unit suite asserts this and that the checks do *not* fire on
  the clean bundle).
- **judged** — the backbone-sensitive measurement: an LLM grades a rubric, so
  the catch rate varies by model. It also runs `validate` on an unmutated bundle
  to measure the judged tier's **false-positive rate**.

Grow the defect library by adding `Defect(...)` entries to
`src/autocodabench/bench/defects.py` (each `expect_check` must be a registered
check; the unit suite enforces this).

## Contributing results (the leaderboard)

Results are append-only and reviewed in-repo:

1. Run a benchmark for a backbone. It writes a canonical, **versioned** record
   (`schema_version`, see `autocodabench.bench.results`) to
   `<bench>/results/<backbone-tag>/<run-id>.json` — endpoint **host only, never
   the API key**.
2. Regenerate the leaderboard and open a PR adding both your `results/...json`
   file(s) and the updated `LEADERBOARD.md`:
   ```bash
   python benchmark/scripts/aggregate.py     # rewrites LEADERBOARD.md + LEADERBOARD.json
   ```
   Heavy per-run artifacts (`tool_calls/`, traces, sandboxes) stay on your
   machine; only the summary record is committed.
3. CI runs `python benchmark/scripts/aggregate.py --check` to ensure the
   committed `LEADERBOARD.md` matches the committed records, so the "current
   progress" across backbones stays live and git-reviewable. `aggregate.py`
   folds every `<bench>/results/<backbone>/*.json` by benchmark and backbone,
   averaging the headline metrics across runs.

Because the record pins `instrument_version`, `git_sha`, and
`autocodabench_version`, results stay comparable across machines and over time;
bumping an instrument invalidates only the records that targeted the old one.

## The missing-information inventory schema

Each `missing_info_report.json` the plan/build phases may emit, and which
`autocodabench.bench.missing_info.aggregate` consumes, has the shape:

```json
{
  "competition_sample_name": "...", "run_id": "...",
  "items": [
    {
      "section": "metric", "field": "direction",
      "what_was_missing": "...",
      "severity": "critical | important | nice_to_have | best_practice",
      "impact_area": "bundle_functionality | deployment_polish | participant_experience",
      "resolution": {
        "action": "inferred | default_applied | deferred | omitted",
        "choice": "...", "confidence": "high | medium | low",
        "would_block_correct_scoring": true
      }
    }
  ]
}
```

`aggregate` returns totals by section/severity/impact/resolution, the
most-missed fields, and the high-stakes inferences (`would_block_correct_scoring`).
