# `test-competition-bundle`

**Skill kind:** driver (orchestrator).

**Skill name:** `test-competition-bundle`.

**File:** [`SKILL.md`](./SKILL.md).

## What it does

Drives Phase 3 of an AutoCodabench session — local validation and
end-to-end testing of the bundle produced in Phase 2:

1. Calls `autocodabench_current_run()` to locate the bundle folder at
   `<run>/bundles/<slug>/`.
2. Runs `scripts/competition_bundle_validator.py` against the unzipped bundle folder and surfaces the result.
3. Reads `competition.yaml` and builds an inventory of all referenced
   components, checking whether each is a directory or a zip. Extracts
   zips in-place if needed.
4. If an `ingestion_program` is present in the `compeittion.yaml`, runs it against
   the bundle's `input_data/` and baseline solution directory.
5. Runs `scoring_program/score.py` with local paths (not the
   Codabench platform paths from `metadata.yaml`), reads `scores.json`,
   and displays a scores table.
6. Produces a structured closing report: validator status, inventory
   table, ingestion result, scoring result, scores, and a punch list
   of issues to fix before upload.

## Where the validator script lives

```
scripts/competition_bundle_validator.py
```
