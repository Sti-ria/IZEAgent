# -*- coding: utf-8 -*-
from core.breaker_types import BreakAction, BreakContext, BreakPlan
import itertools

# 动态引入灰烬感知算血器与原生算血器
try:
    from tools.debug_ash_aware_blood_calculator import AshAwareBloodCalculator
    from core.ize_blood_calculator import IZEBloodCalculator
except ImportError:
    # 兼容备用导入路径
    from debug_ash_aware_blood_calculator import AshAwareBloodCalculator
    from ize_blood_calculator import IZEBloodCalculator

THEME_NAME = "爆炸"
ATTACK_PLANTS = ['puffshroom']  # 爆炸主题仅有小喷菇一种输出植物
ASH_PLANTS = {'potatomine', 'chomper'}  # 爆炸主题灰烬植物集合：土豆地雷、大嘴花

def get_row_plants(context: BreakContext, row: int) -> list[str]:
    """获取某一行前5列的植物列表，清洗格式并去除下划线与首尾空格"""
    row_plants = []
    for col in range(5):
        plant = context.board_5x5[row][col]
        if plant:
            plant_clean = str(plant).replace('_', '').lower().strip()
            row_plants.append(plant_clean)
        else:
            row_plants.append("")
    return row_plants

def check_can_single_dance(plants: list[str]) -> bool:
    """
    判断是否满足单下舞王的硬性排布环境条件：
    1. 后三列(3,4,5列)无输出
    2. 后两列(4,5列)无输出，且整行≤2输出
    3. 后三列(3,4,5列)单小喷，且整行≤2输出
    """
    total_output = sum(1 for p in plants if p in ATTACK_PLANTS)
    
    back_3 = plants[:3]
    back_2 = plants[:2]
    
    back_3_outputs = sum(1 for p in back_3 if p in ATTACK_PLANTS)
    back_2_outputs = sum(1 for p in back_2 if p in ATTACK_PLANTS)
    
    # 条件 1: 后三列无输出
    if back_3_outputs == 0:
        return True
        
    # 条件 2: 后两列无输出，且整行≤2输出
    if back_2_outputs == 0 and total_output <= 2:
        return True
        
    # 条件 3: 后三列单小喷，且整行≤2输出
    if back_3_outputs == 1 and total_output <= 2:
        back_3_attack_plants = [p for p in back_3 if p in ATTACK_PLANTS]
        if back_3_attack_plants and back_3_attack_plants[0] == 'puffshroom':
            return True
        
    return False

def evaluate_single_lane_break(ash_calc: AshAwareBloodCalculator, row: int, plants: list[str]) -> tuple[list[BreakAction], int]:
    """
    利用灰烬感知算血器计算单路原生单破代价（用于未被舞王及伴舞覆盖的独立行收尾）
    """
    cost_dict = ash_calc.calculate_lane(plants)
    display_row = row + 1
    
    best_mode = "slow"
    min_total_cost = cost_dict.get("slow", 250)
    for mode in ["slow", "ladder", "football"]:
        if mode in cost_dict and cost_dict[mode] < min_total_cost:
            min_total_cost = cost_dict[mode]
            best_mode = mode

    # 检查当前行是否存在任何灰烬植物
    has_ash = any(p in ASH_PLANTS for p in plants)

    # 矿工绕后保底判定：只有在本路没有任何灰烬植物时，才允许使用矿工
    if not has_ash and 175 < min_total_cost:
        return [
            BreakAction(zombie="miner", row=row, count=1, note=f"R{display_row}: 矿工绕后单破"),
            BreakAction(zombie="imp", row=row, count=1, note=f"R{display_row}: 补小鬼吃脑")
        ], 175

    actions = []
    
    # 还原并注入排雷模拟过程中所派遣的所有牺牲打僵尸动作
    sacrifice_zombies = cost_dict.get("_sacrifices", [])
    for zb in sacrifice_zombies:
        actions.append(BreakAction(zombie=zb, row=row, count=1, note=f"R{display_row}: 排雷派遣 {zb}"))
        
    sacrifice_cost = cost_dict.get("_sacrifice_cost", 0)
    final_lane_cost = min_total_cost - sacrifice_cost  # 残阵所需的吃脑花费
    
    if best_mode == "slow":
        final_zombie = "bucket" if final_lane_cost >= 125 else "cone"
        actions.append(BreakAction(zombie=final_zombie, row=row, count=1, note=f"R{display_row}: {final_zombie}收尾吃脑"))
    elif best_mode == "ladder":
        actions.append(BreakAction(zombie="ladder", row=row, count=1, note=f"R{display_row}: 扶梯收尾破阵"))
    elif best_mode == "football":
        actions.append(BreakAction(zombie="football", row=row, count=1, note=f"R{display_row}: 橄榄收尾破阵"))

    return actions, min_total_cost

