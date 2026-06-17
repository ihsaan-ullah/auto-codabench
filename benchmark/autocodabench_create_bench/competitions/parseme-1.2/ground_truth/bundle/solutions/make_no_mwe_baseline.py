#!/usr/bin/env python3
"""Generate the trivial 'predict no verbal MWE' baseline for PARSEME 1.2.

For every language it reads ``input_data/<LANG>/test.blind.cupt`` and writes
``solutions/no_mwe_baseline/<LANG>/test.system.cupt`` identical to the blind
input except that the last column (``PARSEME:MWE``) of every ordinary token row
is set to ``*`` (no MWE). Range tokens (id ``a-b``) and empty nodes (id ``a.b``)
keep ``_``, per the .cupt convention. Comment and blank lines are copied verbatim.

This baseline predicts zero MWEs, so it bounds every MWE-based P/R/F metric at 0
— any competent system must beat it. The generated predictions are large and
git-ignored; regenerate them locally by running this script from the bundle
root once ``input_data/`` is populated:

    python3 solutions/make_no_mwe_baseline.py
"""
from __future__ import annotations

from pathlib import Path

BUNDLE = Path(__file__).resolve().parent.parent          # solutions/ -> bundle/
INPUT = BUNDLE / "input_data"
OUT = BUNDLE / "solutions" / "no_mwe_baseline"


def _strip_mwe(line: str) -> str:
    if not line.strip() or line.startswith("#"):
        return line
    cols = line.rstrip("\n").split("\t")
    if len(cols) < 2:
        return line
    tok_id = cols[0]
    # Only ordinary token rows get a prediction; ranges (a-b) / empty nodes (a.b)
    # are not annotatable and stay '_'.
    if tok_id.isdigit():
        cols[-1] = "*"
    return "\t".join(cols) + "\n"


def main() -> int:
    if not INPUT.is_dir():
        raise SystemExit(f"input_data/ not found at {INPUT} — populate it first")
    langs = sorted(p.name for p in INPUT.iterdir()
                   if p.is_dir() and (p / "test.blind.cupt").is_file())
    if not langs:
        raise SystemExit("no <LANG>/test.blind.cupt found under input_data/")
    for lang in langs:
        src = INPUT / lang / "test.blind.cupt"
        dst = OUT / lang / "test.system.cupt"
        dst.parent.mkdir(parents=True, exist_ok=True)
        with src.open(encoding="utf-8") as f, dst.open("w", encoding="utf-8") as g:
            for line in f:
                g.write(_strip_mwe(line))
        print(f"  {lang}: wrote {dst.relative_to(BUNDLE)}")
    print(f"done — {len(langs)} languages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
