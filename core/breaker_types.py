# -*- coding: utf-8 -*-
"""
Shared data structures for theme-breaking strategies.

This file defines the interface between:
1. board recognition / theme recognition / blood calculator
2. eight theme-specific breaking strategy files

Teammates who write strategy files should only depend on these classes,
not on OpenCV, BoardRecognizer, ThemeRecognizer, or debug scripts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BreakAction:
    """
    One planned zombie action.

    row:
        0-based row index, range 0-4.

    col:
        Optional 0-based column index.
        For early strategy testing, this can stay None.
        Later, when connected to automatic clicking, this can be used
        to specify a more precise placement column.

    zombie:
        Suggested zombie type, for example:
        "pole", "slow", "ladder", "football", "pole_ladder".
    """

    zombie: str
    row: int
    col: Optional[int] = None
    count: int = 1
    note: str = ""


@dataclass
class BreakPlan:
    """
    Output of a theme-breaking strategy.
    """

    theme: str
    actions: List[BreakAction] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    debug: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return len(self.actions) == 0


@dataclass
class BreakContext:
    """
    Input passed to each theme strategy.

    Strategy files should mainly use:
        context.theme
        context.board_5x5
        context.blood_table
        context.lane(row)
        context.recommended_modes(row)
        context.mode_value(row, mode)
    """

    theme: str
    board_5x5: List[List[str]]
    blood_table: List[Dict[str, Any]]

    board_5x9: Optional[List[List[str]]] = None
    theme_result: Optional[Dict[str, Any]] = None
    correction_info: Optional[Dict[str, Any]] = None
    config: Dict[str, Any] = field(default_factory=dict)

    def lane(self, row: int) -> List[str]:
        return self.board_5x5[row]

    def blood_values(self, row: int) -> Dict[str, Any]:
        if row < 0 or row >= len(self.blood_table):
            return {}

        return self.blood_table[row].get("values", {})

    def blood_status(self, row: int) -> Dict[str, int]:
        if row < 0 or row >= len(self.blood_table):
            return {}

        return self.blood_table[row].get("status", {})

    def mode_value(self, row: int, mode: str) -> Any:
        return self.blood_values(row).get(mode)

    def mode_status(self, row: int, mode: str) -> int:
        return self.blood_status(row).get(mode, 0)

    def recommended_modes(self, row: int) -> List[str]:
        status = self.blood_status(row)
        return [mode for mode, value in status.items() if value == 1]

    def not_recommended_modes(self, row: int) -> List[str]:
        status = self.blood_status(row)
        return [mode for mode, value in status.items() if value == -1]

    def plant_count(self, row: int) -> int:
        if row < 0 or row >= len(self.board_5x5):
            return 0

        empty_labels = {"", "empty", "unknown", "none", "null"}

        return sum(
            1
            for label in self.board_5x5[row]
            if str(label).strip().lower() not in empty_labels
        )
