# -*- coding: utf-8 -*-
"""
综合阵破阵策略。

当前只实现第一阶段：优先处理磁力菇。

这版基于 control.py 的磁力菇局部算血方式改写：
    - 不构造“目标局部 lane”；
    - 本路目标右侧/后排植物完整参与算血；
    - 上下相邻路三线通过 external_threepeaters 参与算血；
    - 支持多路障/多撑杆时只放大地刺伤害；
    - 支持“磁力菇左侧窝瓜/大嘴花”作为需要先垫掉的保护威胁；
    - 支持大嘴花被垫掉后临时变为普通可啃食植物，直到目标磁力菇消失。

阶段 1：磁力菇优先
    1. 只要场上存在 magnetshroom，就优先处理磁力菇；
    2. 先判断单路障 / 单撑杆能否吃掉磁力菇；
       - 判断的是吃到磁力菇为止的完整路径伤害；
       - 包含本路后排植物和旁路三线伤害；
       - 如果磁力菇左侧一格是窝瓜/大嘴花，则单吃磁力菇会被换掉，需要先处理该威胁；
       - 如果路障和撑杆都满足安全阈值 damage <= HP - 3，且阳光相同，优先路障；
    3. 如果不能单吃，并且满足飞贼条件，则飞贼抓磁力菇；
       飞贼条件：
           - 磁力菇 3x3 范围没有 umbrellaleaf；
           - 磁力菇左侧一格不是 squash / chomper；
       注意：
           - 不检查磁力菇右侧窝瓜；
           - 若左侧是 squash / chomper，飞贼会被弄掉，不能飞，进入第 4 点。
    4. 如果不能飞，进入非铁器强行处理：
       - 禁用所有铁器僵尸：bucket / football / ladder / pole_ladder；
       - 若通往磁力菇的路上先遇到 potatomine / squash / chomper，
         先输出逐个垫僵尸方案，解决这个阻挡点，然后等待识别稳定后重新判断；
       - 若磁力菇左侧一格是 squash / chomper，也先垫掉它；
       - 若没有阻挡点，尝试双撑杆 / 三撑杆 / 双路障 / 三路障强吃磁力菇；
       - n 只路障视作 1 只 n 倍血量的慢速僵尸；
       - n 只撑杆视作 1 只 n 倍血量的撑杆僵尸；
       - 啃食受伤暂时不做削减，偏保守；
       - 地刺受伤乘以僵尸数量 n；
       - 暂时不考虑“路障 + 撑杆”的混合方案。
    5. 磁力菇未清除前，不考虑三线 / 杨桃 / 常规破阵；
    6. 磁力菇清除后，暂时返回“综合阵后续策略待补充”。

外层策略更新建议：
    - 当外层检测到“场上有僵尸 -> 场上没有僵尸”后，再更新一次策略；
    - 如果上一轮策略是“垫掉大嘴花”，下一次更新时该大嘴花会临时视为普通可啃食植物；
    - 直到对应磁力菇被吃掉/消失后，临时大嘴花状态清空，之后大嘴花重新按秒杀性植物处理。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from core.breaker_types import BreakAction, BreakContext, BreakPlan
from core.ize_blood_calculator import (
    Row,
    MODE_SLOW,
    MODE_POLE,
    EMPTY,
    DC_21,
    YT_29,
    JG_3,
    HJSZ_22,
    normalize_lane,
    cpp_round,
    get_butter_rate,
)


THEME_NAME = "综合"

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

# 如果自动下僵尸模块里的飞贼命名不同，只需要改这里。
BUNGEE_ZOMBIE = "bungee"

# 阳光估算。
CONE_COST = 75
POLE_COST = 75
BUNGEE_COST = 125

# 血量判定。
CONE_HP = 27
POLE_HP = 17

# 安全阈值：<= HP - 3 才算“安全”。
SAFE_MARGIN = 3

# 默认认为 solve() 只在“有僵尸 -> 无僵尸”的策略更新时间点被调用。
# 如果你后续改成每帧都调用 solve()，建议把它改成 False，
# 然后在外层检测到“有僵尸 -> 无僵尸”时手动调用 notify_hybrid_zombie_cycle_finished()。
AUTO_APPLY_PENDING_EFFECT_ON_SOLVE = True

# 第 4 点明确禁用铁器僵尸。
BANNED_METAL_ZOMBIES = {
    "bucket",
    "football",
    "ladder",
    "pole_ladder",
    "screen_door",
}

EMPTY_LABELS = {
    "",
    "empty",
    "unknown",
    "none",
    "null",
    "blank",
    "grass",
    "invalidframe",
    "invalid_frame",
}

MAGNET_LABELS = {"magnetshroom"}
UMBRELLA_LABELS = {"umbrellaleaf"}
THREEPEATER_LABELS = {"threepeater"}

# 路径上会先换掉/吃掉僵尸的植物。
PATH_INSTANT_OR_EATER_LABELS = {
    "potatomine",
    "squash",
    "chomper",
}

# 磁力菇左侧一格能在僵尸啃磁力菇时换掉僵尸的威胁。
LEFT_GUARD_LABELS = {
    "squash",
    "chomper",
}


# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

@dataclass
class HybridRuntimeState:
    """
    综合阵磁力菇阶段的运行时状态。

    pending_effect:
        上一轮输出的垫尸策略，等外层确认“有僵尸 -> 无僵尸”后应用。

    consumed_empty_cells:
        被垫掉的土豆雷 / 窝瓜，临时视作 empty。

    standby_chompers:
        已经吃过一个僵尸、进入咀嚼/待机的大嘴花。
        在目标磁力菇消失前，临时视作普通可啃食植物。

    current_magnet_target:
        当前状态绑定的磁力菇位置。
        只要这个磁力菇消失，就清空 consumed_empty_cells / standby_chompers。
    """
    pending_effect: Optional[Dict[str, Any]] = None
    consumed_empty_cells: Set[Tuple[int, int]] = field(default_factory=set)
    standby_chompers: Set[Tuple[int, int]] = field(default_factory=set)
    current_magnet_target: Optional[Tuple[int, int]] = None
    version: int = 0


_STATE = HybridRuntimeState()


def reset_hybrid_strategy_state() -> None:
    """
    手动重置综合阵磁力菇阶段状态。

    建议在新一关、主题重锁定、手动 R 重置时调用。
    """
    global _STATE
    _STATE = HybridRuntimeState()


def notify_hybrid_zombie_cycle_finished() -> Optional[Dict[str, Any]]:
    """
    外层检测到“场上有僵尸 -> 场上没有僵尸”后调用。

    如果上一轮策略是垫掉土豆雷/窝瓜/大嘴花，则在这里应用临时状态：
        - potatomine / squash -> empty
        - chomper -> 普通可啃食植物，直到对应磁力菇消失
    """
    return _apply_pending_effect()


def _apply_pending_effect() -> Optional[Dict[str, Any]]:
    effect = _STATE.pending_effect
    if effect is None:
        return None

    row = int(effect["row"])
    col = int(effect["col"])
    plant = str(effect["plant"])
    target_magnet = effect.get("target_magnet")

    if target_magnet is not None:
        _STATE.current_magnet_target = (
            int(target_magnet[0]),
            int(target_magnet[1]),
        )

    if plant == "chomper":
        _STATE.standby_chompers.add((row, col))
    elif plant in {"potatomine", "squash"}:
        _STATE.consumed_empty_cells.add((row, col))

    _STATE.pending_effect = None
    _STATE.version += 1

    applied = dict(effect)
    applied["applied"] = True
    applied["state_version"] = _STATE.version
    return applied


def _set_pending_effect_from_candidate(candidate: Dict[str, Any]) -> None:
    """
    如果本轮选择的是 prep 垫尸方案，记录 pending effect。
    等下一次策略更新时把它应用到 effective board。
    """
    if not candidate.get("is_prep"):
        _STATE.pending_effect = None
        return

    _STATE.pending_effect = {
        "row": int(candidate["threat_row"]),
        "col": int(candidate["threat_col"]),
        "plant": str(candidate["target_plant"]),
        "target_magnet": tuple(candidate.get("magnet", (candidate["row"], candidate["objective_col"]))),
        "kind": str(candidate["kind"]),
    }


def _clear_transient_state_if_target_magnet_gone(raw_board: List[List[str]]) -> None:
    """
    如果当前状态绑定的磁力菇已经消失，清空临时状态。

    这样大嘴花在磁力菇被处理后，会恢复为有秒杀性的植物。
    """
    target = _STATE.current_magnet_target
    if target is None:
        return

    row, col = target
    target_still_exists = (
        0 <= row < 5
        and 0 <= col < 5
        and raw_board[row][col] in MAGNET_LABELS
    )

    if target_still_exists:
        return

    _STATE.consumed_empty_cells.clear()
    _STATE.standby_chompers.clear()
    _STATE.pending_effect = None
    _STATE.current_magnet_target = None
    _STATE.version += 1


def _state_debug() -> Dict[str, Any]:
    return {
        "pending_effect": dict(_STATE.pending_effect) if _STATE.pending_effect else None,
        "consumed_empty_cells": [
            {"row": row, "col": col}
            for row, col in sorted(_STATE.consumed_empty_cells)
        ],
        "standby_chompers": [
            {"row": row, "col": col}
            for row, col in sorted(_STATE.standby_chompers)
        ],
        "current_magnet_target": (
            None
            if _STATE.current_magnet_target is None
            else {
                "row": _STATE.current_magnet_target[0],
                "col": _STATE.current_magnet_target[1],
            }
        ),
        "version": _STATE.version,
    }


# ---------------------------------------------------------------------------
# Basic board helpers
# ---------------------------------------------------------------------------

def normalize_plant(label: Any) -> str:
    if label is None:
        return ""

    return (
        str(label)
        .strip()
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
    )


def is_empty(label: str) -> bool:
    return normalize_plant(label) in EMPTY_LABELS


def get_board_5x5(context: BreakContext) -> List[List[str]]:
    board: List[List[str]] = []

    for row in range(5):
        lane: List[str] = []
        for col in range(5):
            try:
                value = context.board_5x5[row][col]
            except (IndexError, TypeError):
                value = ""
            lane.append(normalize_plant(value))
        board.append(lane)

    return board


def apply_state_to_board(raw_board: List[List[str]]) -> List[List[str]]:
    """
    根据磁力菇阶段状态生成 effective board。

    - consumed_empty_cells: 视作 empty
    - standby_chompers: 视作 sunflower，即普通可啃食、无秒杀植物
    """
    board = [list(row) for row in raw_board]

    for row, col in _STATE.consumed_empty_cells:
        if 0 <= row < 5 and 0 <= col < 5:
            board[row][col] = "empty"

    for row, col in _STATE.standby_chompers:
        if 0 <= row < 5 and 0 <= col < 5:
            # 大嘴花已经吃过一个僵尸，临时视为普通可啃食植物。
            board[row][col] = "sunflower"

    return board


def get_effective_lane(board: List[List[str]], row: int) -> List[str]:
    try:
        lane = list(board[row][:5])
    except (IndexError, TypeError):
        lane = ["empty"] * 5

    while len(lane) < 5:
        lane.append("empty")

    return lane[:5]


def find_magnets(board: List[List[str]]) -> List[Tuple[int, int]]:
    magnets: List[Tuple[int, int]] = []

    for row in range(5):
        for col in range(5):
            if board[row][col] in MAGNET_LABELS:
                magnets.append((row, col))

    return magnets


def get_adjacent_threepeater_cols(board: List[List[str]], row: int) -> List[int]:
    """
    获取目标行上下相邻路中的三线射手列号。

    本路三线会被 Row(lane, ...) 正常处理；
    这里只把旁路三线传入 external_threepeaters。
    """
    cols: List[int] = []

    for adj_row in (row - 1, row + 1):
        if adj_row < 0 or adj_row >= 5:
            continue

        for col, plant in enumerate(board[adj_row]):
            if plant in THREEPEATER_LABELS:
                cols.append(col)

    return cols


def has_umbrella_in_3x3(board: List[List[str]], row: int, col: int) -> bool:
    """
    判断磁力菇 3x3 范围内是否有叶子保护伞。
    """
    for rr in range(max(0, row - 1), min(5, row + 2)):
        for cc in range(max(0, col - 1), min(5, col + 2)):
            if board[rr][cc] in UMBRELLA_LABELS:
                return True

    return False


def get_cell(board: List[List[str]], row: int, col: int) -> str:
    if row < 0 or row >= 5 or col < 0 or col >= 5:
        return ""

    return board[row][col]


def is_bungee_safe_for_magnet(board: List[List[str]], row: int, col: int) -> Tuple[bool, str]:
    """
    飞贼抓磁力菇的安全条件。

    当前规则：
        - 磁力菇 3x3 范围没有叶子伞；
        - 磁力菇左侧一格不是窝瓜 / 大嘴花；
        - 不检查磁力菇右侧窝瓜。
    """
    if has_umbrella_in_3x3(board, row, col):
        return False, "磁力菇 3x3 范围内有叶子保护伞"

    left = get_cell(board, row, col - 1)
    if left in {"squash", "chomper"}:
        return False, f"磁力菇左侧一格是 {left}，飞贼会被处理，不能飞"

    return True, "磁力菇 3x3 无叶子伞，且左侧不是窝瓜/大嘴花"


def find_first_magnet_blocker(
    board: List[List[str]],
    row: int,
    magnet_col: int,
) -> Optional[Dict[str, Any]]:
    """
    找到处理磁力菇前必须先解决的阻挡点。

    分两类：
        1. path_instant:
           僵尸从右往左走，在碰到磁力菇前先遇到
           potatomine / squash / chomper。

        2. left_guard:
           磁力菇左侧一格是 squash / chomper。
           这种情况即使僵尸已经在啃磁力菇，也会被左侧植物换掉，
           所以必须纳入计算，不能只看磁力菇右侧路径。
    """
    # 先处理右侧路径阻挡，因为僵尸会先遇到这些植物。
    for col in range(4, magnet_col, -1):
        plant = get_cell(board, row, col)
        if plant in PATH_INSTANT_OR_EATER_LABELS:
            return {
                "blocker_type": "path_instant",
                "row": row,
                "threat_col": col,
                "objective_col": col,
                "plant": plant,
                "include_target": False,
                "reason": "通往磁力菇前的路径上存在秒杀/吃人植物",
            }

    # 再处理磁力菇左侧保护威胁。
    left_col = magnet_col - 1
    left = get_cell(board, row, left_col)

    if left in LEFT_GUARD_LABELS:
        return {
            "blocker_type": "left_guard",
            "row": row,
            "threat_col": left_col,
            # 要走到磁力菇位置才会被左侧窝瓜/大嘴花换掉。
            # 因此目标路径计算到 magnet_col，但不把磁力菇当作已啃掉。
            "objective_col": magnet_col,
            "plant": left,
            "include_target": False,
            "reason": "磁力菇左侧一格存在窝瓜/大嘴花，会在啃磁力菇时换掉僵尸",
        }

    return None


# ---------------------------------------------------------------------------
# Full-path damage calculation, based on control.py
# ---------------------------------------------------------------------------

def replace_spikeweed_with_empty(row: Sequence[int]) -> List[int]:
    return [EMPTY if plant == DC_21 else plant for plant in row]


def apply_pole_postjump_correction(row_obj: Row) -> None:
    if row_obj.mode != MODE_POLE:
        return

    if row_obj.bite_lmt < 0:
        return

    idx = row_obj.bite_lmt - 1

    if idx >= 0 and row_obj.row[idx] == YT_29:
        row_obj.bite[row_obj.bite_lmt] += (
            row_obj.bite[row_obj.bite_lmt] - 10.0
        ) * 0.25
        row_obj.fume_bite[row_obj.bite_lmt] *= 1.25
    elif idx >= 0 and row_obj.row[idx] == JG_3:
        row_obj.bite[row_obj.bite_lmt] += (
            row_obj.bite[row_obj.bite_lmt] / 14.0
        ) * 0.25
        row_obj.fume_bite[row_obj.bite_lmt] *= 1.25
    else:
        row_obj.bite[row_obj.bite_lmt] *= 1.25
        row_obj.fume_bite[row_obj.bite_lmt] *= 1.25


def calc_bite_damage(row_obj: Row, i: int, hbfix: set, torchwood: int) -> float:
    """
    复制控制阵中的 bite 阶段伤害计算。

    综合阵磁力菇阶段禁用铁器僵尸，因此这里不需要 football 的特殊修正。
    """
    bite_dps = row_obj.bite[i] + row_obj.fume_bite[i]

    if row_obj.bite_slowed[i]:
        if row_obj.bite_fire[i]:
            bite_dps *= 1.33
        else:
            bite_dps *= 2.0

    bite_dps *= get_butter_rate(row_obj.bite_butter[i])

    if torchwood != -1 and i == torchwood + 1:
        bite_dps += row_obj.HS_fix

    return bite_dps


def calculate_damage_until_col_raw(
    lane: Sequence[Any],
    mode: int,
    target_col: int,
    *,
    include_target: bool,
    external_threepeaters: Optional[Sequence[int]] = None,
) -> Optional[int]:
    """
    计算某种模式下，僵尸从右侧进入，到处理 target_col 目标为止的受伤。

    target_col 是 0-based：
        0 = 第 1 列
        4 = 第 5 列

    include_target=True：
        计算吃掉 target_col 植物为止。
        用于吃掉磁力菇。

    include_target=False：
        计算到达/触发 target_col 威胁为止，但不把 target_col 当作普通植物啃掉。
        用于垫掉土豆雷 / 窝瓜 / 大嘴花，或者被磁力菇左侧窝瓜/大嘴花换掉。
    """
    row_ids = normalize_lane(lane)
    row_obj = Row(
        row_ids,
        mode,
        external_threepeaters=external_threepeaters or [],
    )

    if mode == MODE_POLE:
        pole_target = row_obj.pole_target_idx

        if pole_target is None or pole_target < 0:
            return None

        # 僵尸从右往左走。
        # 如果撑杆第一跳目标就是当前目标或在当前目标左侧，
        # 则不能视为成功处理当前目标。
        if pole_target <= target_col:
            return None

    row_obj.convert()
    row_obj.add_plants()

    torchwood = row_obj.index_of(HJSZ_22)
    hbfix = row_obj.build_hbfix(include_bite=True)

    if mode == MODE_POLE:
        apply_pole_postjump_correction(row_obj)

    if mode == MODE_POLE:
        bite_end = row_obj.bite_lmt
        walk_end = row_obj.walk_lmt
    else:
        bite_end = 5
        walk_end = 5

    if include_target:
        bite_start = target_col + 1
    else:
        # 不把目标格当作普通植物啃掉，只计算目标右侧需要啃掉的植物。
        bite_start = target_col + 2

    # 走到目标格右边/目标触发位置所需的行走伤害仍然要算。
    walk_start = target_col + 1

    total = 0.0
    has_any_segment = False

    # 吃目标右侧植物；include_target=True 时也吃目标植物本身。
    if bite_start <= bite_end:
        for i in range(max(0, bite_start), min(5, bite_end) + 1):
            total += calc_bite_damage(row_obj, i, hbfix, torchwood)
            has_any_segment = True

    # 从出生点走到目标附近这段路受到的伤害。
    if walk_start <= walk_end:
        for i in range(max(0, walk_start), min(5, walk_end) + 1):
            total += row_obj.calc_walk_segment_damage(i, hbfix)
            has_any_segment = True

    # 撑杆需要额外加跳前行走伤害。
    if mode == MODE_POLE:
        total += row_obj.compute_pole_prejump_damage()
        has_any_segment = True

    if not has_any_segment:
        return None

    return cpp_round(total)


def calculate_damage_until_col(
    lane: Sequence[Any],
    mode: int,
    target_col: int,
    *,
    include_target: bool,
    spike_multiplier: int = 1,
    external_threepeaters: Optional[Sequence[int]] = None,
) -> Optional[int]:
    """
    支持多只路障 / 多只撑杆强吃时的地刺伤害放大。

    做法：
        normal_damage = 正常含地刺算血
        no_spike_damage = 把地刺当 empty 后算血
        spike_damage = normal_damage - no_spike_damage

    最终：
        adjusted = no_spike_damage + spike_damage * spike_multiplier

    这样只放大地刺相关伤害，不会把后排植物、旁路三线、杨桃、玉米等伤害错误放大。
    啃食伤害不削减，偏保守。
    """
    row_ids = normalize_lane(lane)

    normal_damage = calculate_damage_until_col_raw(
        row_ids,
        mode,
        target_col,
        include_target=include_target,
        external_threepeaters=external_threepeaters,
    )

    if normal_damage is None:
        return None

    if spike_multiplier <= 1:
        return normal_damage

    no_spike_row = replace_spikeweed_with_empty(row_ids)
    no_spike_damage = calculate_damage_until_col_raw(
        no_spike_row,
        mode,
        target_col,
        include_target=include_target,
        external_threepeaters=external_threepeaters,
    )

    if no_spike_damage is None:
        return normal_damage

    spike_damage = max(0, normal_damage - no_spike_damage)
    adjusted = no_spike_damage + spike_damage * spike_multiplier

    return int(math.ceil(adjusted))


def is_safe_damage(damage: Optional[int], hp: Optional[int]) -> bool:
    if damage is None or hp is None:
        return False

    return damage <= hp - SAFE_MARGIN


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def make_candidate(
    *,
    row: int,
    action_col: int,
    objective_col: int,
    threat_row: int,
    threat_col: int,
    target_plant: str,
    kind: str,
    zombie: str,
    count: int,
    cost: int,
    damage: Optional[int],
    hp: Optional[int],
    clears_magnet: bool,
    is_prep: bool,
    include_target: bool,
    blocker_type: Optional[str],
    magnet: Tuple[int, int],
    note: str,
) -> Dict[str, Any]:
    if zombie in BANNED_METAL_ZOMBIES:
        raise ValueError(f"综合阵磁力菇阶段禁止使用铁器僵尸: {zombie}")

    return {
        "row": row,
        "action_col": action_col,
        "objective_col": objective_col,
        "threat_row": threat_row,
        "threat_col": threat_col,
        "target_plant": target_plant,
        "kind": kind,
        "zombie": zombie,
        "count": count,
        "cost": cost,
        "damage": damage,
        "hp": hp,
        "safe": is_safe_damage(damage, hp),
        "safe_limit": None if hp is None else hp - SAFE_MARGIN,
        "clears_magnet": clears_magnet,
        "is_prep": is_prep,
        "include_target": include_target,
        "blocker_type": blocker_type,
        "magnet": magnet,
        "note": note,
    }


def candidate_to_actions(candidate: Dict[str, Any]) -> List[BreakAction]:
    """
    把候选方案转成逐个执行的 BreakAction。

    多路障 / 多撑杆不输出 count=2/3，而是拆成多条动作，
    方便后续自动操控时“上一只死亡/目标状态变化后再下下一只”。
    """
    row = int(candidate["row"])
    action_col = int(candidate["action_col"])
    zombie = str(candidate["zombie"])
    count = int(candidate["count"])
    base_note = str(candidate["note"])
    is_prep = bool(candidate.get("is_prep"))

    if zombie == BUNGEE_ZOMBIE:
        return [
            BreakAction(
                zombie=zombie,
                row=row,
                col=action_col,
                count=1,
                note=base_note,
            )
        ]

    actions: List[BreakAction] = []

    for idx in range(count):
        if count == 1:
            note = base_note
        else:
            step_text = f"第 {idx + 1}/{count} 只"
            wait_text = "；确认上一只死亡/目标状态稳定后再下下一只" if idx > 0 else ""
            note = f"{base_note}；{step_text}{wait_text}"

        if is_prep:
            note += "；该阶段是垫掉土豆雷/窝瓜/大嘴花，不视为已经清除磁力菇"

        actions.append(
            BreakAction(
                zombie=zombie,
                row=row,
                count=1,
                note=note,
            )
        )

    return actions


def build_objective_candidate(
    lane: Sequence[Any],
    *,
    row: int,
    action_col: int,
    objective_col: int,
    threat_col: int,
    zombie: str,
    count: int,
    mode: int,
    base_hp: int,
    base_cost: int,
    kind: str,
    target_plant: str,
    clears_magnet: bool,
    is_prep: bool,
    include_target: bool,
    blocker_type: Optional[str],
    magnet: Tuple[int, int],
    external_threepeaters: Sequence[int],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    构造处理某个目标的候选方案。

    吃磁力菇：
        objective_col = magnet_col
        include_target = True

    垫掉右侧路径土豆雷/窝瓜/大嘴花：
        objective_col = threat_col
        include_target = False

    垫掉磁力菇左侧窝瓜/大嘴花：
        objective_col = magnet_col
        threat_col = magnet_col - 1
        include_target = False

    count=2/3 时：
        - 总血量 = base_hp * count；
        - 地刺伤害 = 单只地刺伤害 * count；
        - 啃食伤害不削减。
    """
    damage = calculate_damage_until_col(
        lane,
        mode,
        objective_col,
        include_target=include_target,
        spike_multiplier=count,
        external_threepeaters=external_threepeaters,
    )

    hp = base_hp * count
    ok = damage is not None and damage <= hp
    safe = is_safe_damage(damage, hp)

    attempt = {
        "kind": kind,
        "row": row,
        "action_col": action_col,
        "objective_col": objective_col,
        "threat_col": threat_col,
        "zombie": zombie,
        "count": count,
        "damage": damage,
        "hp": hp,
        "safe": safe,
        "safe_limit": hp - SAFE_MARGIN,
        "spike_multiplier": count,
        "ok": ok,
        "target_plant": target_plant,
        "clears_magnet": clears_magnet,
        "is_prep": is_prep,
        "include_target": include_target,
        "blocker_type": blocker_type,
        "external_threepeaters": list(external_threepeaters),
    }

    if not ok:
        return None, attempt

    display_row = row + 1
    display_action_col = action_col + 1
    display_objective_col = objective_col + 1
    display_threat_col = threat_col + 1

    if clears_magnet:
        target_text = f"吃掉 R{display_row}C{display_objective_col} 磁力菇"
        objective_text = "完整路径算血=吃到磁力菇为止"
    else:
        if blocker_type == "left_guard":
            target_text = (
                f"先垫掉磁力菇左侧 R{display_row}C{display_threat_col} 的 {target_plant}；"
                f"路径计算到 R{display_row}C{display_objective_col} 磁力菇位置"
            )
        else:
            target_text = f"先垫掉 R{display_row}C{display_threat_col} 的 {target_plant}"

        objective_text = (
            "完整路径算血=到达并换掉秒杀/吃人植物，"
            "不把该目标当普通植物完整啃掉"
        )

    if count == 1:
        count_text = "单"
    else:
        count_text = f"{count} 只"

    safe_text = (
        f"安全阈值达成：{damage} <= {hp - SAFE_MARGIN}"
        if safe
        else f"可行但不在安全阈值内：{damage} <= {hp}，但 > {hp - SAFE_MARGIN}"
    )

    threepeater_text = (
        f"；旁路三线列={list(external_threepeaters)}"
        if external_threepeaters
        else ""
    )

    note = (
        f"R{display_row}C{display_action_col}: 综合阵磁力菇阶段禁用铁器僵尸；"
        f"{count_text}{zombie} {target_text}，"
        f"受伤={damage}，总血量={hp}，{safe_text}。"
        f"{objective_text}；"
        f"计算规则：本路后排植物完整参与算血，旁路三线参与算血{threepeater_text}；"
        f"{count} 只视作一只 {count} 倍血量僵尸，"
        f"地刺伤害乘以 {count}，啃食受伤不削减"
    )

    candidate = make_candidate(
        row=row,
        action_col=action_col,
        objective_col=objective_col,
        threat_row=row,
        threat_col=threat_col,
        target_plant=target_plant,
        kind=kind,
        zombie=zombie,
        count=count,
        cost=base_cost * count,
        damage=damage,
        hp=hp,
        clears_magnet=clears_magnet,
        is_prep=is_prep,
        include_target=include_target,
        blocker_type=blocker_type,
        magnet=magnet,
        note=note,
    )

    return candidate, attempt