def calculate_dance_lane_cost_and_actions(ash_calc: AshAwareBloodCalculator, row: int, plants: list[str]) -> tuple[list[BreakAction], int]:
    """
    核心计算：计算当前行投放舞王时的代价与行动队列
    """
    actions = []
    cost = 350  # 舞王基础花费
    display_row = row + 1
    
    cost_dict = ash_calc.calculate_lane(plants)

    # 1. 5列大嘴花防线处理：当且仅当5路是大嘴花时，前置小鬼下放喂杀骗招
    if plants[4] == 'chomper':
        actions.append(BreakAction(zombie="imp", row=row, count=1, note=f"R{display_row}: 5列遇大嘴花，下小鬼喂杀骗招"))
        cost += 50

    # 2. 盾牌判定：不符合单下舞王条件时，根据算血选择最优承伤盾防在舞王前方
    if not check_can_single_dance(plants):
        best_shield = "cone"
        shield_cost = 75
        
        if cost_dict.get("slow", 999) >= 125:
            best_shield = "bucket"
            shield_cost = 125
        if cost_dict.get("ladder", 999) < shield_cost:
            best_shield = "ladder"
            shield_cost = cost_dict["ladder"]
        if cost_dict.get("football", 999) < shield_cost:
            best_shield = "football"
            shield_cost = cost_dict["football"]

        actions.append(BreakAction(zombie=best_shield, row=row, count=1, note=f"R{display_row}: 不足单下条件，前置{best_shield}盾防"))
        cost += shield_cost

    # 3. 核心舞王本体
    actions.append(BreakAction(zombie="dancer", row=row, count=1, note=f"R{display_row}: 核心舞王切入"))
    
    return actions, cost

def solve(context: BreakContext) -> BreakPlan:
    """
    爆炸主题解算器：主体思路为双舞王。
    强制：1或者2路必须有一个舞王；4或者5路必须有一个舞王。
    """
    native_calc = IZEBloodCalculator(use_modified_pole=True)
    ash_calc = AshAwareBloodCalculator(native_calc)
    
    lane_plants = [get_row_plants(context, r) for r in range(5)]
    
    # 步骤一：决算各路单独推进与单独下舞王的动作和花费
    base_single_results = {}
    dance_lane_results = {}
    for r in range(5):
        base_single_results[r] = {"actions": [], "cost": 0}
        base_single_results[r]["actions"], base_single_results[r]["cost"] = evaluate_single_lane_break(ash_calc, r, lane_plants[r])
        
        dance_lane_results[r] = {"actions": [], "cost": 0}
        dance_lane_results[r]["actions"], dance_lane_results[r]["cost"] = calculate_dance_lane_cost_and_actions(ash_calc, r, lane_plants[r])

    best_global_cost = float('inf')
    best_dance_rows = []

    # 步骤二：构建双舞王组合空间。
    # 强约束条件：1、2路(索引0,1)选一个，4、5路(索引3,4)选一个。
    # 组合数仅有 2 * 2 = 4 种情况
    upper_choices = [0, 1]
    lower_choices = [3, 4]
    
    double_dance_combinations = list(itertools.product(upper_choices, lower_choices))

    # 步骤三：穷举满足双舞王强约束条件的4种拓扑辐射情况，寻找全局最低消费
    for dance_rows in double_dance_combinations:
        current_combination_cost = 0
        covered_lanes = set()
        
        # 统计召唤舞王后，伴舞僵尸能免费覆盖和吃脑的上下邻接行
        for d_row in dance_rows:
            covered_lanes.add(d_row)
            if d_row > 0: covered_lanes.add(d_row - 1)
            if d_row < 4: covered_lanes.add(d_row + 1)
            
        # 累加5路综合总花费
        for r in range(5):
            if r in dance_rows:
                # 舞王主攻核心行
                current_combination_cost += dance_lane_results[r]["cost"]
            elif r in covered_lanes:
                # 伴舞免费覆盖行，不需要再派额外兵力
                current_combination_cost += 0
            else:
                # 未被双舞王辐射包络覆盖到的真空行，使用单路低成本破阵方案
                current_combination_cost += base_single_results[r]["cost"]

        if current_combination_cost < best_global_cost:
            best_global_cost = current_combination_cost
            best_dance_rows = list(dance_rows)

    # 步骤四：装配生成决策计划包
    final_actions = []
    reasons = [f"双舞王硬锁博弈总花费: {best_global_cost} 阳光"]
    
    final_covered = set()
    for d_row in best_dance_rows:
        final_covered.add(d_row)
        if d_row > 0: final_covered.add(d_row - 1)
        if d_row < 4: final_covered.add(d_row + 1)

    for r in range(5):
        display_idx = r + 1
        if r in best_dance_rows:
            final_actions.extend(dance_lane_results[r]["actions"])
            reasons.append(f"R{display_idx}: 双舞王主线({dance_lane_results[r]['cost']})")
        elif r in final_covered:
            reasons.append(f"R{display_idx}: 伴舞辐射清场")
        else:
            final_actions.extend(base_single_results[r]["actions"])
            reasons.append(f"R{display_idx}: 孤立真空行单破({base_single_results[r]['cost']})")

    return BreakPlan(
        theme=THEME_NAME,
        actions=final_actions,
        confidence=0.99,
        reason="爆炸全局双舞王最优解: " + " | ".join(reasons)
    )