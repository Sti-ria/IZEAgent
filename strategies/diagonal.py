# -*- coding: utf-8 -*-
"""
Theme-specific breaking strategy.

This file is intentionally simple.
Teammates only need to implement solve(context).
"""

from core.breaker_types import BreakContext, BreakPlan


THEME_NAME = "倾斜"


def solve(context: BreakContext) -> BreakPlan:
    return BreakPlan(
        theme=THEME_NAME,
        actions=[],
        confidence=0.0,
        reason="倾斜主题破阵逻辑尚未实现",
    )
