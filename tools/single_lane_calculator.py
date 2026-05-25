"""
单破计算器 (Single Lane Calculator)
用于计算单路在忽略其他路影响下的最优僵尸组合方案。
"""

from core.breaker_types import BreakAction, BreakContext

# 7种核心策略的花费映射 (Sun Cost)
# 注：根据算血器的定义，"slow" 通常代表慢速僵尸的基础状态
STRATEGY_COSTS = {
    "slow_cone": 75,         # 路障策略 (对应算血器中的 slow 推荐)
    "pole": 75,              # 撑杆策略
    "slow_bucket": 125,      # 铁桶策略 (同属慢速，花费125)
    "ladder": 150,           # 梯子策略 (花费150)
    "football": 175,         # 橄榄球策略
    "pole_ladder": 225,      # 撑杆(75) + 梯子(150) = 225
    "cone_football": 250,    # 路障(75) + 橄榄(175) = 250 (保底策略)
}

def calculate_best_zombie_for_lane(context: BreakContext, row: int) -> list[BreakAction]:
    """
    输入棋盘上下文和指定的行号(0-based)，返回该行概率最高且花费最低的僵尸组合 Action 列表。
    """
    # 1. 获取算血器对当前行推荐的所有基础模式列表 (status == 1)
    # 算血器原生返回的可能模式包括: "slow", "pole", "ladder", "football", "pole_ladder"
    recommended_modes = context.recommended_modes(row)
    display_row = row + 1  # 人类可读行号
    
    actions = []
    
    # 2. 如果算血器没有任何推荐，直接触发保底策略：路障 + 橄榄球
    if not recommended_modes:
        actions.append(BreakAction(zombie="football", row=row, count=1, note=f"第 {display_row} 行: 无推荐，保底橄榄顶前"))
        actions.append(BreakAction(zombie="slow", row=row, count=1, note=f"第 {display_row} 行: 无推荐，保底路障跟进"))
        return actions

    # 3. 如果有推荐，评估各策略的可行性并寻找花费最低的
    best_strategy = None
    min_cost = float('inf')
    
    # 依次检查算血器推荐并映射到我们的 7 种细分策略中
    for mode in recommended_modes:
        if mode == "slow":
            # 当算血器推荐 slow(慢速) 时，我们细分为路障和铁桶
            # 优先选择便宜的路障(75)，如果算血参考值很高，则可以考虑铁桶(125)
            # 这里默认取性价比更高的路障作为代表参与花费比对
            current_strat = "slow_cone"
            if STRATEGY_COSTS[current_strat] < min_cost:
                min_cost = STRATEGY_COSTS[current_strat]
                best_strategy = current_strat
                
        elif mode == "pole":
            if STRATEGY_COSTS["pole"] < min_cost:
                min_cost = STRATEGY_COSTS["pole"]
                best_strategy = "pole"
                
        elif mode == "ladder":
            if STRATEGY_COSTS["ladder"] < min_cost:
                min_cost = STRATEGY_COSTS["ladder"]
                best_strategy = "ladder"
                
        elif mode == "football":
            if STRATEGY_COSTS["football"] < min_cost:
                min_cost = STRATEGY_COSTS["football"]
                best_strategy = "football"
                
        elif mode == "pole_ladder":
            if STRATEGY_COSTS["pole_ladder"] < min_cost:
                min_cost = STRATEGY_COSTS["pole_ladder"]
                best_strategy = "pole_ladder"

    # 4. 根据最优策略翻译为对应的真实僵尸部署动作
    if best_strategy == "slow_cone":
        actions.append(BreakAction(zombie="slow", row=row, count=1, note=f"第 {display_row} 行: 采用最低花费路障策略"))
    elif best_strategy == "pole":
        actions.append(BreakAction(zombie="pole", row=row, count=1, note=f"第 {display_row} 行: 采用最低花费撑杆策略"))
    elif best_strategy == "slow_bucket":
        # 如果你后续想通过特定伤害判定强制走铁桶，可以在这里扩展逻辑
        actions.append(BreakAction(zombie="slow", row=row, count=1, note=f"第 {display_row} 行: 采用慢速铁桶策略"))
    elif best_strategy == "ladder":
        actions.append(BreakAction(zombie="ladder", row=row, count=1, note=f"第 {display_row} 行: 采用最低花费梯子策略"))
    elif best_strategy == "football":
        actions.append(BreakAction(zombie="football", row=row, count=1, note=f"第 {display_row} 行: 采用最低花费橄榄策略"))
    elif best_strategy == "pole_ladder":
        actions.append(BreakAction(zombie="ladder", row=row, count=1, note=f"第 {display_row} 行: 组合破阵-梯子搭梯"))
        actions.append(BreakAction(zombie="pole", row=row, count=1, note=f"第 {display_row} 行: 组合破阵-撑杆加速"))

    return actions