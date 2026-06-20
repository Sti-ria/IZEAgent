# -*- coding: utf-8 -*-
"""
Router for theme-specific breaking strategies.

Given a BreakContext with a recognized theme, this router imports the
matching strategy module and calls its solve(context) function.

This version also applies field-status safety filtering:
- Do not place zombies on rows whose brains are already gone.
- Optionally reduce a replan to one target row, because current strategies
  are mostly single-lane breaking strategies.
"""

from __future__ import annotations

from importlib import import_module
from typing import Dict, List, Optional

from core.breaker_types import BreakAction, BreakContext, BreakPlan


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
    Dispatch a BreakContext to one of the theme-specific strategy modules.
    """

    def __init__(self, config=None):
        self.config = config or {}
        self._module_cache = {}

        strategy_cfg = self.config.get("strategy", {})
        field_cfg = self.config.get("field_status", {})

        # When brain filtering is enabled, actions on rows without brains are dropped.
        self.filter_dead_brain_rows = bool(
            strategy_cfg.get(
                "filter_dead_brain_rows",
                field_cfg.get("filter_dead_brain_rows", True),
            )
        )

        # Current strategies are mostly single-lane. In automatic replan mode,
        # keep only one target row's action sequence to avoid multi-lane spam.
        self.single_replan_lane = bool(
            strategy_cfg.get(
                "single_replan_lane",
                field_cfg.get("single_replan_lane", True),
            )
        )

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

        return self._apply_field_status_filter(plan, context)

    def _apply_field_status_filter(
        self,
        plan: BreakPlan,
        context: BreakContext,
    ) -> BreakPlan:
        if plan is None or plan.is_empty:
            return plan

        original_actions = list(plan.actions or [])

        if not original_actions:
            return plan

        allowed_rows = context.candidate_rows()

        if self.filter_dead_brain_rows and allowed_rows:
            allowed_set = set(allowed_rows)
            filtered_actions = [
                action
                for action in original_actions
                if int(action.row) in allowed_set
            ]
        else:
            filtered_actions = original_actions

        dropped_count = len(original_actions) - len(filtered_actions)

        if not filtered_actions:
            return BreakPlan(
                theme=plan.theme,
                actions=[],
                confidence=0.0,
                reason=(
                    "策略动作全部位于已无脑子的行，已过滤。"
                    f"原原因：{plan.reason}"
                ),
                debug={
                    **(plan.debug or {}),
                    "field_filter": {
                        "allowed_rows": allowed_rows,
                        "dropped_count": dropped_count,
                        "original_action_count": len(original_actions),
                    },
                },
            )

        # If this is an automatic replan, keep only one target row.
        # This avoids placing zombies on several rows at once.
        if self.single_replan_lane and context.should_replan:
            target_row = int(filtered_actions[0].row)
            one_lane_actions = [
                action
                for action in filtered_actions
                if int(action.row) == target_row
            ]

            if one_lane_actions:
                reduced_count = len(filtered_actions) - len(one_lane_actions)
                filtered_actions = one_lane_actions
            else:
                reduced_count = 0
        else:
            target_row = None
            reduced_count = 0

        if dropped_count == 0 and reduced_count == 0:
            return plan

        extra_reason_parts = []

        if dropped_count > 0:
            extra_reason_parts.append(
                f"过滤掉 {dropped_count} 个已无脑子行的动作"
            )

        if reduced_count > 0:
            extra_reason_parts.append(
                f"自动重规划模式只保留第 {target_row + 1} 路动作"
            )

        extra_reason = "；".join(extra_reason_parts)

        return BreakPlan(
            theme=plan.theme,
            actions=filtered_actions,
            confidence=plan.confidence,
            reason=f"{plan.reason} | {extra_reason}",
            debug={
                **(plan.debug or {}),
                "field_filter": {
                    "allowed_rows": allowed_rows,
                    "dropped_count": dropped_count,
                    "reduced_count": reduced_count,
                    "target_row": target_row,
                    "original_action_count": len(original_actions),
                    "final_action_count": len(filtered_actions),
                },
            },
        )
