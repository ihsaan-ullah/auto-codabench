# `ground_truth/` — Survival (M2AIC 2018-2019)

The canonical Codabench reference bundle for the **Survival** competition
(survival analysis on the NHANES mortality dataset, scored by a custom
concordance index). It exists so a maintainer can (a) use the bundle as a
**validate-bench instrument** and (b) compare what AutoCodabench's agents
produce against the real bundle. No agent is ever granted read access here.

## Provenance

Originally a legacy CodaLab/Codabench bundle (`competition.yaml` in the old
flat `html:` + dict-`phases` format). It has been reformatted in place to the
AutoCodabench Codabench-v2 schema:

- `html: {...}` → a `pages:` list, and the five `.html` pages were **converted
  to Markdown** under `pages/` (faithful content; Markdown is what the
  documentation + judged checks read). The empty `get_starting_kit` page was
  dropped. `terms` references `pages/terms.md`.
- `competition_docker_image:` → `docker_image:`.
- `phases:` dict (`0:`/`1:`) → an ordered `phases:` list with ISO `start`/`end`.
- per-phase data wired through two `tasks:` (dev → `reference_data_dev/`,
  final → `reference_data_final/`); the `*_1` directory suffixes were dropped.
- `leaderboard:` (singular, nested-dict columns) → a `leaderboards:` list with
  `set1_score` (Custom Concordance Index, `desc`) and `Duration` columns.

### Polish from the validator report (`autocodabench validate`, no LLM)

After reformatting, the deterministic validator was run and its findings used to
polish the bundle to `ok=True`. Changes:

- Final phase total/daily submission limit `1000`/`500` → **`1`/`1`** (the final
  phase auto-migrates the last development submission; no new entries).
- Added `competition_facts.yaml` declaring `data_license` (NHANES is U.S.
  public domain), `challenge_type: regular`, `prizes: false`, and the unit of
  generalization — these satisfy the licence / challenge-type / prize checks.
- The converted Markdown pages state the submission mode and licence explicitly.
- Wired two baseline solutions under `solutions/` and declared them in
  `competition.yaml`: `coxph_baseline/` (the real CoxPH sample submission — a
  competent baseline) and `constant_baseline/` (a trivial constant-risk
  predictor, c-index ≈ 0.5, that bounds the metric). Both implement the
  fit/predict/save/load interface and are tracked (small text).

**Chosen defaults to confirm:** the final-phase limits and the `competition_facts.yaml`
values were set by the maintainer and should be checked against the original
competition.

**Known residual findings (all advisory; bundle is `ok=True`):**
- `docker-image-pinned` — `nnour/codalab-legacy-survival` has no published version
  tag we can pin; needs the real tag/digest.
- `bundle-schema` leaderboard-key heuristic — `score.py` writes the column keys
  (`set1_score`, `Duration`) dynamically, so the static literal scan can't see
  them; a false positive, not a real gap.

## Layout

```
ground_truth/
├── README.md                  # this file (tracked)
└── bundle/                    # the reformatted bundle
    ├── competition.yaml       # tracked (reformatted to v2)
    ├── competition_facts.yaml # tracked (declared facts: licence, challenge type, prizes)
    ├── pages/                 # tracked (overview.md, data.md, evaluation.md, terms.md)
    ├── logo.png               # tracked
    ├── scoring_program/  ingestion_program/   # tracked (legacy `metadata` carries the command)
    ├── solutions/             # tracked — coxph_baseline/ + constant_baseline/ (declared baselines)
    ├── reference_data_dev/  reference_data_final/   # tracked (tiny gold solutions)
    ├── input_data/            # NOT tracked — ~62 MB raw .data (keep-alive .gitignore)
    ├── public_data/           # NOT tracked — ~1.3 MB (keep-alive .gitignore)
    └── starting_kit/          # NOT tracked — ~2.7 MB (keep-alive .gitignore)
```

## Populating the un-tracked data

`input_data/`, `public_data/`, and `starting_kit/` hold the heavy raw data and
are git-ignored (only their `.gitignore` is tracked). Re-populate from the
source survival bundle by copying the corresponding `*_1` directories:

```bash
# from the repo root, with the source bundle at $SRC
SRC=/path/to/survival/bundle
DEST=benchmark/autocodabench_create_bench/competitions/survival/ground_truth/bundle
rsync -a --exclude='*.zip' --exclude='.DS_Store' "$SRC/input_data_1/"   "$DEST/input_data/"
rsync -a --exclude='*.zip' --exclude='.DS_Store' "$SRC/public_data_1/"  "$DEST/public_data/"
rsync -a --exclude='*.zip' --exclude='.DS_Store' "$SRC/starting_kit_1/" "$DEST/starting_kit/"
```

Static validation (`autocodabench validate <bundle>` / validate-bench with
`execute=False`) only needs the tracked files plus the `input_data/` path to
exist; full execution (`--execute`) additionally needs the populated data.

## Use as a validate-bench instrument

```bash
python benchmark/autocodabench_validate_bench/run.py \
  --instrument benchmark/autocodabench_create_bench/competitions/survival/ground_truth/bundle
```
