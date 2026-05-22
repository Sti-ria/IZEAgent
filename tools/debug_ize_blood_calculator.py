# -*- coding: utf-8 -*-
r"""
Debug CLI for core/ize_blood_calculator.py.

Usage examples, from PVZAgent project root:

    python .\tools\debug_ize_blood_calculator.py

    python .\tools\debug_ize_blood_calculator.py --lane "snowpea,repeater,wallnut,empty,puffshroom"

    python .\tools\debug_ize_blood_calculator.py --lane "empty,empty,empty,snowpea,empty" --explain

    python .\tools\debug_ize_blood_calculator.py --lane "empty,empty,empty,snowpea,empty" --legacy-pole --explain

    python .\tools\debug_ize_blood_calculator.py --json --lane "snowpea,repeater,wallnut,empty,puffshroom"

Board format:
    Rows are separated by semicolons.
    Cells in each row are separated by commas.

    python .\tools\debug_ize_blood_calculator.py --board "empty,empty,empty,empty,empty; peashooter,empty,empty,empty,empty; snowpea,repeater,wallnut,empty,puffshroom"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import List


# Allow running this file from PVZAgent/tools directly.
_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parents[1] if len(_THIS_FILE.parents) >= 2 else Path.cwd()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from core.ize_blood_calculator import (
        IZEBloodCalculator,
        explain_pole,
        format_result_table,
    )
except ModuleNotFoundError:
    # Also allow running when both generated files are in the same folder.
    local_core = _THIS_FILE.with_name("ize_blood_calculator.py")
    if local_core.exists():
        sys.path.insert(0, str(_THIS_FILE.parent))
        from ize_blood_calculator import (  # type: ignore
            IZEBloodCalculator,
            explain_pole,
            format_result_table,
        )
    else:
        raise


DEFAULT_BOARD = [
    ["empty", "empty", "empty", "empty", "empty"],
    ["peashooter", "empty", "empty", "empty", "empty"],
    ["snowpea", "repeater", "wallnut", "empty", "puffshroom"],
    ["starfruit", "spikeweed", "kernelpult", "empty", "empty"],
    ["potatomine", "squash", "chomper", "magnetshroom", "umbrellaleaf"],
]


def parse_lane(text: str) -> List[str]:
    return [part.strip() for part in text.split(",") if part.strip() != ""]


def parse_board(text: str) -> List[List[str]]:
    rows = []
    for row_text in text.split(";"):
        row = parse_lane(row_text)
        if row:
            rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug IZE blood calculator.")
    parser.add_argument(
        "--lane",
        type=str,
        default=None,
        help='One lane, comma-separated. Example: "snowpea,repeater,wallnut,empty,puffshroom"',
    )
    parser.add_argument(
        "--board",
        type=str,
        default=None,
        help="Board rows separated by semicolons. Every row uses comma-separated plant labels.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON result.",
    )
    parser.add_argument(
        "--no-status",
        action="store_true",
        help="Do not decorate recommended / not-recommended values.",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Print pole-vaulting correction details.",
    )
    parser.add_argument(
        "--legacy-pole",
        action="store_true",
        help="Disable PVZAgent modified pole pre-jump correction and use legacy pole result.",
    )
    args = parser.parse_args()

    calculator = IZEBloodCalculator(use_modified_pole=not args.legacy_pole)

    if args.lane:
        lane = parse_lane(args.lane)
        result = calculator.calculate_lane(lane, explain=args.explain)
        results = [result]
    elif args.board:
        board = parse_board(args.board)
        results = calculator.calculate_board(board, explain=args.explain)
    else:
        results = calculator.calculate_board(DEFAULT_BOARD, explain=args.explain)

    if args.json:
        print(json.dumps(results[0] if args.lane else results, ensure_ascii=False, indent=2))
    else:
        print(format_result_table(results, no_status=args.no_status))

    if args.explain:
        print()
        if args.lane:
            print(explain_pole(results[0]))
        else:
            for i, result in enumerate(results):
                print(f"第 {i + 1} 行")
                print(explain_pole(result))
                if i != len(results) - 1:
                    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
