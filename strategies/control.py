# -*- coding: utf-8 -*-
"""
控制阵破阵策略。

阶段 1：优先处理磁力菇
    1. 只要场上存在磁力菇，就优先处理磁力菇；
    2. 先判断单路障 / 单撑杆能否吃掉磁力菇；
    3. 如果不能吃掉，检查磁力菇 3x3 范围内是否有叶子保护伞：
        - 没有保护伞：飞贼抓磁力菇；
        - 有保护伞：尝试双路障 / 双撑杆 / 三路障 / 三撑杆强吃；
    4. 磁力菇未清除前，不考虑后续破阵。

阶段 2：磁力菇清除后，进入单破逻辑
    1. 如果还有三线射手，优先单破三线所在路；
    2. 如果没有三线射手，所有路优先级相同；
    3. 单破候选：
        - 单撑杆
        - 单路障
        - 单铁桶
        - 单扶梯
        - 矿工 + 小鬼
        - 矿工 + 路障
        - 单橄榄
        - 扶梯 + 撑杆
    4. 暂不考虑舞王。
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
    IZEBloodCalculator,
)


THEME_NAME = "控制"

# 如果你的自动下僵尸模块里名称不同，只改这些常量即可。
BUNGEE_ZOMBIE = "bungee"
MINER_ZOMBIE = "miner"
IMP_ZOMBIE = "imp"
CONE_ZOMBIE = "cone"
BUCKET_ZOMBIE = "bucket"
POLE_ZOMBIE = "pole"
LADDER_ZOMBIE = "ladder"
FOOTBALL_ZOMBIE = "football"

# 阳光估算
IMP_COST = 50
CONE_COST = 75
POLE_COST = 75
BUCKET_COST = 125
MINER_COST = 125
BUNGEE_COST = 125
LADDER_COST = 150
FOOTBALL_COST = 175
POLE_LADDER_COST = 225

# 血量判定
IMP_HP = 10
POLE_HP = 17
CONE_HP = 27
BUCKET_HP = 65
LADDER_BODY_HP = 17
FOOTBALL_HP = 90

EMPTY_LABELS = {
    "",
    "empty",
    "unknown",
    "none",
    "null",
    "blank",
    "grass",
}

MAGNET_LABELS = {
    "magnetshroom",
}

UMBRELLA_LABELS = {
    "umbrellaleaf",
}

THREEPEATER_LABELS = {
    "threepeater",
}

SPLIT_PEA_LABELS = {
    "splitpea",
}

SPIKEWEED_LABELS = {
    "spikeweed",
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


def is_empty_like(plant: str) -> bool:
    return plant in EMPTY_LABELS


def has_real_plant(plants: Sequence[str]) -> bool:
    return any(not is_empty_like(plant) for plant in plants)


def find_magnets(board: List[List[str]]) -> List[Tuple[int, int]]:
    magnets: List[Tuple[int, int]] = []

    for row in range(5):
        for col in range(5):
            if board[row][col] in MAGNET_LABELS:
                magnets.append((row, col))

    return magnets


def find_threepeater_rows(board: List[List[str]]) -> List[int]:
    rows: List[int] = []

    for row in range(5):
        if any(plant in THREEPEATER_LABELS for plant in board[row]):
            rows.append(row)

    return rows

def get_adjacent_threepeater_cols(board: List[List[str]], row: int) -> List[int]:
    """
    获取目标行上下相邻路中的三线射手列号。

    返回 0-based col：
        0 = 第 1 列
        4 = 第 5 列

    只算相邻路三线：
        row - 1
        row + 1

    本路三线本来就在 lane 里，会被正常算血器处理，不需要放进 external_threepeaters。
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


def parse_numeric_value(value: Any) -> Optional[int]:
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return int(math.ceil(float(value)))

    text = str(value).strip()
    if text == "" or text == "-":
        return None

    text = (
        text.replace("*", "")
        .replace("(", "")
        .replace(")", "")
        .replace(" ", "")
    )

    if text == "":
        return None

    try:
        return int(math.ceil(float(text)))
    except ValueError:
        return None


