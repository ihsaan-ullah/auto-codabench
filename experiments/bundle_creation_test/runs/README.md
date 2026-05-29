# `runs/` — experiment output dirs

Each invocation of `bundle-experiment-runner` creates a subdirectory:

```
runs/<comp>/<branch_short_sha>_<utc_ts>/
├── manifest.json
├── plan/
│   ├── implementation_plan.md
│   └── auto_codabench_run/
├── bundle/<slug>/...
├── validation/report.txt
├── reformatted_submission/sub_<N>/...
└── submission_run/sub_<N>/{stdout.txt, stderr.txt, score.json, sandbox/}
```

By default the heavy contents are gitignored — you regenerate them by
running the orchestrator. To preserve a specific run for reference,
force-add the small JSONs you care about:

```bash
git add -f runs/<comp>/<run_id>/manifest.json
git add -f runs/<comp>/<run_id>/submission_run/sub_*/score.json
```

Per-competition source materials (input dataset, ground-truth bundle,
sample submissions, expected results) live under
`../competitions/<comp>/`, NOT here. This separation keeps source vs.
output cleanly distinct.
