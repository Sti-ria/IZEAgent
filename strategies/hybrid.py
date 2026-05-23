# -*- coding: utf-8 -*-
"""
Hybrid theme breaking strategy.

This is a simple example strategy.
Later teammates can replace this logic with real hybrid-theme breaking logic.
"""

from core.breaker_types import BreakAction, BreakContext, BreakPlan


THEME_NAME = "综合"


def solve(context: BreakContext) -> BreakPlan:
    """
    Example logic:
    Choose the first row where the blood calculator recommends pole.
    """

    for row in range(5):
        recommended = context.recommended_modes(row)

        if "pole" in recommended:
            return BreakPlan(
                theme=THEME_NAME,
                actions=[
                    BreakAction(
                        zombie="pole",
                        row=row,
                        note="示例策略：算血器推荐撑杆，所以选择该行",
                    )
                ],
                confidence=0.5,
                reason=f"第 {row + 1} 行推荐撑杆",
                debug={
                    "recommended_modes": recommended,
                    "lane": context.lane(row),
                    "blood_values": context.blood_values(row),
                },
            )

    return BreakPlan(
        theme=THEME_NAME,
        actions=[],
        confidence=0.0,
        reason="综合主题示例策略：没有找到推荐撑杆的行",
    )
