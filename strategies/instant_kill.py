# -*- coding: utf-8 -*-
"""
Theme-specific breaking strategy.

This file is intentionally simple.
Teammates only need to implement solve(context).
"""

from core.breaker_types import BreakContext, BreakPlan


THEME_NAME = "即死"


def solve(context: BreakContext) -> BreakPlan:
    return BreakPlan(
        theme=THEME_NAME,
        actions=[],
        confidence=0.0,
        reason="即死主题破阵逻辑尚未实现",
    )