def build_stage4_prep_candidates(
    lane: Sequence[Any],
    *,
    row: int,
    blocker: Dict[str, Any],
    magnet: Tuple[int, int],
    external_threepeaters: Sequence[int],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    第 4 点：垫掉土豆雷 / 窝瓜 / 大嘴花。

    这里禁用铁器僵尸，只考虑：
        1/2/3 路障
        1/2/3 撑杆

    对 potatomine / squash / chomper 使用 include_target=False：
        代表“换掉它”，不是把它当普通植物完整啃掉。
    """
    candidates: List[Dict[str, Any]] = []
    attempts: List[Dict[str, Any]] = []

    objective_col = int(blocker["objective_col"])
    threat_col = int(blocker["threat_col"])
    target_plant = str(blocker["plant"])
    blocker_type = str(blocker["blocker_type"])

    for count in (1, 2, 3):
        candidate, attempt = build_objective_candidate(
            lane,
            row=row,
            action_col=threat_col,
            objective_col=objective_col,
            threat_col=threat_col,
            zombie="cone",
            count=count,
            mode=MODE_SLOW,
            base_hp=CONE_HP,
            base_cost=CONE_COST,
            kind=f"prep_{count}_cone",
            target_plant=target_plant,
            clears_magnet=False,
            is_prep=True,
            include_target=False,
            blocker_type=blocker_type,
            magnet=magnet,
            external_threepeaters=external_threepeaters,
        )
        attempts.append(attempt)
        if candidate is not None:
            candidates.append(candidate)

        candidate, attempt = build_objective_candidate(
            lane,
            row=row,
            action_col=threat_col,
            objective_col=objective_col,
            threat_col=threat_col,
            zombie="pole",
            count=count,
            mode=MODE_POLE,
            base_hp=POLE_HP,
            base_cost=POLE_COST,
            kind=f"prep_{count}_pole",
            target_plant=target_plant,
            clears_magnet=False,
            is_prep=True,
            include_target=False,
            blocker_type=blocker_type,
            magnet=magnet,
            external_threepeaters=external_threepeaters,
        )
        attempts.append(attempt)
        if candidate is not None:
            candidates.append(candidate)

    return candidates, attempts


def build_stage4_force_candidates(
    lane: Sequence[Any],
    *,
    row: int,
    magnet_col: int,
    external_threepeaters: Sequence[int],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    第 4 点：不能飞时，使用双/三路障或双/三撑杆强吃磁力菇。

    暂时不考虑路障 + 撑杆混合。
    """
    candidates: List[Dict[str, Any]] = []
    attempts: List[Dict[str, Any]] = []
    magnet = (row, magnet_col)

    for count in (2, 3):
        candidate, attempt = build_objective_candidate(
            lane,
            row=row,
            action_col=magnet_col,
            objective_col=magnet_col,
            threat_col=magnet_col,
            zombie="cone",
            count=count,
            mode=MODE_SLOW,
            base_hp=CONE_HP,
            base_cost=CONE_COST,
            kind=f"force_{count}_cone",
            target_plant="magnetshroom",
            clears_magnet=True,
            is_prep=False,
            include_target=True,
            blocker_type=None,
            magnet=magnet,
            external_threepeaters=external_threepeaters,
        )
        attempts.append(attempt)
        if candidate is not None:
            candidates.append(candidate)

        candidate, attempt = build_objective_candidate(
            lane,
            row=row,
            action_col=magnet_col,
            objective_col=magnet_col,
            threat_col=magnet_col,
            zombie="pole",
            count=count,
            mode=MODE_POLE,
            base_hp=POLE_HP,
            base_cost=POLE_COST,
            kind=f"force_{count}_pole",
            target_plant="magnetshroom",
            clears_magnet=True,
            is_prep=False,
            include_target=True,
            blocker_type=None,
            magnet=magnet,
            external_threepeaters=external_threepeaters,
        )
        attempts.append(attempt)
        if candidate is not None:
            candidates.append(candidate)

    return candidates, attempts


def build_magnet_candidates_for_one(
    board: List[List[str]],
    row: int,
    col: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    为单个磁力菇生成处理方案。
    """
    display_row = row + 1
    display_col = col + 1

    lane = get_effective_lane(board, row)
    external_threepeaters = get_adjacent_threepeater_cols(board, row)
    magnet = (row, col)

    candidates: List[Dict[str, Any]] = []
    attempts: List[Dict[str, Any]] = []

    blocker = find_first_magnet_blocker(board, row, col)
    blocked = blocker is not None

    # -------------------------------------------------------------
    # 1. 单路障 / 单撑杆能否直接吃掉磁力菇。
    #    如果有右侧路径阻挡，或磁力菇左侧有窝瓜/大嘴花保护，
    #    则不能视为能直接吃磁力菇。
    # -------------------------------------------------------------
    if not blocked:
        single_cone, attempt = build_objective_candidate(
            lane,
            row=row,
            action_col=col,
            objective_col=col,
            threat_col=col,
            zombie="cone",
            count=1,
            mode=MODE_SLOW,
            base_hp=CONE_HP,
            base_cost=CONE_COST,
            kind="single_cone",
            target_plant="magnetshroom",
            clears_magnet=True,
            is_prep=False,
            include_target=True,
            blocker_type=None,
            magnet=magnet,
            external_threepeaters=external_threepeaters,
        )
        attempt["stage"] = "single_check"
        attempts.append(attempt)
        if single_cone is not None:
            candidates.append(single_cone)

        single_pole, attempt = build_objective_candidate(
            lane,
            row=row,
            action_col=col,
            objective_col=col,
            threat_col=col,
            zombie="pole",
            count=1,
            mode=MODE_POLE,
            base_hp=POLE_HP,
            base_cost=POLE_COST,
            kind="single_pole",
            target_plant="magnetshroom",
            clears_magnet=True,
            is_prep=False,
            include_target=True,
            blocker_type=None,
            magnet=magnet,
            external_threepeaters=external_threepeaters,
        )
        attempt["stage"] = "single_check"
        attempts.append(attempt)
        if single_pole is not None:
            candidates.append(single_pole)
    else:
        attempts.append(
            {
                "stage": "single_check",
                "kind": "blocked_by_instant_or_left_guard",
                "row": row,
                "col": col,
                "blocker": blocker,
                "ok": False,
                "reason": (
                    f"处理 R{display_row}C{display_col} 磁力菇前，"
                    f"需要先处理 {blocker['blocker_type']}："
                    f"R{display_row}C{int(blocker['threat_col']) + 1} 的 {blocker['plant']}"
                ),
                "external_threepeaters": list(external_threepeaters),
            }
        )

    single_ok = any(
        candidate.get("clears_magnet")
        and candidate.get("kind") in {"single_cone", "single_pole"}
        for candidate in candidates
    )

    # -------------------------------------------------------------
    # 2. 单破不行时，检查飞贼。
    #    飞贼只看：3x3 无叶子伞 + 左侧不是窝瓜/大嘴花。
    # -------------------------------------------------------------
    bungee_safe, bungee_reason = is_bungee_safe_for_magnet(board, row, col)
    attempts.append(
        {
            "stage": "bungee_check",
            "kind": "bungee",
            "row": row,
            "col": col,
            "ok": (not single_ok and bungee_safe),
            "reason": bungee_reason,
            "external_threepeaters": list(external_threepeaters),
        }
    )

    if not single_ok and bungee_safe:
        candidates.append(
            make_candidate(
                row=row,
                action_col=col,
                objective_col=col,
                threat_row=row,
                threat_col=col,
                target_plant="magnetshroom",
                kind="bungee",
                zombie=BUNGEE_ZOMBIE,
                count=1,
                cost=BUNGEE_COST,
                damage=None,
                hp=None,
                clears_magnet=True,
                is_prep=False,
                include_target=True,
                blocker_type=None,
                magnet=magnet,
                note=(
                    f"R{display_row}C{display_col}: 单路障/单撑杆不能直接吃磁力菇；"
                    f"{bungee_reason}，使用飞贼抓掉磁力菇"
                ),
            )
        )

    # -------------------------------------------------------------
    # 3. 不能飞时，进入第 4 点。
    #    若有土豆雷 / 窝瓜 / 大嘴花阻挡，先输出逐个垫掉阻挡点；
    #    否则尝试双/三路障或双/三撑杆强吃磁力菇。
    # -------------------------------------------------------------
    if not single_ok and not bungee_safe:
        if blocker is not None:
            prep_candidates, prep_attempts = build_stage4_prep_candidates(
                lane,
                row=row,
                blocker=blocker,
                magnet=magnet,
                external_threepeaters=external_threepeaters,
            )

            for attempt in prep_attempts:
                attempt["stage"] = "stage4_prep_blocker"
                attempt["magnet_col"] = col
                attempt["blocker"] = blocker

            attempts.extend(prep_attempts)
            candidates.extend(prep_candidates)
        else:
            force_candidates, force_attempts = build_stage4_force_candidates(
                lane,
                row=row,
                magnet_col=col,
                external_threepeaters=external_threepeaters,
            )

            for attempt in force_attempts:
                attempt["stage"] = "stage4_force_magnet"

            attempts.extend(force_attempts)
            candidates.extend(force_candidates)

    for attempt in attempts:
        attempt.setdefault("row", row)
        attempt.setdefault("col", col)
        attempt["has_umbrella_3x3"] = has_umbrella_in_3x3(board, row, col)
        attempt["banned_metal_zombies"] = sorted(BANNED_METAL_ZOMBIES)

    return candidates, attempts


def choose_best_magnet_plan(
    board: List[List[str]],
    magnets: List[Tuple[int, int]],
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    all_candidates: List[Dict[str, Any]] = []
    all_attempts: List[Dict[str, Any]] = []

    for row, col in magnets:
        candidates, attempts = build_magnet_candidates_for_one(
            board,
            row,
            col,
        )
        all_candidates.extend(candidates)
        all_attempts.extend(attempts)

    if not all_candidates:
        return None, all_candidates, all_attempts

    # 如果存在真正能清掉磁力菇的方案，优先清磁力菇；
    # 如果都被土豆雷 / 窝瓜 / 大嘴花卡住且无法飞，再选垫掉阻挡点的方案。
    clearing_candidates = [
        candidate for candidate in all_candidates
        if candidate.get("clears_magnet")
    ]
    candidate_pool = clearing_candidates if clearing_candidates else all_candidates

    stage_priority = {
        "single_cone": 0,
        "single_pole": 0,
        "bungee": 1,
        "force_2_cone": 2,
        "force_2_pole": 2,
        "force_3_cone": 3,
        "force_3_pole": 3,
        "prep_1_cone": 4,
        "prep_1_pole": 4,
        "prep_2_cone": 5,
        "prep_2_pole": 5,
        "prep_3_cone": 6,
        "prep_3_pole": 6,
    }

    # 同阳光、同阶段都安全时，优先路障。
    zombie_priority = {
        "cone": 0,
        "pole": 1,
        BUNGEE_ZOMBIE: 2,
    }

    def sort_key(candidate: Dict[str, Any]) -> Tuple[int, int, int, int, int, int]:
        kind = str(candidate["kind"])
        damage = candidate.get("damage")
        damage_sort = int(damage) if isinstance(damage, int) else 999999

        safe_sort = 0 if candidate.get("safe") else 1
        zombie_sort = zombie_priority.get(str(candidate.get("zombie")), 9)

        return (
            int(candidate["cost"]),
            stage_priority.get(kind, 99),
            safe_sort,
            zombie_sort,
            damage_sort,
            int(candidate["row"]) * 10 + int(candidate["action_col"]),
        )

    candidate_pool.sort(key=sort_key)
    return candidate_pool[0], all_candidates, all_attempts


# ---------------------------------------------------------------------------
# Main solve
# ---------------------------------------------------------------------------

def solve(context: BreakContext) -> BreakPlan:
    if AUTO_APPLY_PENDING_EFFECT_ON_SOLVE:
        applied_effect = _apply_pending_effect()
    else:
        applied_effect = None

    raw_board = get_board_5x5(context)
    _clear_transient_state_if_target_magnet_gone(raw_board)

    board = apply_state_to_board(raw_board)
    magnets = find_magnets(board)

    # -------------------------------------------------------------
    # 没有磁力菇：后续综合阵破阵策略暂未实现。
    # -------------------------------------------------------------
    if not magnets:
        return BreakPlan(
            theme=THEME_NAME,
            actions=[],
            confidence=0.35,
            reason=(
                "综合阵未检测到磁力菇；第一阶段磁力菇处理已结束，"
                "临时大嘴花/灰烬状态已清空；"
                "后续三线 / 杨桃 / 常规单破策略待补充。"
            ),
            debug={
                "strategy": "hybrid",
                "stage": "after_magnet",
                "magnets": [],
                "todo": "综合阵后续策略待补充",
                "applied_effect": applied_effect,
                "state": _state_debug(),
                "raw_board": raw_board,
                "effective_board": board,
            },
        )

    best, all_candidates, all_attempts = choose_best_magnet_plan(
        board,
        magnets,
    )

    # -------------------------------------------------------------
    # 有磁力菇，但当前规则没有找到可行处理。
    # -------------------------------------------------------------
    if best is None:
        _STATE.pending_effect = None

        return BreakPlan(
            theme=THEME_NAME,
            actions=[],
            confidence=0.45,
            reason=(
                "综合阵检测到磁力菇，但当前磁力菇处理规则下没有找到可行方案："
                "单路障/单撑杆不可直接吃磁力菇；飞贼条件不满足；"
                "第4点的垫僵尸或双/三路障/撑杆强吃也不可行。"
            ),
            debug={
                "strategy": "hybrid",
                "stage": "magnet_first",
                "magnets": [{"row": r, "col": c} for r, c in magnets],
                "candidates": all_candidates,
                "attempts": all_attempts,
                "banned_metal_zombies": sorted(BANNED_METAL_ZOMBIES),
                "applied_effect": applied_effect,
                "state": _state_debug(),
                "raw_board": raw_board,
                "effective_board": board,
            },
        )

    _set_pending_effect_from_candidate(best)
    actions = candidate_to_actions(best)

    display_row = int(best["row"]) + 1
    display_col = int(best["action_col"]) + 1

    if best.get("clears_magnet"):
        reason_tail = "该方案目标是清除磁力菇；磁力菇清除后，后续综合阵策略暂待补充。"
    else:
        target_plant = best.get("target_plant")
        blocker_type = best.get("blocker_type")

        if blocker_type == "left_guard" and target_plant == "chomper":
            state_text = (
                "下一次策略更新时，该大嘴花会临时视作普通可啃食植物，"
                "直到对应磁力菇消失后恢复为秒杀性植物。"
            )
        elif blocker_type == "left_guard":
            state_text = "下一次策略更新时，该左侧保护威胁会按已处理状态参与重新判断。"
        elif target_plant == "chomper":
            state_text = (
                "下一次策略更新时，该大嘴花会临时视作普通可啃食植物，"
                "直到对应磁力菇消失后恢复为秒杀性植物。"
            )
        else:
            state_text = "下一次策略更新时，该植物会按已消耗状态参与重新判断。"

        reason_tail = (
            f"该方案只是先垫掉 {target_plant}；"
            f"{state_text}"
        )

    safe_text = (
        "满足安全阈值"
        if best.get("safe")
        else "可行但未满足 HP-3 安全阈值"
    )

    return BreakPlan(
        theme=THEME_NAME,
        actions=actions,
        confidence=0.9,
        reason=(
            "综合阵第一阶段：检测到磁力菇，优先处理磁力菇；"
            "磁力菇存在时禁用 bucket / football / ladder / pole_ladder 等铁器僵尸；"
            "算血使用完整本路路径，并加入旁路三线；"
            "磁力菇左侧窝瓜/大嘴花会作为保护威胁先处理；"
            f"选择方案处理 R{display_row}C{display_col}："
            f"{best['kind']}，预计阳光={best['cost']}，{safe_text}。"
            f"{reason_tail}"
        ),
        debug={
            "strategy": "hybrid",
            "stage": "magnet_first",
            "selected": best,
            "magnets": [{"row": r, "col": c} for r, c in magnets],
            "candidates": all_candidates,
            "attempts": all_attempts,
            "cone_hp": CONE_HP,
            "pole_hp": POLE_HP,
            "safe_margin": SAFE_MARGIN,
            "bungee_zombie_name": BUNGEE_ZOMBIE,
            "banned_metal_zombies": sorted(BANNED_METAL_ZOMBIES),
            "applied_effect": applied_effect,
            "state": _state_debug(),
            "raw_board": raw_board,
            "effective_board": board,
        },
    )
