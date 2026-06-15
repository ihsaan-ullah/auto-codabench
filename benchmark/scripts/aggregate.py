#!/usr/bin/env python3
"""Aggregate contributed benchmark records into the committed leaderboard.

Scans ``benchmark/*/results/**/*.json``, folds them by benchmark and backbone
(``autocodabench.bench.leaderboard``), and writes ``benchmark/LEADERBOARD.md``
and ``benchmark/LEADERBOARD.json``. Pure data → markdown; runs in CI on merge.

  python benchmark/scripts/aggregate.py                 # write LEADERBOARD.{md,json}
  python benchmark/scripts/aggregate.py --check         # fail if the committed
                                                        # leaderboard is stale (CI gate)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]

from autocodabench.bench import leaderboard, results


def build() -> tuple[dict, str]:
    paths = leaderboard.discover_results(BENCH_ROOT)
    records = []
    for p in paths:
        try:
            records.append(results.load(p))
        except Exception as e:  # malformed file — note and skip
            print(f"  ! skipping {p.relative_to(BENCH_ROOT)}: {e}", file=sys.stderr)
    agg = leaderboard.aggregate(records)
    return agg, leaderboard.render_markdown(agg)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if LEADERBOARD.md is out of date (CI gate)")
    args = ap.parse_args(argv)

    agg, md = build()
    md_path = BENCH_ROOT / "LEADERBOARD.md"
    json_path = BENCH_ROOT / "LEADERBOARD.json"

    if args.check:
        current = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
        # Compare on body only — the generated timestamp line legitimately varies.
        def _body(t: str) -> str:
            return "\n".join(l for l in t.splitlines() if not l.startswith("- generated:"))
        if _body(current) != _body(md):
            print("LEADERBOARD.md is stale — run: python benchmark/scripts/aggregate.py",
                  file=sys.stderr)
            return 1
        print(f"LEADERBOARD.md is up to date ({agg['n_records']} records).")
        return 0

    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(json.dumps(agg, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {md_path.relative_to(BENCH_ROOT.parent)} and "
          f"{json_path.relative_to(BENCH_ROOT.parent)} "
          f"({agg['n_records']} records, {agg['n_skipped']} skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
