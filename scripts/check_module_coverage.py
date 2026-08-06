"""Per-module coverage floors.

The global floor (90%, branch) lives in pyproject.toml; this script enforces
floors for modules whose coverage is analysed separately, e.g.:
    uv run pytest -q --ignore=tests/e2e
    uv run python scripts/check_module_coverage.py src/charts.py src/metrics_engine.py --min 90
"""

import argparse
import sys

import coverage


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-module coverage floors.")
    parser.add_argument("modules", nargs="+", help="module file paths, e.g. src/charts.py")
    parser.add_argument("--min", type=float, default=90.0, help="minimum percent (branch-aware)")
    args = parser.parse_args()

    cov = coverage.Coverage()
    cov.load()
    failures = []
    for module in args.modules:
        pct = cov.report(include=[f"*/{module}"])
        if pct < args.min:
            failures.append(f"{module}: {pct:.1f}% < {args.min}%")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"module coverage OK (min {args.min}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
