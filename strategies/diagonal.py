# -*- coding: utf-8 -*-
"""
倾斜阵破阵策略。

主题特征：
    9 地刺 + 8 杨桃

核心规则：
    1. 只使用算血器倾斜阵分支输出的 slow 值；
    2. 一开始输出当前策略；
    3. 之后只有当某一行“除地刺之外的所有植物”都变成 empty 后，才更新策略；
    4. 如果存在路障安全单破路，选择 slow 最大的路先破；
    5. 如果不存在路障安全单破路，则在铁桶安全单破路中选择 slow 最大的路先破；
    6. 当前策略排序：
        - 安全路从 slow 大到小；
        - 不安全路从 slow 小到大；
    7. 下僵尸必须一个接一个，确认上一只死亡后再放下一只。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from core.breaker_types import BreakAction, BreakContext, BreakPlan


THEME_NAME = "倾斜"

CONE_HP = 27
BUCKET_HP = 65

# 安全判定阈值
# slow <= CONE_SAFE_VALUE 才算路障安全单破
# slow <= BUCKET_SAFE_VALUE 才算铁桶安全单破
CONE_SAFE_VALUE = 23
BUCKET_SAFE_VALUE = 61

EMPTY_LABELS = {
    "",
    "empty",
    "unknown",
    "none",
    "null",
    "blank",
    "grass",
}

SPIKEWEED_LABELS = {
    "spikeweed",
}

# ---------------------------------------------------------------------------
# 模块级缓存：
# 用于实现“只在开局 / 某路非地刺植物清空后更新策略”
# ---------------------------------------------------------------------------

_LAST_CLEAR_MASK: Optional[Tuple[bool, bool, bool, bool, bool]] = None
_LAST_NON_SPIKE_COUNTS: Optional[Tuple[int, int, int, int, int]] = None
_LAST_PLAN: Optional[BreakPlan] = None


def normalize_plant(label: Any) -> str:
    """
    清洗植物标签，兼容 star_fruit / star-fruit / starfruit 等写法。
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
    获取某一行前 5 列植物。
    """
    plants: List[str] = []

    for col in range(5):
        try:
            plant = context.board_5x5[row][col]
        except (IndexError, TypeError):
            plant = ""

        plants.append(normalize_plant(plant))

    return plants


def is_empty_like(plant: str) -> bool:
    return plant in EMPTY_LABELS


def is_spikeweed(plant: str) -> bool:
    return plant in SPIKEWEED_LABELS


def count_non_spikeweed_plants(plants: List[str]) -> int:
    """
    统计一行里“除地刺之外”的真实植物数量。

    倾斜阵中地刺经常会残留，所以更新策略时不能要求整行完全 empty，
    而是要求非地刺植物全部清空。
    """
    count = 0

    for plant in plants:
        if is_empty_like(plant):
            continue
        if is_spikeweed(plant):
            continue
        count += 1

    return count


def is_non_spikeweed_cleared(plants: List[str]) -> bool:
    """
    判断某行是否已经清空所有非地刺植物。
    """
    return count_non_spikeweed_plants(plants) == 0


def parse_numeric_value(value: Any) -> Optional[int]:
    """
    将算血器输出转成 int。

    正常情况下 slow 是 int。
    这里额外兼容字符串、括号、星号，方便 mock / debug 数据不完全统一时仍能跑。
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

    # slow 正常不会是 a+b；这里只是兜底。
    if "+" in text:
        parts = [parse_numeric_value(part) for part in text.split("+")]
        if any(part is None for part in parts):
            return None
        return int(sum(part for part in parts if part is not None))

    try:
        return int(math.ceil(float(text)))
    except ValueError:
        return None


def get_slow_value(context: BreakContext, row: int) -> Optional[int]:
    """
    倾斜阵只看 slow 这一列。
    """
    return parse_numeric_value(context.mode_value(row, "slow"))


