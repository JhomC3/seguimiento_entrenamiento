"""Atomic-code gate: fail files over --max code lines, warn over --warn.

Code lines = non-blank lines whose lstripped text does not start with '#'.
Scopes: app.py, src, scripts, tests (excluding tests/e2e: inherently long flows).
Checked set = files in the diff vs --base PLUS any over---max file in the tree
(catches new giants outside the diff). Grandfathered giants live in ALLOWLIST
with +5% headroom (they may breathe, not grow).
"""

import argparse
import subprocess
import sys
from pathlib import Path

WARN_DEFAULT = 500
MAX_DEFAULT = 800
HEADROOM = 1.05

ALLOWLIST = {
    "tests/test_app.py": 2656,
    "tests/test_database.py": 1294,
    "tests/test_charts.py": 1235,
    "tests/test_training_api.py": 1185,
}

SCOPES = ("app.py", "src", "scripts", "tests")
EXCLUDE_PREFIX = "tests/e2e/"


def code_lines(path: Path) -> int:
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            n += 1
    return n


def in_scope(rel: str) -> bool:
    if rel.startswith(EXCLUDE_PREFIX):
        return False
    return rel == "app.py" or rel.startswith(("src/", "scripts/", "tests/"))


def diff_files(base: str) -> set[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", base],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        return set()
    return {l.strip() for l in out.stdout.splitlines() if l.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Atomic-code file-size gate.")
    parser.add_argument("--warn", type=int, default=WARN_DEFAULT)
    parser.add_argument("--max", type=int, default=MAX_DEFAULT)
    parser.add_argument("--base", default="HEAD")
    args = parser.parse_args()

    root = Path.cwd()
    candidates = {f for f in diff_files(args.base) if in_scope(f)}
    for scope in SCOPES:
        p = root / scope
        if p.is_file():
            candidates.add(scope)
        elif p.is_dir():
            for f in p.rglob("*.py"):
                rel = f.relative_to(root).as_posix()
                if in_scope(rel):
                    candidates.add(rel)

    failures: list[str] = []
    for rel in sorted(candidates):
        p = root / rel
        if not p.is_file():
            continue
        n = code_lines(p)
        pinned = ALLOWLIST.get(rel)
        if pinned is not None:
            if n > pinned * HEADROOM:
                failures.append(f"{rel}: {n} > allowlist {pinned} +5%")
            elif n > args.warn:
                print(f"aviso: {rel} tiene {n} líneas de código", file=sys.stderr)
        elif n > args.max:
            failures.append(f"{rel}: {n} > max {args.max}")
        elif n > args.warn:
            print(f"aviso: {rel} tiene {n} líneas de código", file=sys.stderr)

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("tamaño OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