def parse_pair_value(value: Any) -> Tuple[Optional[int], Optional[int]]:
    """
    解析类似 '20+7' 的算血器输出。

    返回：
        first, second

    对 ladder / pole_ladder：
        first  一般表示梯子承伤；
        second 一般表示本体承伤。
    """
    if value is None:
        return None, None

    text = str(value).strip()
    if text == "" or text == "-":
        return None, None

    text = (
        text.replace("*", "")
        .replace("(", "")
        .replace(")", "")
        .replace(" ", "")
    )

    if "+" not in text:
        num = parse_numeric_value(text)
        return num, None

    parts = text.split("+")
    if len(parts) < 2:
        return None, None

    first = parse_numeric_value(parts[0])
    second = parse_numeric_value(parts[1])

    return first, second


# ---------------------------------------------------------------------------
# Stage 1: Magnet handling
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
    计算某种模式下，僵尸从右侧进入，到吃掉 target_col 植物为止的受伤。

    target_col 是 0-based：
        0 = 第 1 列
        4 = 第 5 列
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

        # 撑杆第一跳目标是磁力菇或在磁力菇左侧，都不能视为“吃掉磁力菇”。
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

    for i in range(max(0, bite_start), min(5, bite_end) + 1):
        total += calc_bite_damage(row_obj, i, hbfix, torchwood)

    for i in range(max(0, walk_start), min(5, walk_end) + 1):
        total += row_obj.calc_walk_segment_damage(i, hbfix)

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
) -> Optional[int]:

    """
    支持多只路障 / 多只撑杆强吃磁力菇时的地刺伤害放大。
    """
    row_ids = normalize_lane(lane)

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


def make_magnet_candidate(
    *,
    row: int,
    col: int,
    kind: str,
    zombie: str,
    count: int,
    cost: int,
    damage: Optional[int],
    hp: Optional[int],
    note: str,
) -> Dict[str, Any]:
    return {
        "row": row,
        "col": col,
        "kind": kind,
        "zombie": zombie,
        "count": count,
        "cost": cost,
        "damage": damage,
        "hp": hp,
        "note": note,
    }


def magnet_candidate_to_actions(candidate: Dict[str, Any]) -> List[BreakAction]:
    row = int(candidate["row"])
    col = int(candidate["col"])
    zombie = str(candidate["zombie"])
    count = int(candidate["count"])
    note = str(candidate["note"])

    if zombie == BUNGEE_ZOMBIE:
        return [
            BreakAction(
                zombie=zombie,
                row=row,
                col=col,
                count=1,
                note=note,
            )
        ]

    return [
        BreakAction(
            zombie=zombie,
            row=row,
            count=count,
            note=note,
        )
    ]


