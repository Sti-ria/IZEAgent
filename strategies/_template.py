# -*- coding: utf-8 -*-
"""
Theme strategy template.

Copy this file when implementing a new theme-breaking strategy.

A strategy file only needs to implement:

    def solve(context: BreakContext) -> BreakPlan

Do not import OpenCV, BoardRecognizer, ThemeRecognizer, or debug scripts here.
Only use BreakContext, BreakPlan and BreakAction.
"""

from core.breaker_types import BreakAction, BreakContext, BreakPlan


THEME_NAME = "主题名"


def solve(context: BreakContext) -> BreakPlan:
    """
    Input:
        context.theme:
            当前主题中文名，例如 "综合" / "输出" / "回复"

        context.board_5x5:
            IZE 前 5 列植物阵型。
            row 和 col 都是 0-based。

        context.board_5x9:
            完整 5x9 label 棋盘，可选使用。

        context.blood_table:
            算血器结果，共 5 行。

    Helpful methods:
        context.lane(row)
        context.plant_count(row)
        context.blood_values(row)
        context.blood_status(row)
        context.mode_value(row, mode)
        context.mode_status(row, mode)
        context.recommended_modes(row)
        context.not_recommended_modes(row)

    Mode names:
        "pole"        撑杆
        "slow"        慢速
        "ladder"      梯子
        "football"    橄榄
        "pole_ladder" 撑杆梯子
    """

    actions = []

    # Example:
    # Find the first row where pole is recommended.
    for row in range(5):
        if "pole" in context.recommended_modes(row):
            actions.append(
                BreakAction(
                    zombie="pole",
                    row=row,
                    col=None,
                    count=1,
                    note="示例：该行推荐撑杆",
                )
            )
            break

    if not actions:
        return BreakPlan(
            theme=THEME_NAME,
            actions=[],
            confidence=0.0,
            reason="没有找到合适破阵方案",
        )

    return BreakPlan(
        theme=THEME_NAME,
        actions=actions,
        confidence=0.5,
        reason="示例策略：优先使用推荐撑杆行",
        debug={
            "board_5x5": context.board_5x5,
        },
    )
