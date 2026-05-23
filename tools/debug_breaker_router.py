# -*- coding: utf-8 -*-
"""
Debug CLI for theme breaker router.

This script does not require PVZ window, OpenCV capture, board recognition,
or the blood calculator.

It only tests:
BreakContext -> ThemeBreakerRouter -> strategies/<theme>.py -> BreakPlan
"""

from __future__ import annotations

from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))


from core.breaker_types import BreakContext
from core.breaker_router import ThemeBreakerRouter


DEFAULT_BOARD_5X5 = [
    ["empty", "empty", "empty", "empty", "empty"],
    ["peashooter", "empty", "empty", "empty", "empty"],
    ["snowpea", "repeater", "wallnut", "empty", "puffshroom"],
    ["starfruit", "spikeweed", "kernelpult", "empty", "empty"],
    ["potatomine", "squash", "chomper", "magnetshroom", "umbrellaleaf"],
]


DEFAULT_BLOOD_TABLE = [
    {
        "values": {
            "pole": 100,
            "slow": 130,
            "ladder": "20+50",
            "football": 180,
            "pole_ladder": "",
        },
        "status": {
            "pole": 0,
            "slow": 0,
            "ladder": 0,
            "football": 0,
            "pole_ladder": -1,
        },
    },
    {
        "values": {
            "pole": 90,
            "slow": 120,
            "ladder": "10+40",
            "football": 160,
            "pole_ladder": "",
        },
        "status": {
            "pole": 1,
            "slow": 0,
            "ladder": 0,
            "football": 0,
            "pole_ladder": -1,
        },
    },
    {
        "values": {
            "pole": 123,
            "slow": 210,
            "ladder": "30+80",
            "football": 260,
            "pole_ladder": "",
        },
        "status": {
            "pole": 1,
            "slow": -1,
            "ladder": 0,
            "football": -1,
            "pole_ladder": -1,
        },
    },
    {
        "values": {
            "pole": 70,
            "slow": 110,
            "ladder": "15+60",
            "football": 150,
            "pole_ladder": "",
        },
        "status": {
            "pole": 0,
            "slow": 1,
            "ladder": 0,
            "football": 0,
            "pole_ladder": -1,
        },
    },
    {
        "values": {
            "pole": 200,
            "slow": 260,
            "ladder": "",
            "football": 300,
            "pole_ladder": "",
        },
        "status": {
            "pole": -1,
            "slow": -1,
            "ladder": -1,
            "football": -1,
            "pole_ladder": -1,
        },
    },
]


def print_plan(plan):
    print("=" * 60)
    print(f"theme      : {plan.theme}")
    print(f"confidence : {plan.confidence}")
    print(f"reason     : {plan.reason}")
    print(f"actions    : {len(plan.actions)}")

    for i, action in enumerate(plan.actions, start=1):
        print(
            f"  {i}. zombie={action.zombie}, "
            f"row={action.row + 1}, "
            f"col={None if action.col is None else action.col + 1}, "
            f"count={action.count}, "
            f"note={action.note}"
        )

    if plan.debug:
        print(f"debug      : {plan.debug}")


def main():
    router = ThemeBreakerRouter()

    themes = [
        "综合",
        "控制",
        "即死",
        "输出",
        "爆炸",
        "倾斜",
        "穿刺",
        "回复",
    ]

    for theme in themes:
        context = BreakContext(
            theme=theme,
            board_5x5=DEFAULT_BOARD_5X5,
            blood_table=DEFAULT_BLOOD_TABLE,
        )

        plan = router.solve(context)
        print_plan(plan)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
