#!/usr/bin/env python3
"""Print a markdown summary of test runtimes.

Reads the JSON produced by the pytest hook in tests/acceptance/conftest.py
(default: output/test_runtimes.json) and prints:

  1. Per-tier aggregates (count, total, mean, p50, p95, max)
  2. Top-N slowest tests (default 10)

Usage:
    python scripts/runtime_summary.py [--in PATH] [--top N]
    python scripts/runtime_summary.py --in output/tier2.json --top 20
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def fmt_seconds(s: float) -> str:
    if s < 60:
        return f"{s:.1f}s"
    m, sec = divmod(int(s), 60)
    if m < 60:
        return f"{m}m{sec:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--in", dest="input_path",
        default="output/test_runtimes.json",
        help="Input JSON path (default: output/test_runtimes.json)",
    )
    parser.add_argument(
        "--top", type=int, default=10,
        help="How many slowest tests to list (default 10)",
    )
    args = parser.parse_args()

    path = Path(args.input_path)
    if not path.is_file():
        print(f"ERROR: {path} not found.", file=sys.stderr)
        print(
            "Generate it by running pytest with the runtime hook enabled, e.g.:\n"
            "  pytest tests/acceptance/ -m tier1 --sif ... --runtime-out "
            f"{path}",
            file=sys.stderr,
        )
        return 2

    data = json.loads(path.read_text())
    aggregates = data.get("aggregates", {})
    tests = data.get("tests", [])

    # --- Per-tier aggregates ---
    print(f"# Test runtimes — `{path}`\n")
    if aggregates:
        print("## Per-tier aggregates\n")
        print("| Tier | Count | Total | Mean | p50 | p95 | Max |")
        print("|---|---|---|---|---|---|---|")
        for tier in sorted(aggregates):
            a = aggregates[tier]
            print(
                f"| `{tier}` | {a.get('count', 0)} | "
                f"{fmt_seconds(a.get('total_s', 0))} | "
                f"{fmt_seconds(a.get('mean_s', 0))} | "
                f"{fmt_seconds(a.get('p50_s', 0))} | "
                f"{fmt_seconds(a.get('p95_s', 0))} | "
                f"{fmt_seconds(a.get('max_s', 0))} |"
            )
        print()

    # --- Top-N slowest ---
    if tests:
        print(f"## Top {args.top} slowest tests\n")
        slowest = sorted(tests, key=lambda r: r["duration_s"], reverse=True)[: args.top]
        print("| # | Time | Outcome | Tiers | Test |")
        print("|---|---|---|---|---|")
        for i, r in enumerate(slowest, 1):
            tier_tag = ", ".join(r.get("tiers", [])) or "—"
            print(
                f"| {i} | {fmt_seconds(r['duration_s'])} | "
                f"{r['outcome']} | {tier_tag} | "
                f"`{r['nodeid'].split('::')[-1]}` |"
            )
        print()

        n_passed = sum(1 for r in tests if r["outcome"] == "passed")
        n_skipped = sum(1 for r in tests if r["outcome"] == "skipped")
        n_failed = sum(1 for r in tests if r["outcome"] == "failed")
        total = sum(r["duration_s"] for r in tests)
        print(
            f"_{len(tests)} tests, "
            f"{n_passed} passed / {n_failed} failed / {n_skipped} skipped, "
            f"{fmt_seconds(total)} total wall-clock_"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