def get_independent_blood_value(context: BreakContext, row: int) -> Optional[int]:
    """
    独立算血只放进 debug，不参与当前策略排序。
    """
    return parse_numeric_value(context.mode_value(row, "independent_blood"))


def get_board_state(context: BreakContext) -> Tuple[
    Tuple[bool, bool, bool, bool, bool],
    Tuple[int, int, int, int, int],
]:
    """
    返回：
        clear_mask:
            每行是否已经清空所有非地刺植物。

        non_spike_counts:
            每行当前非地刺植物数量。
    """
    clear_values: List[bool] = []
    counts: List[int] = []

    for row in range(5):
        plants = get_row_plants(context, row)
        count = count_non_spikeweed_plants(plants)
        counts.append(count)
        clear_values.append(count == 0)

    return (
        tuple(clear_values),  # type: ignore[return-value]
        tuple(counts),        # type: ignore[return-value]
    )


def should_update_strategy(
    clear_mask: Tuple[bool, bool, bool, bool, bool],
    non_spike_counts: Tuple[int, int, int, int, int],
) -> Tuple[bool, str]:
    """
    判断是否应该重新计算策略。

    更新条件：
        1. 第一次运行；
        2. 有某行从“未清空”变成“已清空”；
        3. 有某行从“已清空”变回“未清空”，通常意味着新一关 / 识别重置；
        4. 非地刺植物数量整体增加，通常也意味着新一关 / 识别重置。
    """
    global _LAST_CLEAR_MASK
    global _LAST_NON_SPIKE_COUNTS
    global _LAST_PLAN

    if _LAST_PLAN is None or _LAST_CLEAR_MASK is None or _LAST_NON_SPIKE_COUNTS is None:
        return True, "init"

    newly_cleared_rows = [
        row
        for row in range(5)
        if clear_mask[row] and not _LAST_CLEAR_MASK[row]
    ]
    if newly_cleared_rows:
        rows_text = ",".join(f"R{row + 1}" for row in newly_cleared_rows)
        return True, f"non_spikeweed_cleared:{rows_text}"

    reopened_rows = [
        row
        for row in range(5)
        if not clear_mask[row] and _LAST_CLEAR_MASK[row]
    ]
    if reopened_rows:
        rows_text = ",".join(f"R{row + 1}" for row in reopened_rows)
        return True, f"new_round_or_memory_reset:{rows_text}"

    old_total = sum(_LAST_NON_SPIKE_COUNTS)
    new_total = sum(non_spike_counts)
    if new_total > old_total:
        return True, "plant_count_increased_reset"

    return False, "hold"


def build_lane_record(context: BreakContext, row: int) -> Dict[str, Any]:
    """
    构造单行候选信息。
    """
    plants = get_row_plants(context, row)
    slow_value = get_slow_value(context, row)
    independent_blood = get_independent_blood_value(context, row)
    non_spike_count = count_non_spikeweed_plants(plants)
    cleared = non_spike_count == 0

    category = "cleared"
    if not cleared and slow_value is not None:
        if slow_value <= CONE_SAFE_VALUE:
            category = "cone_safe"
        elif slow_value <= BUCKET_SAFE_VALUE:
            category = "bucket_safe"
        else:
            category = "unsafe"
    elif not cleared:
        category = "unknown"

    return {
        "row": row,
        "plants": plants,
        "slow": slow_value,
        "independent_blood": independent_blood,
        "non_spike_count": non_spike_count,
        "cleared": cleared,
        "category": category,
    }


