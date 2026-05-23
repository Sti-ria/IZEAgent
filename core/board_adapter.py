# -*- coding: utf-8 -*-
"""
Board adapter for strategy modules.

This module converts board recognition results into simple label boards that
can be used by:
1. IZE blood calculator
2. theme-breaking strategy modules

The strategy layer should not depend on the internal structure of cell_results
or BoardRecognizer memory objects.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence, Tuple


EMPTY_CELL_LABELS = {
    "",
    "empty",
    "unknown",
    "none",
    "null",
    "background",
    "invalid_frame",
}


LABEL_FIELDS = [
    "locked_label",
    "corrected_label",
    "stable_label",
    "memory_label",
    "final_label",
    "label",
    "plant",
    "class_name",
    "name",
    "pred",
]


def normalize_strategy_label(label: Any) -> str:
    """
    Normalize a cell label into a strategy-friendly string.
    """
    if label is None:
        return "empty"

    text = str(label).strip()

    if text.lower() in EMPTY_CELL_LABELS:
        return "empty"

    return text


def get_cell_field(cell: Any, names: Sequence[str], default: Any = None) -> Any:
    """
    Read one field from either dict-like cell result or object-like cell result.
    """
    if isinstance(cell, dict):
        for name in names:
            if name in cell:
                return cell.get(name)

        return default

    for name in names:
        if hasattr(cell, name):
            return getattr(cell, name)

    return default


def get_cell_label(cell: Any) -> str:
    """
    Extract a final usable plant label from one cell result.
    """
    value = get_cell_field(cell, LABEL_FIELDS, default=None)
    return normalize_strategy_label(value)


def iter_cells(cell_results: Any) -> Iterable[Tuple[int, Any]]:
    """
    Iterate over cell results in a stable flat order.

    Supports:
    - flat list
    - 2D list
    - dict values
    """
    if cell_results is None:
        return

    if isinstance(cell_results, dict):
        for idx, item in enumerate(cell_results.values()):
            yield idx, item
        return

    if isinstance(cell_results, (list, tuple)):
        idx = 0

        for item in cell_results:
            if isinstance(item, (list, tuple)):
                for sub_item in item:
                    yield idx, sub_item
                    idx += 1
            else:
                yield idx, item
                idx += 1


def extract_label_board(
    cell_results: Any,
    rows: int = 5,
    cols: int = 9,
) -> List[List[str]]:
    """
    Convert arbitrary cell results into a rows x cols string label board.

    Missing cells are filled as "empty".
    """
    board = [["empty" for _ in range(cols)] for _ in range(rows)]

    for idx, cell in iter_cells(cell_results):
        row = get_cell_field(cell, ["row", "r"], default=None)
        col = get_cell_field(cell, ["col", "column", "c"], default=None)

        if row is None:
            row = idx // cols

        if col is None:
            col = idx % cols

        try:
            row = int(row)
            col = int(col)
        except Exception:
            continue

        if 0 <= row < rows and 0 <= col < cols:
            board[row][col] = get_cell_label(cell)

    return board


def extract_ize_board(
    cell_results: Any,
    rows: int = 5,
    cols: int = 5,
) -> List[List[str]]:
    """
    Extract the first 5 columns used by IZE theme-breaking and blood calculation.
    """
    full_board = extract_label_board(cell_results, rows=rows, cols=9)
    return [lane[:cols] for lane in full_board]


def board_signature(board: Sequence[Sequence[str]]) -> Tuple[Tuple[str, ...], ...]:
    """
    Make a hashable signature for logging or change detection.
    """
    return tuple(tuple(str(cell) for cell in row) for row in board)


def print_board(board: Sequence[Sequence[str]]) -> None:
    """
    Small helper for manual debugging.
    """
    for row in board:
        print(" | ".join(str(cell) for cell in row))
