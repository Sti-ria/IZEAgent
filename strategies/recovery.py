# -*- coding: utf-8 -*-
"""
回复阵破阵策略。

主题特征：
    回复阵主要是胆小菇 / 小喷菇相关阵型。

当前策略目标：
    1. 只考虑单路破阵，不考虑其他路僵尸导致胆小菇缩头；
    2. 每一行独立调用单路算血器 calculate_lane()；
    3. 如果某一路没有任何小喷菇和胆小菇，直接放小鬼；
    4. 小鬼特殊判定：
        使用扶梯模式的算血结果 ladder = a+b；
        取 a，也就是梯子承受伤害；
        如果 a < 3，则认为小鬼可单破；
    5. 撑杆和路障阳光相同，优先判断：
        pole <= 15：撑杆可过；
        slow <= 25：路障可过；
        如果二者都可过，选择安全余量更大的那个；
    6. 否则根据 slow 算血值选择：
        slow <= 65：铁桶
        slow > 65：铁桶 + 路障补刀兜底
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from core.breaker_types import BreakAction, BreakContext, BreakPlan
from core.ize_blood_calculator import IZEBloodCalculator


THEME_NAME = "回复"

# 小鬼判定：ladder = a+b 中的 a，也就是梯子承受伤害。
# 如果 a < 3，则下小鬼。
IMP_LADDER_DAMAGE_THRESHOLD = 3

# 便宜单破判定。
# 撑杆真实血量约 17，这里 <=15 判定能过。
# 路障真实血量约 27，这里 <=25 判定能过。
POLE_SAFE_VALUE = 15
CONE_SAFE_VALUE = 25

# 兜底血量判定。
CONE_HP = 27
BUCKET_HP = 65

EMPTY_LABELS = {
    "",
    "empty",
    "unknown",
    "none",
    "null",
    "blank",
    "grass",
}

PUFF_AND_SCAREDY_LABELS = {
    "puffshroom",
    "scaredyshroom",
}


def normalize_plant(label: Any) -> str:
    """
    清洗植物标签，兼容 puff_shroom / puff-shroom / puffshroom 等写法。
    """
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


def get_row_plants(context: BreakContext, row: int) -> List[str]:
    """
    获取某一行前 5 列植物，并统一清洗标签。
    """
    plants: List[str] = []

    for col in range(5):
        try:
            plant = context.board_5x5[row][col]
        except (IndexError, TypeError):
            plant = ""

        plants.append(normalize_plant(plant))

    return plants


def has_real_plant(plants: List[str]) -> bool:
    """
    判断这一行是否有真实植物。
    """
    return any(plant not in EMPTY_LABELS for plant in plants)


def has_puff_or_scaredy(plants: List[str]) -> bool:
    """
    判断这一行是否有小喷菇或胆小菇。

    规则：
        如果某一路没有任何小喷菇和胆小菇，直接放小鬼。
    """
    return any(plant in PUFF_AND_SCAREDY_LABELS for plant in plants)


def parse_numeric_value(value: Any) -> Optional[int]:
    """
    将算血器输出转为整数。

    兼容：
        12
        "12"
        "*12*"
        "(12)"
        "12.0"
    """
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


def parse_ladder_damage_value(value: Any) -> Optional[int]:
    """
    解析梯子算血结果。

    梯子算血一般是：
        "a+b"

    其中：
        a = 梯子承受伤害
        b = 僵尸本体承受伤害

    当前小鬼判定使用 a，也就是梯子承受伤害。
    如果不是 a+b 格式，则退化为普通数字解析。
    """
    if value is None:
        return None

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

    if "+" in text:
        parts = text.split("+")
        if len(parts) >= 1:
            ladder_damage = parse_numeric_value(parts[0])
            if ladder_damage is None:
                return None
            return ladder_damage

    return parse_numeric_value(text)


def calculate_single_lane_result(context: BreakContext, row: int) -> Dict[str, Any]:
    """
    回复阵只考虑单路，所以这里直接调用 calculate_lane()。

    不使用 calculate_board()，也不传 adjacent_lanes，
    避免引入其他路影响。
    """
    calc = IZEBloodCalculator()
    lane = context.lane(row)
    return calc.calculate_lane(lane)


def get_mode_value(result: Dict[str, Any], mode: str) -> Any:
    return result.get("values", {}).get(mode)


def can_imp_by_ladder_damage(result: Dict[str, Any]) -> Tuple[bool, Optional[int], Any]:
    """
    小鬼判定：

    使用扶梯模式 ladder 的“梯子承受伤害”。
    如果梯子承受伤害 < 3，则下小鬼。
    """
    ladder_raw = get_mode_value(result, "ladder")
    ladder_damage = parse_ladder_damage_value(ladder_raw)

    if ladder_damage is None:
        return False, None, ladder_raw

    # 避免 -1+-1 这种无效梯子值触发小鬼。
    if ladder_damage < 0:
        return False, ladder_damage, ladder_raw

    return ladder_damage < IMP_LADDER_DAMAGE_THRESHOLD, ladder_damage, ladder_raw


def choose_pole_or_cone(
    row: int,
    pole_value: Optional[int],
    slow_value: Optional[int],
) -> Optional[Tuple[List[BreakAction], int, str]]:
    """
    判断撑杆 / 路障是否能过。

    规则：
        pole <= 15：撑杆可过
        slow <= 25：路障可过

    撑杆和路障阳光相同，二者都能过时选择安全余量更大的。
    """
    display_row = row + 1

    candidates: List[Dict[str, Any]] = []

    if pole_value is not None and pole_value <= POLE_SAFE_VALUE:
        candidates.append(
            {
                "zombie": "pole",
                "cost": 75,
                "value": pole_value,
                "threshold": POLE_SAFE_VALUE,
                "margin": POLE_SAFE_VALUE - pole_value,
                "note": (
                    f"R{display_row}: 回复阵单路 pole={pole_value} "
                    f"<= 撑杆判定值{POLE_SAFE_VALUE}，撑杆可单破"
                ),
                "reason": f"R{display_row}: pole={pole_value}，撑杆单破",
            }
        )

    if slow_value is not None and slow_value <= CONE_SAFE_VALUE:
        candidates.append(
            {
                "zombie": "cone",
                "cost": 75,
                "value": slow_value,
                "threshold": CONE_SAFE_VALUE,
                "margin": CONE_SAFE_VALUE - slow_value,
                "note": (
                    f"R{display_row}: 回复阵单路 slow={slow_value} "
                    f"<= 路障判定值{CONE_SAFE_VALUE}，路障可单破"
                ),
                "reason": f"R{display_row}: slow={slow_value}，路障单破",
            }
        )

    if not candidates:
        return None

    # 同阳光时，选择安全余量更大的。
    # 如果余量相同，优先撑杆；通常撑杆能减少部分啃咬阶段，实战更干净。
    candidates.sort(
        key=lambda item: (
            int(item["margin"]),
            1 if item["zombie"] == "pole" else 0,
        ),
        reverse=True,
    )

    best = candidates[0]

    action = BreakAction(
        zombie=str(best["zombie"]),
        row=row,
        count=1,
        note=str(best["note"]),
    )

    return [action], int(best["cost"]), str(best["reason"])


def build_bucket_plus_cones(row: int, slow_value: int) -> Tuple[List[BreakAction], int, str]:
    """
    slow > 65 时的兜底方案。

    正常回复阵一般铁桶能单破；这个分支主要是防止异常算血或极端识别。
    """
    display_row = row + 1
    remaining = max(0, slow_value - BUCKET_HP)
    cone_count = int(math.ceil(remaining / CONE_HP))

    actions: List[BreakAction] = [
        BreakAction(
            zombie="bucket",
            row=row,
            count=1,
            note=(
                f"R{display_row}: 回复阵单路 slow={slow_value} > 铁桶血量{BUCKET_HP}，"
                "先下铁桶兜底"
            ),
        )
    ]

    for idx in range(cone_count):
        actions.append(
            BreakAction(
                zombie="cone",
                row=row,
                count=1,
                note=(
                    f"R{display_row}: 【确认上一只死亡后】补第 {idx + 1} 只路障"
                ),
            )
        )

    cost = 125 + cone_count * 75
    reason = f"R{display_row}: slow={slow_value}，铁桶后补 {cone_count} 路障"

    return actions, cost, reason


def choose_single_break_for_row(
    context: BreakContext,
    row: int,
) -> Tuple[List[BreakAction], int, str, Dict[str, Any]]:
    """
    给单行生成破阵动作。

    返回：
        actions
        estimated_cost
        reason
        single_lane_blood_result
    """
    display_row = row + 1
    plants = get_row_plants(context, row)
    result = calculate_single_lane_result(context, row)

    values = result.get("values", {})
    pole_value = parse_numeric_value(values.get("pole"))
    slow_value = parse_numeric_value(values.get("slow"))

    # -------------------------------------------------------------
    # 规则 1：没有小喷菇和胆小菇，直接小鬼
    # -------------------------------------------------------------
    if not has_puff_or_scaredy(plants):
        return (
            [
                BreakAction(
                    zombie="imp",
                    row=row,
                    count=1,
                    note=(
                        f"R{display_row}: 本路没有小喷菇和胆小菇，"
                        "直接小鬼收路"
                    ),
                )
            ],
            50,
            f"R{display_row}: 无小喷/胆小，直接小鬼",
            result,
        )

    # -------------------------------------------------------------
    # 规则 2：小鬼按扶梯逻辑判断，但取 ladder 前半段“梯子承伤”
    # -------------------------------------------------------------
    can_imp, ladder_damage, ladder_raw = can_imp_by_ladder_damage(result)
    if can_imp:
        return (
            [
                BreakAction(
                    zombie="imp",
                    row=row,
                    count=1,
                    note=(
                        f"R{display_row}: 回复阵单路算血，ladder={ladder_raw}，"
                        f"梯子承伤={ladder_damage} < {IMP_LADDER_DAMAGE_THRESHOLD}，"
                        "小鬼可单破"
                    ),
                )
            ],
            50,
            f"R{display_row}: ladder={ladder_raw}，梯子承伤={ladder_damage}<3，下小鬼",
            result,
        )

    # -------------------------------------------------------------
    # 规则 3：撑杆 / 路障同阳光，优先判断便宜单破
    # -------------------------------------------------------------
    cheap_result = choose_pole_or_cone(
        row=row,
        pole_value=pole_value,
        slow_value=slow_value,
    )
    if cheap_result is not None:
        actions, cost, reason = cheap_result
        return actions, cost, reason, result

    # -------------------------------------------------------------
    # 规则 4：撑杆 / 路障都不能过，再判断铁桶
    # -------------------------------------------------------------
    if slow_value is not None:
        if slow_value <= BUCKET_HP:
            return (
                [
                    BreakAction(
                        zombie="bucket",
                        row=row,
                        count=1,
                        note=(
                            f"R{display_row}: 回复阵单路 slow={slow_value} "
                            f"<= 铁桶血量{BUCKET_HP}，铁桶单破"
                        ),
                    )
                ],
                125,
                f"R{display_row}: slow={slow_value}，铁桶单破",
                result,
            )

        actions, cost, reason = build_bucket_plus_cones(row, slow_value)
        return actions, cost, reason, result

    # -------------------------------------------------------------
    # 规则 5：拿不到 slow 时的兜底
    # -------------------------------------------------------------
    return (
        [
            BreakAction(
                zombie="bucket",
                row=row,
                count=1,
                note=(
                    f"R{display_row}: 回复阵未拿到 slow 算血值，"
                    "按最差情况使用铁桶兜底"
                ),
            )
        ],
        125,
        f"R{display_row}: 缺少 slow，铁桶兜底",
        result,
    )


def solve(context: BreakContext) -> BreakPlan:
    """
    回复阵主策略入口。

    每一行独立输出单破动作。
    """
    all_actions: List[BreakAction] = []
    reasons: List[str] = []
    debug_rows: List[Dict[str, Any]] = []
    total_cost = 0

    for row in range(5):
        actions, cost, reason, result = choose_single_break_for_row(context, row)

        all_actions.extend(actions)
        reasons.append(reason)
        total_cost += cost

        plants = get_row_plants(context, row)
        values = result.get("values", {})
        ladder_raw = values.get("ladder")
        ladder_damage = parse_ladder_damage_value(ladder_raw)

        debug_rows.append(
            {
                "row": row,
                "plants": plants,
                "has_real_plant": has_real_plant(plants),
                "has_puff_or_scaredy": has_puff_or_scaredy(plants),
                "values": values,
                "status": result.get("status", {}),
                "pole": parse_numeric_value(values.get("pole")),
                "slow": parse_numeric_value(values.get("slow")),
                "ladder_raw": ladder_raw,
                "ladder_damage": ladder_damage,
                "actions": [
                    {
                        "zombie": action.zombie,
                        "row": action.row,
                        "count": action.count,
                        "note": action.note,
                    }
                    for action in actions
                ],
                "cost": cost,
                "reason": reason,
            }
        )

    return BreakPlan(
        theme=THEME_NAME,
        actions=all_actions,
        confidence=0.96,
        reason=(
            "回复阵单路破阵策略：每行独立调用 calculate_lane()；"
            "无小喷/胆小则小鬼；"
            "ladder 梯子承伤 < 3 时小鬼；"
            "否则 pole<=15 用撑杆，slow<=25 用路障，二者都能过时选安全余量更大的；"
            "再按 slow<=65 铁桶进行单破。"
            " | "
            + " | ".join(reasons)
        ),
        debug={
            "strategy": "recovery",
            "imp_ladder_damage_threshold": IMP_LADDER_DAMAGE_THRESHOLD,
            "pole_safe_value": POLE_SAFE_VALUE,
            "cone_safe_value": CONE_SAFE_VALUE,
            "cone_hp": CONE_HP,
            "bucket_hp": BUCKET_HP,
            "total_estimated_cost": total_cost,
            "rows": debug_rows,
        },
    )
