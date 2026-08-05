from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

MINIMUM_LINE_PERCENT = 80.0
MINIMUM_BRANCH_PERCENT = 75.0


def percentage(covered: int, total: int) -> float:
    return 100.0 if total == 0 else covered / total * 100.0


def check_coverage(report_path: Path) -> int:
    report = cast(dict[str, Any], json.loads(report_path.read_text(encoding="utf-8")))
    totals = cast(dict[str, int], report["totals"])
    line_percent = percentage(totals["covered_lines"], totals["num_statements"])
    branch_percent = percentage(totals["covered_branches"], totals["num_branches"])

    print(f"backend line coverage: {line_percent:.2f}% (minimum {MINIMUM_LINE_PERCENT:.0f}%)")
    print(f"backend branch coverage: {branch_percent:.2f}% (minimum {MINIMUM_BRANCH_PERCENT:.0f}%)")

    if line_percent < MINIMUM_LINE_PERCENT or branch_percent < MINIMUM_BRANCH_PERCENT:
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enforce backend line and branch coverage")
    parser.add_argument("report", type=Path, help="coverage.py JSON report")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return check_coverage(args.report)


if __name__ == "__main__":
    raise SystemExit(main())
