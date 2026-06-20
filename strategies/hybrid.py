# -*- coding: utf-8 -*-
"""
综合阵破阵策略。

当前只实现第一阶段：优先处理磁力菇。

修正版要点：
    1. 不使用“裁掉后排”的局部 lane；
       本路目标右侧植物、啃食伤害、行走伤害、相邻路三线伤害都要计算。
       这里直接参考 control.py 的 calculate_damage_until_col() 写法。
    2. 对“吃掉磁力菇”：
       使用原始 lane，计算到吃掉 magnetshroom 这一列为止的承伤。
    3. 对“换掉土豆雷 / 窝瓜 / 大嘴花”：
       使用完整 lane，但只把目标格临时视作 empty；
       代表僵尸到达该格后触发/被吃，不把目标当普通可啃植物完整啃掉。
    4. 若单路障、单撑杆都满足安全阈值 damage <= HP - 3，
       且花费相同，优先选择路障。
    5. 磁力菇存在时，ban 所有铁器僵尸。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.breaker_types import BreakAction, BreakContext, BreakPlan
from core.ize_blood_calculator import (
    Row,
    MODE_SLOW,
    MODE_POLE,
    MODE_FOOTBALL,
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

# 如果自动操控模块里的名称不同，只需要改这里。
BUNGEE_ZOMBIE = "bungee"
CONE_ZOMBIE = "cone"
POLE_ZOMBIE = "pole"

# 阳光估算。
CONE_COST = 75
POLE_COST = 75
BUNGEE_COST = 125

# 血量判定。
CONE_HP = 27
POLE_HP = 17

# 安全阈值：<= HP - 3 才算安全。
SAFE_MARGIN = 3

# 磁力菇阶段明确禁用铁器僵尸。
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
INSTANT_OR_EATER_LABELS = {"potatomine", "squash", "chomper"}


# ---------------------------------------------------------------------------
# Basic helpers
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


def is_empty_like(label: str) -> bool:
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


def get_raw_lane(context: BreakContext, row: int) -> List[Any]:
    try:
        lane = list(context.board_5x5[row][:5])
    except (IndexError, TypeError):
        lane = ["empty"] * 5

    while len(lane) < 5:
        lane.append("empty")

    return lane[:5]


def get_cell(board: List[List[str]], row: int, col: int) -> str:
    if row < 0 or row >= 5 or col < 0 or col >= 5:
        return ""
    return board[row][col]


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

    本路三线会被 lane 自己算进去；
    这里只额外传入相邻两路三线，和 control.py 的磁力菇处理一致。
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
    for rr in range(max(0, row - 1), min(5, row + 2)):
        for cc in range(max(0, col - 1), min(5, col + 2)):
            if board[rr][cc] in UMBRELLA_LABELS:
                return True

    return False


def is_bungee_safe_for_magnet(board: List[List[str]], row: int, col: int) -> Tuple[bool, str]:
    """
    飞贼抓磁力菇的安全条件。

    当前综合阵规则：
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


def find_first_blocking_instant_on_path(
    board: List[List[str]],
    row: int,
    magnet_col: int,
) -> Optional[Tuple[int, str]]:
    """
    找到通往磁力菇路上的第一个土豆雷 / 窝瓜 / 大嘴花。

    IZE 僵尸从右往左走，所以处理磁力菇时，会先经过 col=4,3,2...
    如果这些位置存在土豆雷 / 窝瓜 / 大嘴花，地面僵尸会先换掉它们。
    """
    for col in range(4, magnet_col - 1, -1):
        plant = get_cell(board, row, col)
        if plant in INSTANT_OR_EATER_LABELS:
            return col, plant

    return None


