# -*- coding: utf-8 -*-
"""
Router for theme-specific breaking strategies.

Given a BreakContext with a recognized theme, this router imports the matching
strategy module and calls its solve(context) function.
"""

from __future__ import annotations

from importlib import import_module
from typing import Dict, Optional

from core.breaker_types import BreakContext, BreakPlan


THEME_TO_MODULE: Dict[str, str] = {
    "综合": "strategies.hybrid",
    "控制": "strategies.control",
    "即死": "strategies.instant_kill",
    "输出": "strategies.output",
    "爆炸": "strategies.explosion",
    "倾斜": "strategies.diagonal",
    "穿刺": "strategies.piercing",
    "回复": "strategies.recovery",
}


class ThemeBreakerRouter:
    """
    Dispatch a BreakContext to one of the eight theme-specific strategy modules.
    """

    def __init__(self, config=None):
        self.config = config or {}
        self._module_cache = {}

    def get_module_name(self, theme: str) -> Optional[str]:
        if theme is None:
            return None

        return THEME_TO_MODULE.get(str(theme))

    def solve(self, context: BreakContext) -> BreakPlan:
        module_name = self.get_module_name(context.theme)

        if not module_name:
            return BreakPlan(
                theme=context.theme,
                actions=[],
                confidence=0.0,
                reason=f"没有找到主题 {context.theme!r} 对应的破阵模块",
            )

        if module_name not in self._module_cache:
            self._module_cache[module_name] = import_module(module_name)

        module = self._module_cache[module_name]

        if not hasattr(module, "solve"):
            return BreakPlan(
                theme=context.theme,
                actions=[],
                confidence=0.0,
                reason=f"{module_name} 没有实现 solve(context)",
            )

        plan = module.solve(context)

        if not isinstance(plan, BreakPlan):
            return BreakPlan(
                theme=context.theme,
                actions=[],
                confidence=0.0,
                reason=f"{module_name}.solve(context) 没有返回 BreakPlan",
            )

        return plan
