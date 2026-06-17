# `ground_truth/` — PARSEME shared task 1.2 (verbal MWE identification)

The canonical Codabench reference bundle for the **PARSEME 1.2** shared task on
semi-supervised identification of verbal multiword expressions (results
submission). It exists so a maintainer can (a) use the bundle as a
**validate-bench instrument** and (b) compare what AutoCodabench's agents
produce against the real bundle. No agent is ever granted read access here.

## Provenance

A Codabench-v2 bundle (`bundle_parseme/`). Reformatted in place with only
minimal, faithful fixes:

- phase `start: 5-2-2024` → ISO `start: '2024-02-05'` (+ a nominal `end`).
- task `input_data: input_data.zip` / `reference_data: reference_data.zip` →
  the unzipped directories `input_data/` and `reference_data/`.
- added a `Terms` entry to `pages:` (the `pages/terms.md` file already existed
  and is referenced by `terms:`).

Everything else (description, `fact_sheet`, the 9-column leaderboard, the
scoring/ingestion programs) is carried over unchanged.

### Polish from the validator report (`autocodabench validate`, no LLM)

The deterministic validator was run and its findings used to polish the bundle
(PASS count 7 → 27):

- Added `sorting: desc` to all nine leaderboard columns (every column is a
  higher-is-better P/R/F metric).
- Added `max_submissions_per_day: 10` to the phase (anti-probing cap).
- Added `competition_facts.yaml` declaring `data_license`, `challenge_type:
  regular`, and `prizes: false`.
- Wired two baseline solutions under `solutions/` and declared them in
  `competition.yaml`: `no_mwe_baseline/` (a trivial "predict no verbal MWE"
  baseline that bounds every MWE-based P/R/F at 0, generated for all 14
  languages by the tracked `solutions/make_no_mwe_baseline.py`) and
  `HMSid_open/` (a real system submission, FR). The prediction `.cupt` files are
  heavy (~120 MB) and git-ignored — the generator script is tracked, so the
  trivial baseline is reproducible; `HMSid_open/` is populated from the upstream
  submission.

**Chosen defaults to confirm:** the daily cap and the `competition_facts.yaml`
values (notably `data_license`, which truly varies per language) were set by the
maintainer and should be confirmed against the upstream shared task.

**Known residual findings:**
- `reference-data-not-participant-visible` (the one FAIL) — accepted and
  documented above; intrinsic to the semi-supervised task.
- `two-phase-structure` — PARSEME 1.2 is genuinely single-phase; left faithful.
- `docker-image-pinned` — no published worker image to pin (the upstream
  `docker/Dockerfile` builds one from `nvidia/cuda:11.1.1-cudnn8…`); needs a real
  pushed tag/digest.
- `bundle-schema` leaderboard-key heuristic (9×) — the column keys are written
  dynamically by `evaluate.py`/`generate_files.py`, so the static literal scan
  can't see them; false positives, not real gaps.

> **Known faithful flaw.** `autocodabench validate` reports a FAIL from
> `reference-data-not-participant-visible`: per-language `dev.cupt`/`train.cupt`
> files in `reference_data/` are byte-for-byte identical to the same files in
> the participant-visible `input_data/`. This is a real property of the upstream
> PARSEME bundle (annotated train/dev gold is distributed to participants), not
> a packaging artifact — it is left as-is so the instrument exercises the check.

## Layout

```
ground_truth/
├── README.md                  # this file (tracked)
└── bundle/                    # the reformatted bundle
    ├── competition.yaml       # tracked (reformatted to v2)
    ├── competition_facts.yaml # tracked (declared facts: licence, challenge type, prizes)
    ├── parseme.jpg            # tracked
    ├── pages/                 # tracked (overview.md, participate.md, terms.md)
    ├── scoring_program/  ingestion_program/   # tracked (metadata.yaml carries the command)
    ├── solutions/             # make_no_mwe_baseline.py tracked; prediction .cupt git-ignored (~120 MB)
    ├── starting_kit/          # tracked (~0.9 MB)
    ├── input_data/            # NOT tracked — ~392 MB of .cupt (keep-alive .gitignore)
    └── reference_data/        # NOT tracked — ~392 MB of gold .cupt (keep-alive .gitignore)
```

## Populating the un-tracked data

`input_data/` and `reference_data/` hold the heavy `.cupt` corpora and are
git-ignored (only their `.gitignore` is tracked). Re-populate from the source
PARSEME bundle (the un-tracked data is what makes the
`reference-data-not-participant-visible` FAIL reproduce):

```bash
# from the repo root, with the source bundle at $SRC
SRC=/path/to/portage-codabench-parseme-1.2/bundle_parseme
DEST=benchmark/autocodabench_create_bench/competitions/parseme-1.2/ground_truth/bundle
rsync -a --exclude='.DS_Store' "$SRC/input_data/"     "$DEST/input_data/"
rsync -a --exclude='.DS_Store' "$SRC/reference_data/" "$DEST/reference_data/"
# (or unzip the sibling input_data.zip / reference_data.zip into those dirs)
```

## Use as a validate-bench instrument

```bash
python benchmark/autocodabench_validate_bench/run.py \
  --instrument benchmark/autocodabench_create_bench/competitions/parseme-1.2/ground_truth/bundle
```