def parse_damage_value(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return int(math.ceil(float(value)))

    if isinstance(value, dict):
        for key in ("value", "damage", "blood", "hp", "result"):
            if key in value:
                parsed = parse_damage_value(value[key])
                if parsed is not None:
                    return parsed
        return None

    if isinstance(value, (tuple, list)):
        for item in value:
            parsed = parse_damage_value(item)
            if parsed is not None:
                return parsed
        return None

    text = str(value).strip()
    if not text or text == "-":
        return None

    text = (
        text.replace("*", "")
        .replace("(", "")
        .replace(")", "")
        .replace(" ", "")
    )

    if not text or text == "-":
        return None

    if "+" in text:
        parts = [parse_damage_value(part) for part in text.split("+")]
        if any(part is None for part in parts):
            return None
        return int(sum(part for part in parts if part is not None))

    try:
        return int(math.ceil(float(text)))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Damage calculation: same idea as control.py, with objective adaptation
# ---------------------------------------------------------------------------

def replace_spikeweed_with_empty(row: Sequence[int]) -> List[int]:
    return [EMPTY if plant == DC_21 else plant for plant in row]


def replace_target_with_empty(row: Sequence[int], target_col: int) -> List[int]:
    """
    换掉土豆雷 / 窝瓜 / 大嘴花时使用。

    只把目标格视作 empty：
        - 不裁掉本路后排植物；
        - 不裁掉旁路三线；
        - 不把目标植物按普通可啃植物完整啃掉。
    """
    result = list(row)
    if 0 <= target_col < len(result):
        result[target_col] = EMPTY
    return result


def apply_pole_postjump_correction(row_obj: Row) -> None:
    """
    复制 control.py / Row.compute() 里的撑杆跳后修正。
    """
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
    复制 control.py 的 bite 阶段伤害计算。

    综合阵磁力菇阶段禁用 football，因此保留 MODE_FOOTBALL 分支只是为了和原算血器逻辑兼容。
    """
    bite_dps = row_obj.bite[i] + row_obj.fume_bite[i]

    if row_obj.bite_slowed[i]:
        if row_obj.bite_fire[i]:
            bite_dps *= 1.33
        else:
            bite_dps *= 2.0
    elif i in hbfix:
        if not row_obj.bite_fire[i]:
            if row_obj.mode == MODE_FOOTBALL:
                if (i - 1) in row_obj.wallnuts:
                    bite_dps += bite_dps / 14.0 * 0.5
                else:
                    bite_dps *= 1.5

    bite_dps *= get_butter_rate(row_obj.bite_butter[i])

    if torchwood != -1 and i == torchwood + 1:
        bite_dps += row_obj.HS_fix

    return bite_dps


def calculate_damage_until_col_raw(
    lane: Sequence[Any],
    mode: int,
    target_col: int,
    *,
    external_threepeaters: Optional[Sequence[int]] = None,
) -> Optional[int]:
    """
    计算某种模式下，僵尸从右侧进入，到“处理 target_col 这一列”为止的承伤。

    这是 control.py 的磁力菇局部算血方式：
        - 本路后排 / 右侧植物保留；
        - 相邻路三线通过 external_threepeaters 传入；
        - 不要求单破整路；
        - 只算到目标列。
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
        # 如果撑杆第一跳目标就是当前目标，或者在目标左侧，
        # 都不能视为“处理掉目标”。
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

    bite_start = target_col + 1
    walk_start = target_col + 1

    if bite_start > bite_end:
        return None

    total = 0.0

    # 吃目标以及目标右侧路径植物时受到的伤害。
    for i in range(max(0, bite_start), min(5, bite_end) + 1):
        total += calc_bite_damage(row_obj, i, hbfix, torchwood)

    # 从出生点走到目标右侧这段路受到的伤害。
    for i in range(max(0, walk_start), min(5, walk_end) + 1):
        total += row_obj.calc_walk_segment_damage(i, hbfix)

    # 撑杆需要额外计算跳前行走伤害。
    if mode == MODE_POLE:
        total += row_obj.compute_pole_prejump_damage()

    return cpp_round(total)


def calculate_damage_until_col(
    lane: Sequence[Any],
    mode: int,
    target_col: int,
    *,
    spike_multiplier: int = 1,
    external_threepeaters: Optional[Sequence[int]] = None,
    target_as_empty: bool = False,
) -> Optional[int]:
    """
    目标算血入口。

    target_as_empty=False:
        用于吃掉磁力菇。目标格保留，代表要把目标植物吃掉。

    target_as_empty=True:
        用于换掉土豆雷 / 窝瓜 / 大嘴花。只把目标格临时设为 empty，
        其他本路后排植物和相邻路三线全部保留。

    spike_multiplier:
        双/三路障或双/三撑杆时，只放大地刺伤害；
        啃食伤害不削减，偏保守。
    """
    row_ids = normalize_lane(lane)

    if target_as_empty:
        row_ids = replace_target_with_empty(row_ids, target_col)

    normal_damage = calculate_damage_until_col_raw(
        row_ids,
        mode,
        target_col,
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


def is_ok_damage(damage: Optional[int], hp: Optional[int]) -> bool:
    if damage is None or hp is None:
        return False
    return damage <= hp


# ---------------------------------------------------------------------------
# Candidate helpers
# ---------------------------------------------------------------------------

def make_candidate(
    *,
    row: int,
    col: int,
    kind: str,
    zombie: str,
    count: int,
    cost: int,
    damage: Optional[int],
    hp: Optional[int],
    clears_magnet: bool,
    is_prep: bool,
    target_plant: str,
    target_as_empty: bool,
    external_threepeaters: Sequence[int],
    note: str,
) -> Dict[str, Any]:
    if zombie in BANNED_METAL_ZOMBIES:
        raise ValueError(f"综合阵磁力菇阶段禁止使用铁器僵尸: {zombie}")

    return {
        "row": row,
        "col": col,
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
        "target_plant": target_plant,
        "target_as_empty": target_as_empty,
        "external_threepeaters": list(external_threepeaters),
        "note": note,
    }


def candidate_to_actions(candidate: Dict[str, Any]) -> List[BreakAction]:
    """
    多路障 / 多撑杆拆成逐条动作。
    """
    row = int(candidate["row"])
    col = int(candidate["col"])
    zombie = str(candidate["zombie"])
    count = int(candidate["count"])
    base_note = str(candidate["note"])
    is_prep = bool(candidate.get("is_prep"))

    if zombie == BUNGEE_ZOMBIE:
        return [
            BreakAction(
                zombie=zombie,
                row=row,
                col=col,
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
            note += "；该阶段只是换掉土豆雷/窝瓜/大嘴花，不视为已经清除磁力菇"

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
    col: int,
    zombie: str,
    count: int,
    mode: int,
    base_hp: int,
    base_cost: int,
    kind: str,
    target_plant: str,
    clears_magnet: bool,
    is_prep: bool,
    target_as_empty: bool,
    external_threepeaters: Sequence[int],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    构造“处理当前目标列”为止的候选方案。

    clears_magnet=True:
        目标是吃掉磁力菇，target_as_empty=False。

    is_prep=True:
        目标是换掉土豆雷 / 窝瓜 / 大嘴花，target_as_empty=True。
    """
    damage = calculate_damage_until_col(
        lane,
        mode,
        col,
        spike_multiplier=count,
        external_threepeaters=external_threepeaters,
        target_as_empty=target_as_empty,
    )
    hp = base_hp * count
    ok = is_ok_damage(damage, hp)
    safe = is_safe_damage(damage, hp)

    attempt = {
        "kind": kind,
        "row": row,
        "col": col,
        "zombie": zombie,
        "count": count,
        "damage": damage,
        "hp": hp,
        "safe": safe,
        "safe_limit": hp - SAFE_MARGIN,
        "spike_multiplier": count,
        "ok": ok,
        "target_plant": target_plant,
        "target_as_empty": target_as_empty,
        "clears_magnet": clears_magnet,
        "is_prep": is_prep,
        "external_threepeaters": list(external_threepeaters),
    }

    if not ok:
        return None, attempt

    display_row = row + 1
    display_col = col + 1

    if clears_magnet:
        target_text = f"吃掉 R{display_row}C{display_col} 磁力菇"
        calc_text = "目标格保留，计算到吃掉磁力菇为止"
    else:
        target_text = f"换掉 R{display_row}C{display_col} 的 {target_plant}"
        calc_text = "只把目标格临时视作 empty，保留本路后排和旁路三线伤害"

    if count == 1:
        count_text = "单"
    else:
        count_text = f"{count} 只"

    safe_text = (
        f"安全阈值达成：{damage} <= {hp - SAFE_MARGIN}"
        if safe
        else f"可行但未达安全阈值：{damage} <= {hp}，但 > {hp - SAFE_MARGIN}"
    )

    note = (
        f"R{display_row}C{display_col}: 综合阵磁力菇阶段禁用铁器僵尸；"
        f"{count_text}{zombie} {target_text}，"
        f"受伤={damage}，总血量={hp}，{safe_text}。"
        f"{calc_text}；"
        f"相邻路三线列={list(external_threepeaters)}；"
        f"{count} 只视作一只 {count} 倍血量僵尸，"
        f"地刺伤害乘以 {count}，啃食受伤不削减"
    )

    candidate = make_candidate(
        row=row,
        col=col,
        kind=kind,
        zombie=zombie,
        count=count,
        cost=base_cost * count,
        damage=damage,
        hp=hp,
        clears_magnet=clears_magnet,
        is_prep=is_prep,
        target_plant=target_plant,
        target_as_empty=target_as_empty,
        external_threepeaters=external_threepeaters,
        note=note,
    )

    return candidate, attempt


def build_stage4_prep_candidates(
    lane: Sequence[Any],
    *,
    row: int,
    blocker_col: int,
    blocker_plant: str,
    external_threepeaters: Sequence[int],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    第 4 点：如果路上先遇到土豆雷 / 窝瓜 / 大嘴花，
    输出逐个垫僵尸方案，解决该阻挡点后等待重新识别。

    这里不使用铁器僵尸，只考虑：
        1/2/3 路障
        1/2/3 撑杆

    如果你后面想强制第 4 点只用双/三，把 counts 改成 (2, 3) 即可。
    """
    candidates: List[Dict[str, Any]] = []
    attempts: List[Dict[str, Any]] = []

    for count in (1, 2, 3):
        candidate, attempt = build_objective_candidate(
            lane,
            row=row,
            col=blocker_col,
            zombie=CONE_ZOMBIE,
            count=count,
            mode=MODE_SLOW,
            base_hp=CONE_HP,
            base_cost=CONE_COST,
            kind=f"prep_{count}_cone",
            target_plant=blocker_plant,
            clears_magnet=False,
            is_prep=True,
            target_as_empty=True,
            external_threepeaters=external_threepeaters,
        )
        attempts.append(attempt)
        if candidate is not None:
            candidates.append(candidate)

        candidate, attempt = build_objective_candidate(
            lane,
            row=row,
            col=blocker_col,
            zombie=POLE_ZOMBIE,
            count=count,
            mode=MODE_POLE,
            base_hp=POLE_HP,
            base_cost=POLE_COST,
            kind=f"prep_{count}_pole",
            target_plant=blocker_plant,
            clears_magnet=False,
            is_prep=True,
            target_as_empty=True,
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
    第 4 点：不能飞时，双/三路障或双/三撑杆强吃磁力菇。
    不考虑路障 + 撑杆混合。
    """
    candidates: List[Dict[str, Any]] = []
    attempts: List[Dict[str, Any]] = []

    for count in (2, 3):
        candidate, attempt = build_objective_candidate(
            lane,
            row=row,
            col=magnet_col,
            zombie=CONE_ZOMBIE,
            count=count,
            mode=MODE_SLOW,
            base_hp=CONE_HP,
            base_cost=CONE_COST,
            kind=f"force_{count}_cone",
            target_plant="magnetshroom",
            clears_magnet=True,
            is_prep=False,
            target_as_empty=False,
            external_threepeaters=external_threepeaters,
        )
        attempts.append(attempt)
        if candidate is not None:
            candidates.append(candidate)

        candidate, attempt = build_objective_candidate(
            lane,
            row=row,
            col=magnet_col,
            zombie=POLE_ZOMBIE,
            count=count,
            mode=MODE_POLE,
            base_hp=POLE_HP,
            base_cost=POLE_COST,
            kind=f"force_{count}_pole",
            target_plant="magnetshroom",
            clears_magnet=True,
            is_prep=False,
            target_as_empty=False,
            external_threepeaters=external_threepeaters,
        )
        attempts.append(attempt)
        if candidate is not None:
            candidates.append(candidate)

    return candidates, attempts


def build_magnet_candidates_for_one(
    context: BreakContext,
    board: List[List[str]],
    row: int,
    col: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    为单个磁力菇生成处理方案。
    """
    display_row = row + 1
    display_col = col + 1
    lane = get_raw_lane(context, row)
    external_threepeaters = get_adjacent_threepeater_cols(board, row)

    candidates: List[Dict[str, Any]] = []
    attempts: List[Dict[str, Any]] = []

    blocking_instant = find_first_blocking_instant_on_path(board, row, col)
    blocked_by_instant = blocking_instant is not None

    # -------------------------------------------------------------
    # 1. 单路障 / 单撑杆能否直接吃掉磁力菇。
    #    如果路上先遇到土豆雷 / 窝瓜 / 大嘴花，则地面僵尸不能直接吃磁力菇。
    # -------------------------------------------------------------
    if not blocked_by_instant:
        candidate, attempt = build_objective_candidate(
            lane,
            row=row,
            col=col,
            zombie=CONE_ZOMBIE,
            count=1,
            mode=MODE_SLOW,
            base_hp=CONE_HP,
            base_cost=CONE_COST,
            kind="single_cone",
            target_plant="magnetshroom",
            clears_magnet=True,
            is_prep=False,
            target_as_empty=False,
            external_threepeaters=external_threepeaters,
        )
        attempt["stage"] = "single_check"
        attempts.append(attempt)
        if candidate is not None:
            candidates.append(candidate)

        candidate, attempt = build_objective_candidate(
            lane,
            row=row,
            col=col,
            zombie=POLE_ZOMBIE,
            count=1,
            mode=MODE_POLE,
            base_hp=POLE_HP,
            base_cost=POLE_COST,
            kind="single_pole",
            target_plant="magnetshroom",
            clears_magnet=True,
            is_prep=False,
            target_as_empty=False,
            external_threepeaters=external_threepeaters,
        )
        attempt["stage"] = "single_check"
        attempts.append(attempt)
        if candidate is not None:
            candidates.append(candidate)
    else:
        blocker_col, blocker_plant = blocking_instant
        attempts.append(
            {
                "stage": "single_check",
                "kind": "blocked_by_instant_or_eater",
                "row": row,
                "col": col,
                "blocker_col": blocker_col,
                "blocker_plant": blocker_plant,
                "ok": False,
                "reason": (
                    f"通往 R{display_row}C{display_col} 磁力菇前，"
                    f"会先遇到 {blocker_plant}，地面僵尸不能直接吃磁力菇"
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
    # 2. 单吃不行时，检查飞贼。
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
                col=col,
                kind="bungee",
                zombie=BUNGEE_ZOMBIE,
                count=1,
                cost=BUNGEE_COST,
                damage=None,
                hp=None,
                clears_magnet=True,
                is_prep=False,
                target_plant="magnetshroom",
                target_as_empty=False,
                external_threepeaters=external_threepeaters,
                note=(
                    f"R{display_row}C{display_col}: 单路障/单撑杆不能直接吃磁力菇；"
                    f"{bungee_reason}，使用飞贼抓掉磁力菇"
                ),
            )
        )

    # -------------------------------------------------------------
    # 3. 不能飞时进入第 4 点：
    #    - 有土豆雷 / 窝瓜 / 大嘴花阻挡：先垫掉阻挡点；
    #    - 无阻挡点：双/三路障或双/三撑杆强吃磁力菇。
    # -------------------------------------------------------------
    if not single_ok and not bungee_safe:
        if blocking_instant is not None:
            blocker_col, blocker_plant = blocking_instant
            prep_candidates, prep_attempts = build_stage4_prep_candidates(
                lane,
                row=row,
                blocker_col=blocker_col,
                blocker_plant=blocker_plant,
                external_threepeaters=external_threepeaters,
            )

            for attempt in prep_attempts:
                attempt["stage"] = "stage4_prep_blocker"
                attempt["magnet_col"] = col
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
    context: BreakContext,
    board: List[List[str]],
    magnets: List[Tuple[int, int]],
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    all_candidates: List[Dict[str, Any]] = []
    all_attempts: List[Dict[str, Any]] = []

    for row, col in magnets:
        candidates, attempts = build_magnet_candidates_for_one(
            context,
            board,
            row,
            col,
        )
        all_candidates.extend(candidates)
        all_attempts.extend(attempts)

    if not all_candidates:
        return None, all_candidates, all_attempts

    # 优先真正清磁力菇；如果都因为灰烬/大嘴花卡住且不能飞，再输出垫掉阻挡点。
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

    # 当路障和撑杆都安全、同阳光、同阶段时，优先路障。
    zombie_priority_when_safe = {
        CONE_ZOMBIE: 0,
        POLE_ZOMBIE: 1,
        BUNGEE_ZOMBIE: 2,
    }

    def sort_key(candidate: Dict[str, Any]) -> Tuple[int, int, int, int, int, int, int]:
        kind = str(candidate["kind"])
        damage = candidate.get("damage")
        hp = candidate.get("hp")

        if isinstance(damage, int) and isinstance(hp, int):
            margin = hp - damage
            damage_sort = damage
        else:
            margin = -999999
            damage_sort = 999999

        safe = bool(candidate.get("safe"))

        # safe 候选：路障优先；
        # 非 safe 候选：先看余量，避免盲目因为路障优先而选更贴边的方案。
        if safe:
            zombie_sort = zombie_priority_when_safe.get(str(candidate.get("zombie")), 9)
            margin_sort = -margin
        else:
            zombie_sort = 0
            margin_sort = -margin

        return (
            int(candidate["cost"]),
            stage_priority.get(kind, 99),
            0 if safe else 1,
            zombie_sort,
            margin_sort,
            damage_sort,
            int(candidate["row"]) * 10 + int(candidate["col"]),
        )

    candidate_pool.sort(key=sort_key)
    return candidate_pool[0], all_candidates, all_attempts


# ---------------------------------------------------------------------------
# Main solve
# ---------------------------------------------------------------------------

def solve(context: BreakContext) -> BreakPlan:
    board = get_board_5x5(context)
    magnets = find_magnets(board)

    # 没有磁力菇：后续综合阵破阵策略暂未实现。
    if not magnets:
        return BreakPlan(
            theme=THEME_NAME,
            actions=[],
            confidence=0.35,
            reason=(
                "综合阵未检测到磁力菇；第一阶段磁力菇处理已结束，"
                "后续三线 / 杨桃 / 常规单破策略待补充。"
            ),
            debug={
                "strategy": "hybrid",
                "stage": "after_magnet",
                "magnets": [],
                "todo": "综合阵后续策略待补充",
            },
        )

    best, all_candidates, all_attempts = choose_best_magnet_plan(
        context,
        board,
        magnets,
    )

    if best is None:
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
            },
        )

    actions = candidate_to_actions(best)
    display_row = int(best["row"]) + 1
    display_col = int(best["col"]) + 1

    if best.get("clears_magnet"):
        reason_tail = "该方案目标是清除磁力菇；磁力菇清除后，后续综合阵策略暂待补充。"
    else:
        reason_tail = (
            f"该方案只是先换掉 {best.get('target_plant')}；"
            "等待识别稳定后重新执行磁力菇处理判断。"
        )

    safe_text = (
        "满足 HP-3 安全阈值"
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
            "算血参考 control.py 的完整行段计算，保留本路后排植物和相邻路三线伤害；"
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
        },
    )