def make_actions_for_record(record: Dict[str, Any]) -> List[BreakAction]:
    """
    根据候选行生成当前要执行的动作。

    注意：
        这里只给“当前目标行”的动作。
        真正下一路什么时候打，由下一次策略更新决定。
    """
    row = int(record["row"])
    display_row = row + 1
    slow_value = record.get("slow")
    category = record.get("category")

    if slow_value is None:
        return []

    if category == "cone_safe":
        return [
            BreakAction(
                zombie="cone",
                row=row,
                count=1,
                note=(
                    f"R{display_row}: 倾斜阵路障安全单破，"
                    f"slow={slow_value} <= 路障安全阈值{CONE_SAFE_VALUE}。"
                    "下完后等待该路非地刺植物全部清空，再更新策略。"
                ),
            )
        ]

    if category == "bucket_safe":
        return [
            BreakAction(
                zombie="bucket",
                row=row,
                count=1,
                note=(
                    f"R{display_row}: 倾斜阵无路障安全路时选铁桶安全单破，"
                    f"slow={slow_value} <= 铁桶安全阈值{BUCKET_SAFE_VALUE}。"
                    "下完后等待该路非地刺植物全部清空，再更新策略。"
                ),
            )
        ]

    if category == "unsafe":
        remaining = max(0, int(slow_value) - BUCKET_HP)
        cone_count = int(math.ceil(remaining / CONE_HP))

        actions = [
            BreakAction(
                zombie="bucket",
                row=row,
                count=1,
                note=(
                    f"R{display_row}: 倾斜阵无安全单破路，选择最低不安全路强破，"
                    f"slow={slow_value} > 铁桶血量{BUCKET_HP}。先下铁桶。"
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
                        f"R{display_row}: 【确认上一只死亡后】补第 {idx + 1} 只路障。"
                    ),
                )
            )

        return actions

    return []