def build_magnet_candidates_for_one(
    context: BreakContext,
    board: List[List[str]],
    row: int,
    col: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    display_row = row + 1
    display_col = col + 1
    lane = get_raw_lane(context, row)

    candidates: List[Dict[str, Any]] = []
    attempts: List[Dict[str, Any]] = []

    has_umbrella = has_umbrella_in_3x3(board, row, col)
    external_threepeaters = get_adjacent_threepeater_cols(board, row)

    # 1. 单路障吃磁力菇
    cone_damage = calculate_damage_until_col(
        lane,
        MODE_SLOW,
        col,
        spike_multiplier=1,
        external_threepeaters=external_threepeaters,
    )
    attempts.append(
        {
            "kind": "single_cone",
            "damage": cone_damage,
            "hp": CONE_HP,
            "ok": cone_damage is not None and cone_damage <= CONE_HP,
        }
    )

    if cone_damage is not None and cone_damage <= CONE_HP:
        candidates.append(
            make_magnet_candidate(
                row=row,
                col=col,
                kind="single_cone",
                zombie=CONE_ZOMBIE,
                count=1,
                cost=CONE_COST,
                damage=cone_damage,
                hp=CONE_HP,
                note=(
                    f"R{display_row}C{display_col}: 控制阵优先处理磁力菇；"
                    f"单路障吃磁力菇，受伤={cone_damage} <= 路障血量{CONE_HP}"
                ),
            )
        )

    # 2. 单撑杆吃磁力菇
    pole_damage = calculate_damage_until_col(
        lane,
        MODE_POLE,
        col,
        spike_multiplier=1,
        external_threepeaters=external_threepeaters
    )
    attempts.append(
        {
            "kind": "single_pole",
            "damage": pole_damage,
            "hp": POLE_HP,
            "ok": pole_damage is not None and pole_damage <= POLE_HP,
        }
    )

    if pole_damage is not None and pole_damage <= POLE_HP:
        candidates.append(
            make_magnet_candidate(
                row=row,
                col=col,
                kind="single_pole",
                zombie=POLE_ZOMBIE,
                count=1,
                cost=POLE_COST,
                damage=pole_damage,
                hp=POLE_HP,
                note=(
                    f"R{display_row}C{display_col}: 控制阵优先处理磁力菇；"
                    f"单撑杆吃磁力菇，受伤={pole_damage} <= 撑杆血量{POLE_HP}"
                ),
            )
        )

    single_ok = any(c["kind"] in {"single_cone", "single_pole"} for c in candidates)

    # 3. 单破不行且无保护伞：飞贼抓磁力菇
    if not single_ok and not has_umbrella:
        candidates.append(
            make_magnet_candidate(
                row=row,
                col=col,
                kind="bungee",
                zombie=BUNGEE_ZOMBIE,
                count=1,
                cost=BUNGEE_COST,
                damage=None,
                hp=None,
                note=(
                    f"R{display_row}C{display_col}: 磁力菇 3x3 内无叶子保护伞；"
                    "单路障/单撑杆不可吃，使用飞贼抓掉磁力菇"
                ),
            )
        )
        attempts.append(
            {
                "kind": "bungee",
                "has_umbrella_3x3": has_umbrella,
                "ok": True,
            }
        )

    # 4. 有保护伞：双/三路障、双/三撑杆强吃
    if not single_ok and has_umbrella:
        for count in (2, 3):
            hp = CONE_HP * count
            damage = calculate_damage_until_col(
                lane,
                MODE_SLOW,
                col,
                spike_multiplier=count,
                external_threepeaters=external_threepeaters
            )
            ok = damage is not None and damage <= hp

            attempts.append(
                {
                    "kind": f"{count}_cone",
                    "damage": damage,
                    "hp": hp,
                    "spike_multiplier": count,
                    "ok": ok,
                }
            )

            if ok:
                candidates.append(
                    make_magnet_candidate(
                        row=row,
                        col=col,
                        kind=f"{count}_cone",
                        zombie=CONE_ZOMBIE,
                        count=count,
                        cost=CONE_COST * count,
                        damage=damage,
                        hp=hp,
                        note=(
                            f"R{display_row}C{display_col}: 磁力菇 3x3 内有叶子保护伞；"
                            f"{count} 路障强吃磁力菇，受伤={damage} <= 总血量{hp}。"
                            "地刺伤害已按路障数量放大"
                        ),
                    )
                )

            hp = POLE_HP * count
            damage = calculate_damage_until_col(
                lane,
                MODE_POLE,
                col,
                spike_multiplier=count,
                external_threepeaters=external_threepeaters
            )
            ok = damage is not None and damage <= hp

            attempts.append(
                {
                    "kind": f"{count}_pole",
                    "damage": damage,
                    "hp": hp,
                    "spike_multiplier": count,
                    "ok": ok,
                }
            )

            if ok:
                candidates.append(
                    make_magnet_candidate(
                        row=row,
                        col=col,
                        kind=f"{count}_pole",
                        zombie=POLE_ZOMBIE,
                        count=count,
                        cost=POLE_COST * count,
                        damage=damage,
                        hp=hp,
                        note=(
                            f"R{display_row}C{display_col}: 磁力菇 3x3 内有叶子保护伞；"
                            f"{count} 撑杆强吃磁力菇，受伤={damage} <= 总血量{hp}。"
                            "地刺伤害已按撑杆数量放大"
                        ),
                    )
                )

    for attempt in attempts:
        attempt["row"] = row
        attempt["col"] = col
        attempt["has_umbrella_3x3"] = has_umbrella
        attempt["external_threepeaters"] = list(external_threepeaters)

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

    priority = {
        "single_cone": 0,
        "single_pole": 0,
        "bungee": 1,
    }

    def sort_key(candidate: Dict[str, Any]) -> Tuple[int, int, int, int]:
        kind = str(candidate["kind"])
        return (
            int(candidate["cost"]),
            priority.get(kind, 2),
            int(candidate["row"]),
            int(candidate["col"]),
        )

    all_candidates.sort(key=sort_key)
    return all_candidates[0], all_candidates, all_attempts


# ---------------------------------------------------------------------------
# Stage 2: Single-lane breaking after magnets are gone
# ---------------------------------------------------------------------------

def calculate_single_lane_result(context: BreakContext, row: int) -> Dict[str, Any]:
    """
    控制阵后续单破：不考虑旁路三线影响，所以只调用 calculate_lane()。
    """
    calc = IZEBloodCalculator()
    lane = get_raw_lane(context, row)
    return calc.calculate_lane(lane)


def make_action_spec(
    zombie: str,
    row: int,
    *,
    count: int = 1,
    note: str = "",
) -> Dict[str, Any]:
    return {
        "zombie": zombie,
        "row": row,
        "count": count,
        "note": note,
    }


def action_specs_to_actions(specs: Sequence[Dict[str, Any]]) -> List[BreakAction]:
    actions: List[BreakAction] = []

    for spec in specs:
        actions.append(
            BreakAction(
                zombie=str(spec["zombie"]),
                row=int(spec["row"]),
                count=int(spec.get("count", 1)),
                note=str(spec.get("note", "")),
            )
        )

    return actions


def make_single_candidate(
    *,
    row: int,
    kind: str,
    cost: int,
    actions: Sequence[Dict[str, Any]],
    reason: str,
    damage: Optional[Any] = None,
    hp: Optional[Any] = None,
    margin: Optional[int] = None,
    priority: int = 100,
) -> Dict[str, Any]:
    return {
        "row": row,
        "kind": kind,
        "cost": cost,
        "actions": list(actions),
        "reason": reason,
        "damage": damage,
        "hp": hp,
        "margin": margin,
        "priority": priority,
    }


def can_use_miner_combo(plants: Sequence[str]) -> Tuple[bool, str]:
    """
    矿工 + 小鬼 / 路障判定。

    你的规则：
        1. 如果 2,3,4,5 列有裂荚射手，ban 矿工；
        2. 如果有 3 个地刺：
            - 第 5 列是地刺，不 ban；
            - 第 5 列不是地刺，ban；
        3. 如果 1 列裂荚射手 + 2 个地刺，ban；
        4. 其他情况矿工可以单刷一路。
    """
    split_cols = [idx for idx, plant in enumerate(plants) if plant in SPLIT_PEA_LABELS]
    spike_cols = [idx for idx, plant in enumerate(plants) if plant in SPIKEWEED_LABELS]

    # 2,3,4,5 列有裂荚，ban。
    if any(col in {1, 2, 3, 4} for col in split_cols):
        return False, "第 2-5 列存在裂荚射手，矿工不能通过"

    # 3 个或更多地刺，且第 5 列不是地刺，ban。
    if len(spike_cols) >= 3 and 4 not in spike_cols:
        return False, "地刺数量 >= 3 且第 5 列不是地刺，ban 矿工"

    # 1 列裂荚 + 2 个或更多地刺，ban。
    if 0 in split_cols and len(spike_cols) >= 2:
        return False, "第 1 列裂荚射手 + 至少 2 个地刺，ban 矿工"

    return True, "矿工规则允许"


def build_miner_candidate(row: int, plants: Sequence[str]) -> Optional[Dict[str, Any]]:
    display_row = row + 1
    can_miner, reason = can_use_miner_combo(plants)

    if not can_miner:
        return None

    spike_count = sum(1 for plant in plants if plant in SPIKEWEED_LABELS)

    if spike_count <= 1:
        actions = [
            make_action_spec(
                MINER_ZOMBIE,
                row,
                note=f"R{display_row}: 控制阵单破，矿工规则允许；先下矿工吃空本路",
            ),
            make_action_spec(
                IMP_ZOMBIE,
                row,
                note=f"R{display_row}: 地刺数量={spike_count} <= 1，矿工后补小鬼收尾",
            ),
        ]
        return make_single_candidate(
            row=row,
            kind="miner_imp",
            cost=MINER_COST + IMP_COST,
            actions=actions,
            reason=f"R{display_row}: 矿工+小鬼，{reason}，地刺数量={spike_count}",
            damage=None,
            hp=None,
            margin=None,
            priority=4,
        )

    actions = [
        make_action_spec(
            MINER_ZOMBIE,
            row,
            note=f"R{display_row}: 控制阵单破，矿工规则允许；先下矿工吃空本路",
        ),
        make_action_spec(
            CONE_ZOMBIE,
            row,
            note=f"R{display_row}: 地刺数量={spike_count} >= 2，矿工后补路障收尾",
        ),
    ]
    return make_single_candidate(
        row=row,
        kind="miner_cone",
        cost=MINER_COST + CONE_COST,
        actions=actions,
        reason=f"R{display_row}: 矿工+路障，{reason}，地刺数量={spike_count}",
        damage=None,
        hp=None,
        margin=None,
        priority=5,
    )


def build_single_lane_candidates(
    context: BreakContext,
    board: List[List[str]],
    row: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    display_row = row + 1
    plants = board[row]
    result = calculate_single_lane_result(context, row)
    values = result.get("values", {})

    pole_value = parse_numeric_value(values.get("pole"))
    slow_value = parse_numeric_value(values.get("slow"))
    football_value = parse_numeric_value(values.get("football"))

    ladder_raw = values.get("ladder")
    ladder_damage, ladder_body = parse_pair_value(ladder_raw)

    pole_ladder_raw = values.get("pole_ladder")
    pole_ladder_damage, pole_ladder_body = parse_pair_value(pole_ladder_raw)

    candidates: List[Dict[str, Any]] = []

    # 空路：小鬼。
    if not has_real_plant(plants):
        candidates.append(
            make_single_candidate(
                row=row,
                kind="empty_imp",
                cost=IMP_COST,
                actions=[
                    make_action_spec(
                        IMP_ZOMBIE,
                        row,
                        note=f"R{display_row}: 本路无植物，小鬼收路",
                    )
                ],
                reason=f"R{display_row}: 空路，小鬼",
                damage=0,
                hp=IMP_HP,
                margin=IMP_HP,
                priority=0,
            )
        )

    # 单撑杆
    if pole_value is not None and pole_value >= 0 and pole_value <= POLE_HP:
        candidates.append(
            make_single_candidate(
                row=row,
                kind="single_pole",
                cost=POLE_COST,
                actions=[
                    make_action_spec(
                        POLE_ZOMBIE,
                        row,
                        note=(
                            f"R{display_row}: 控制阵单破，pole={pole_value} "
                            f"<= 撑杆血量{POLE_HP}，单撑杆"
                        ),
                    )
                ],
                reason=f"R{display_row}: 单撑杆 pole={pole_value}",
                damage=pole_value,
                hp=POLE_HP,
                margin=POLE_HP - pole_value,
                priority=1,
            )
        )

    # 单路障
    if slow_value is not None and slow_value >= 0 and slow_value <= CONE_HP:
        candidates.append(
            make_single_candidate(
                row=row,
                kind="single_cone",
                cost=CONE_COST,
                actions=[
                    make_action_spec(
                        CONE_ZOMBIE,
                        row,
                        note=(
                            f"R{display_row}: 控制阵单破，slow={slow_value} "
                            f"<= 路障血量{CONE_HP}，单路障"
                        ),
                    )
                ],
                reason=f"R{display_row}: 单路障 slow={slow_value}",
                damage=slow_value,
                hp=CONE_HP,
                margin=CONE_HP - slow_value,
                priority=1,
            )
        )

    # 单铁桶
    if slow_value is not None and slow_value >= 0 and slow_value <= BUCKET_HP:
        candidates.append(
            make_single_candidate(
                row=row,
                kind="single_bucket",
                cost=BUCKET_COST,
                actions=[
                    make_action_spec(
                        BUCKET_ZOMBIE,
                        row,
                        note=(
                            f"R{display_row}: 控制阵单破，slow={slow_value} "
                            f"<= 铁桶血量{BUCKET_HP}，单铁桶"
                        ),
                    )
                ],
                reason=f"R{display_row}: 单铁桶 slow={slow_value}",
                damage=slow_value,
                hp=BUCKET_HP,
                margin=BUCKET_HP - slow_value,
                priority=2,
            )
        )

    # 单扶梯
    if (
        ladder_body is not None
        and ladder_body >= 0
        and ladder_body <= LADDER_BODY_HP
    ):
        candidates.append(
            make_single_candidate(
                row=row,
                kind="single_ladder",
                cost=LADDER_COST,
                actions=[
                    make_action_spec(
                        LADDER_ZOMBIE,
                        row,
                        note=(
                            f"R{display_row}: 控制阵单破，ladder={ladder_raw}，"
                            f"本体承伤={ladder_body} <= {LADDER_BODY_HP}，单扶梯"
                        ),
                    )
                ],
                reason=f"R{display_row}: 单扶梯 ladder={ladder_raw}",
                damage=ladder_raw,
                hp=f"梯子+本体，本体HP={LADDER_BODY_HP}",
                margin=LADDER_BODY_HP - ladder_body,
                priority=3,
            )
        )

    # 矿工 + 小鬼 / 路障
    miner_candidate = build_miner_candidate(row, plants)
    if miner_candidate is not None:
        candidates.append(miner_candidate)

    # 单橄榄
    if football_value is not None and football_value >= 0 and football_value <= FOOTBALL_HP:
        candidates.append(
            make_single_candidate(
                row=row,
                kind="single_football",
                cost=FOOTBALL_COST,
                actions=[
                    make_action_spec(
                        FOOTBALL_ZOMBIE,
                        row,
                        note=(
                            f"R{display_row}: 控制阵单破，football={football_value} "
                            f"<= 橄榄血量{FOOTBALL_HP}，单橄榄"
                        ),
                    )
                ],
                reason=f"R{display_row}: 单橄榄 football={football_value}",
                damage=football_value,
                hp=FOOTBALL_HP,
                margin=FOOTBALL_HP - football_value,
                priority=6,
            )
        )

    # 扶梯 + 撑杆
    if (
        pole_ladder_body is not None
        and pole_ladder_body >= 0
        and pole_ladder_body <= LADDER_BODY_HP
    ):
        candidates.append(
            make_single_candidate(
                row=row,
                kind="pole_ladder",
                cost=POLE_LADDER_COST,
                actions=[
                    make_action_spec(
                        LADDER_ZOMBIE,
                        row,
                        note=(
                            f"R{display_row}: 控制阵单破组合，pole_ladder={pole_ladder_raw}，"
                            "先下扶梯"
                        ),
                    ),
                    make_action_spec(
                        POLE_ZOMBIE,
                        row,
                        note=f"R{display_row}: 控制阵单破组合，扶梯后接撑杆",
                    ),
                ],
                reason=f"R{display_row}: 扶梯+撑杆 pole_ladder={pole_ladder_raw}",
                damage=pole_ladder_raw,
                hp=f"梯子+本体，本体HP={LADDER_BODY_HP}",
                margin=LADDER_BODY_HP - pole_ladder_body,
                priority=7,
            )
        )

    debug = {
        "row": row,
        "plants": list(plants),
        "has_threepeater": any(plant in THREEPEATER_LABELS for plant in plants),
        "values": values,
        "status": result.get("status", {}),
        "pole": pole_value,
        "slow": slow_value,
        "ladder_raw": ladder_raw,
        "ladder_damage": ladder_damage,
        "ladder_body": ladder_body,
        "football": football_value,
        "pole_ladder_raw": pole_ladder_raw,
        "pole_ladder_damage": pole_ladder_damage,
        "pole_ladder_body": pole_ladder_body,
        "miner": {
            "can_use": build_miner_candidate(row, plants) is not None,
            "rule": can_use_miner_combo(plants)[1],
        },
        "candidate_kinds": [candidate["kind"] for candidate in candidates],
    }

    return candidates, debug


def choose_best_single_candidate(candidates: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None

    def sort_key(candidate: Dict[str, Any]) -> Tuple[int, int, int]:
        margin = candidate.get("margin")
        if margin is None:
            margin_value = -999
        else:
            margin_value = int(margin)

        return (
            int(candidate["cost"]),
            int(candidate["priority"]),
            -margin_value,
        )

    ordered = sorted(candidates, key=sort_key)
    return ordered[0]


def build_after_magnet_plan(context: BreakContext, board: List[List[str]]) -> BreakPlan:
    threepeater_rows = find_threepeater_rows(board)
    threepeater_set = set(threepeater_rows)

    row_records: List[Dict[str, Any]] = []
    debug_rows: List[Dict[str, Any]] = []

    for row in range(5):
        candidates, debug = build_single_lane_candidates(context, board, row)
        best = choose_best_single_candidate(candidates)

        record = {
            "row": row,
            "has_threepeater": row in threepeater_set,
            "best": best,
            "candidates": candidates,
        }
        row_records.append(record)

        debug["best"] = best
        debug["candidates"] = candidates
        debug_rows.append(debug)

    # 如果有三线，三线所在路优先；否则按行号输出。
    if threepeater_rows:
        row_records.sort(
            key=lambda item: (
                0 if item["has_threepeater"] else 1,
                int(item["row"]),
            )
        )
        priority_text = (
            "检测到三线射手，优先单破三线所在路："
            + ", ".join(f"R{row + 1}" for row in threepeater_rows)
        )
    else:
        row_records.sort(key=lambda item: int(item["row"]))
        priority_text = "未检测到三线射手，5 路无特殊优先级，按行号输出单破策略"

    actions: List[BreakAction] = []
    reasons: List[str] = []
    selected_rows: List[Dict[str, Any]] = []
    total_cost = 0

    for record in row_records:
        best = record["best"]
        row = int(record["row"])

        if best is None:
            reasons.append(f"R{row + 1}: 当前规则未找到可行单破方案")
            selected_rows.append(
                {
                    "row": row,
                    "has_threepeater": bool(record["has_threepeater"]),
                    "selected": None,
                }
            )
            continue

        actions.extend(action_specs_to_actions(best["actions"]))
        reasons.append(str(best["reason"]))
        total_cost += int(best["cost"])

        selected_rows.append(
            {
                "row": row,
                "has_threepeater": bool(record["has_threepeater"]),
                "selected": best,
            }
        )

    confidence = 0.86 if actions else 0.45

    return BreakPlan(
        theme=THEME_NAME,
        actions=actions,
        confidence=confidence,
        reason=(
            "控制阵第二阶段：磁力菇已清除，进入单破逻辑；"
            f"{priority_text}；"
            "暂不考虑舞王。"
            " | "
            + " | ".join(reasons)
        ),
        debug={
            "strategy": "control",
            "stage": "after_magnet_single_break",
            "threepeater_rows": threepeater_rows,
            "selected_rows": selected_rows,
            "rows": debug_rows,
            "total_estimated_cost": total_cost,
            "costs": {
                "imp": IMP_COST,
                "cone": CONE_COST,
                "pole": POLE_COST,
                "bucket": BUCKET_COST,
                "miner": MINER_COST,
                "ladder": LADDER_COST,
                "football": FOOTBALL_COST,
                "pole_ladder": POLE_LADDER_COST,
            },
            "hp": {
                "imp": IMP_HP,
                "pole": POLE_HP,
                "cone": CONE_HP,
                "bucket": BUCKET_HP,
                "ladder_body": LADDER_BODY_HP,
                "football": FOOTBALL_HP,
            },
        },
    )


# ---------------------------------------------------------------------------
# Main solve
# ---------------------------------------------------------------------------

def solve(context: BreakContext) -> BreakPlan:
    board = get_board_5x5(context)
    magnets = find_magnets(board)

    # 阶段 1：只要有磁力菇，永远优先处理磁力菇。
    if magnets:
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
                    "控制阵检测到磁力菇，但当前磁力菇处理规则下没有找到可行方案："
                    "单路障/单撑杆不可吃；若有保护伞，双/三路障或双/三撑杆也不可吃。"
                    "后续需要补充更强的处理方式。"
                ),
                debug={
                    "strategy": "control",
                    "stage": "magnet_first",
                    "magnets": [{"row": r, "col": c} for r, c in magnets],
                    "candidates": all_candidates,
                    "attempts": all_attempts,
                },
            )

        actions = magnet_candidate_to_actions(best)
        display_row = int(best["row"]) + 1
        display_col = int(best["col"]) + 1

        return BreakPlan(
            theme=THEME_NAME,
            actions=actions,
            confidence=0.9,
            reason=(
                "控制阵第一阶段：检测到磁力菇，优先处理磁力菇；"
                f"选择最少阳光方案处理 R{display_row}C{display_col} 磁力菇："
                f"{best['kind']}，预计阳光={best['cost']}。"
                "磁力菇清除后进入三线优先 / 单破逻辑。"
            ),
            debug={
                "strategy": "control",
                "stage": "magnet_first",
                "selected": best,
                "magnets": [{"row": r, "col": c} for r, c in magnets],
                "candidates": all_candidates,
                "attempts": all_attempts,
                "cone_hp": CONE_HP,
                "pole_hp": POLE_HP,
                "bungee_zombie_name": BUNGEE_ZOMBIE,
            },
        )

    # 阶段 2：磁力菇清除后，进入三线优先 / 单破逻辑。
    return build_after_magnet_plan(context, board)