def sort_current_strategy(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    当前策略排序：

    1. 如果存在路障安全路：
        只把路障安全路作为当前优先安全路，从 slow 大到小；
        其他路放后面。

    2. 如果不存在路障安全路，但存在铁桶安全路：
        铁桶安全路从 slow 大到小。

    3. 最后是不安全路，从 slow 小到大。
    """
    active_records = [
        record
        for record in records
        if not record.get("cleared") and record.get("slow") is not None
    ]

    cone_safe = [
        record for record in active_records
        if record.get("category") == "cone_safe"
    ]
    bucket_safe = [
        record for record in active_records
        if record.get("category") == "bucket_safe"
    ]
    unsafe = [
        record for record in active_records
        if record.get("category") == "unsafe"
    ]

    cone_safe.sort(key=lambda r: int(r["slow"]), reverse=True)
    bucket_safe.sort(key=lambda r: int(r["slow"]), reverse=True)
    unsafe.sort(key=lambda r: int(r["slow"]))

    if cone_safe:
        return cone_safe + bucket_safe + unsafe

    if bucket_safe:
        return bucket_safe + unsafe

    return unsafe


def describe_record(record: Dict[str, Any]) -> str:
    row = int(record["row"]) + 1
    slow = record.get("slow")
    independent = record.get("independent_blood")
    category = record.get("category")

    category_text = {
        "cone_safe": "路障安全",
        "bucket_safe": "铁桶安全",
        "unsafe": "不安全",
        "unknown": "缺少算血",
        "cleared": "已清空",
    }.get(str(category), str(category))

    if independent is None:
        return f"R{row}:{category_text},slow={slow}"

    return f"R{row}:{category_text},slow={slow},独立={independent}"


def build_new_plan(context: BreakContext, update_reason: str) -> BreakPlan:
    """
    重新计算当前策略。
    """
    records = [build_lane_record(context, row) for row in range(5)]
    ordered_records = sort_current_strategy(records)

    if not ordered_records:
        return BreakPlan(
            theme=THEME_NAME,
            actions=[],
            confidence=0.0,
            reason=(
                "倾斜阵策略：所有行的非地刺植物都已清空，"
                "当前无需继续下僵尸。"
            ),
            debug={
                "strategy": "diagonal",
                "strategy_updated": True,
                "update_reason": update_reason,
                "records": records,
            },
        )

    target = ordered_records[0]
    actions = make_actions_for_record(target)

    if not actions:
        return BreakPlan(
            theme=THEME_NAME,
            actions=[],
            confidence=0.0,
            reason="倾斜阵策略：存在候选行，但无法生成动作，请检查 slow 算血值。",
            debug={
                "strategy": "diagonal",
                "strategy_updated": True,
                "update_reason": update_reason,
                "records": records,
                "ordered_records": ordered_records,
            },
        )

    target_row = int(target["row"]) + 1
    target_slow = target.get("slow")
    target_category = target.get("category")

    order_text = " -> ".join(describe_record(record) for record in ordered_records)

    if target_category == "cone_safe":
        target_text = (
            f"当前选择 R{target_row} 路障单破，"
            f"因为存在路障安全路，且该路 slow={target_slow} 为路障安全路中最大。"
        )
    elif target_category == "bucket_safe":
        target_text = (
            f"当前选择 R{target_row} 铁桶单破，"
            f"因为没有路障安全路，且该路 slow={target_slow} 为铁桶安全路中最大。"
        )
    else:
        target_text = (
            f"当前选择 R{target_row} 强破，"
            f"因为没有安全单破路，该路 slow={target_slow} 为不安全路中最小。"
        )

    return BreakPlan(
        theme=THEME_NAME,
        actions=actions,
        confidence=0.96,
        reason=(
            f"倾斜阵事件更新策略[{update_reason}]："
            f"{target_text} "
            f"当前排序：{order_text}。"
            "后续等待某一路除地刺外植物全部清空后再更新策略。"
        ),
        debug={
            "strategy": "diagonal",
            "strategy_updated": True,
            "update_reason": update_reason,
            "cone_hp": CONE_HP,
            "bucket_hp": BUCKET_HP,
            "cone_safe_value": CONE_SAFE_VALUE,
            "bucket_safe_value": BUCKET_SAFE_VALUE,
            "target_row": int(target["row"]),
            "target_slow": target_slow,
            "target_category": target_category,
            "ordered_rows": [
                {
                    "row": record["row"],
                    "slow": record.get("slow"),
                    "independent_blood": record.get("independent_blood"),
                    "category": record.get("category"),
                    "cleared": record.get("cleared"),
                    "non_spike_count": record.get("non_spike_count"),
                }
                for record in ordered_records
            ],
        },
    )


def solve(context: BreakContext) -> BreakPlan:
    """
    倾斜阵主入口。

    策略只在以下事件发生时重新计算：
        - 第一次进入；
        - 某一行非地刺植物全部清空；
        - 新一关 / 棋盘记忆重置。
    """
    global _LAST_CLEAR_MASK
    global _LAST_NON_SPIKE_COUNTS
    global _LAST_PLAN

    clear_mask, non_spike_counts = get_board_state(context)
    should_update, update_reason = should_update_strategy(clear_mask, non_spike_counts)

    # 不更新时返回上一份计划，避免策略因为中途某个植物被吃掉但未清空整路而抖动。
    if not should_update and _LAST_PLAN is not None:
        cached_plan = BreakPlan(
            theme=_LAST_PLAN.theme,
            actions=_LAST_PLAN.actions,
            confidence=_LAST_PLAN.confidence,
            reason=(
                "倾斜阵策略未更新：等待某一路除地刺外植物全部清空。"
                f" 当前清空状态={clear_mask}。上一策略：{_LAST_PLAN.reason}"
            ),
            debug={
                **_LAST_PLAN.debug,
                "strategy_updated": False,
                "update_reason": update_reason,
                "clear_mask": clear_mask,
                "non_spike_counts": non_spike_counts,
            },
        )

        # 仍然记录最新状态，但不重算策略。
        _LAST_CLEAR_MASK = clear_mask
        _LAST_NON_SPIKE_COUNTS = non_spike_counts
        return cached_plan

    plan = build_new_plan(context, update_reason)

    _LAST_CLEAR_MASK = clear_mask
    _LAST_NON_SPIKE_COUNTS = non_spike_counts
    _LAST_PLAN = plan

    return plan
