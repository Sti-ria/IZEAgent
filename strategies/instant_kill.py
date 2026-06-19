# -*- coding: utf-8 -*-
from core.breaker_types import BreakAction, BreakContext, BreakPlan
import itertools

# 动态引入我们定制的灰烬感知算血器
try:
    from tools.debug_ash_aware_blood_calculator import AshAwareBloodCalculator
    from core.ize_blood_calculator import IZEBloodCalculator
except ImportError:
    # 兼容备用导入路径
    from debug_ash_aware_blood_calculator import AshAwareBloodCalculator
    from ize_blood_calculator import IZEBloodCalculator

THEME_NAME = "即死"
ATTACK_PLANTS = ['fumeshroom', 'puffshroom', 'peashooter', 'repeater', 'snowpea', 'splitpea']
ASH_PLANTS = {'potatomine', 'squash', 'chomper'}  # 灰烬植物集合

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
    
    back_3 = plants[2:5]  # 第3, 4, 5列
    back_2 = plants[3:5]  # 第4, 5列
    
    back_3_outputs = sum(1 for p in back_3 if p in ATTACK_PLANTS)
    back_2_outputs = sum(1 for p in back_2 if p in ATTACK_PLANTS)
    
    if back_3_outputs == 0:
        return True
        
    if back_2_outputs == 0 and total_output <= 2:
        return True
        
    if back_3_outputs == 1 and total_output <= 2:
        back_3_attack_plants = [p for p in back_3 if p in ATTACK_PLANTS]
        if back_3_attack_plants and back_3_attack_plants[0] == 'puffshroom':
            return True
        
    return False

def evaluate_single_lane_break(ash_calc: AshAwareBloodCalculator, row: int, plants: list[str]) -> tuple[list[BreakAction], int]:
    """
    利用全新重构的 AshAwareBloodCalculator 精确决算单路最少花费，并还原每一步的排雷动作流。
    """
    cost_dict = ash_calc.calculate_lane(plants)
    display_row = row + 1
    
    best_mode = "slow"
    min_total_cost = cost_dict.get("slow", 250)
    for mode in ["slow", "ladder", "football"]:
        if mode in cost_dict and cost_dict[mode] < min_total_cost:
            min_total_cost = cost_dict[mode]
            best_mode = mode

    has_ash = any(p in ASH_PLANTS for p in plants)

    if not has_ash and 'splitpea' not in plants[1:5] and 175 < min_total_cost:
        return [
            BreakAction(zombie="miner", row=row, count=1, note=f"R{display_row}: 矿工绕后单破"),
            BreakAction(zombie="imp", row=row, count=1, note=f"R{display_row}: 补小鬼吃脑")
        ], 175

    actions = []
    
    sacrifice_zombies = cost_dict.get("_sacrifices", [])
    for zb in sacrifice_zombies:
        actions.append(BreakAction(zombie=zb, row=row, count=1, note=f"R{display_row}: 排雷派遣 {zb}"))
        
    sacrifice_cost = cost_dict.get("_sacrifice_cost", 0)
    final_lane_cost = min_total_cost - sacrifice_cost
    
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
    ★ 核心修改：评估单路投放舞王时的代价与动作序列
    引入飞贼针对123列唯一大喷菇的“环境安全伴生锁”，不安全则直接 ban 舞王。
    """
    display_row = row + 1
    
    # 统计123列中大喷菇的数量
    fume_count_123 = sum(1 for p in plants[0:3] if p == 'fumeshroom')
    
    # 情况 3: 如果123列有至少两个大喷菇，无条件 ban 舞王
    if fume_count_123 >= 2:
        return [], 999999

    actions = []
    cost = 350  # 舞王基础花费
    eval_plants = list(plants)  # 拷贝阵线用于模拟转化

    # 情况 2: 123列恰有一个大喷菇，审查其周边邻居，判定飞贼可行性
    if fume_count_123 == 1:
        # 寻找该大喷菇所在的具体列索引 (0, 1, 或 2)
        fume_idx = -1
        for i in range(3):
            if eval_plants[i] == 'fumeshroom':
                fume_idx = i
                break
        
        # --- 🔍 飞贼生存环境危险性安全审查 ---
        # 1. 检查左侧植物：如果大喷菇不在底线(idx > 0)，且它左边一个位置是守护植物大嘴花或窝瓜
        if fume_idx > 0:
            left_plant = eval_plants[fume_idx - 1]
            if left_plant in ['chomper', 'squash']:
                return [], 999999  # 飞贼降落必死，Ban掉舞王
                
        # 2. 检查右侧植物：只要右侧紧挨着的植物是窝瓜，窝瓜就会回头砸飞贼
        if fume_idx < 4:
            right_plant = eval_plants[fume_idx + 1]
            if right_plant == 'squash':
                return [], 999999  # 飞贼必被回头砸，Ban掉舞王
        
        # --- 💡 环境安全，通过审查，正式派遣飞贼 ---
        actions.append(BreakAction(zombie="bungee", row=row, count=1, note=f"R{display_row}: 环境安全，前置飞贼清除123列唯一大喷菇"))
        cost += 125
        eval_plants[fume_idx] = 'empty'

    # 情况 1 & 后续推进逻辑
    cost_dict = ash_calc.calculate_lane(eval_plants)

    # 5路常规灰烬/大嘴花排雷垫小鬼
    if eval_plants[4] in ['chomper', 'squash']:
        actions.append(BreakAction(zombie="imp", row=row, count=1, note=f"R{display_row}: 5列遇大嘴花/窝瓜，下小鬼喂杀骗招"))
        cost += 50

    # 盾牌前置防护判断
    if not check_can_single_dance(eval_plants):
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

    # 舞王切入
    actions.append(BreakAction(zombie="dancer", row=row, count=1, note=f"R{display_row}: 核心舞王切入"))
    
    return actions, cost

def solve(context: BreakContext) -> BreakPlan:
    """
    即死主题：全局舞王流与全新灰烬算血感知器融合的最优破阵策略
    """
    native_calc = IZEBloodCalculator(use_modified_pole=True)
    ash_calc = AshAwareBloodCalculator(native_calc)
    
    lane_plants = [get_row_plants(context, r) for r in range(5)]
    
    # 步骤一：单路原生单破代价决算
    base_single_results = {}
    for r in range(5):
        acts, cost = evaluate_single_lane_break(ash_calc, r, lane_plants[r])
        base_single_results[r] = {"actions": acts, "cost": cost}

    # 步骤二：单路舞王突击方案代价决算
    dance_lane_results = {}
    for r in range(5):
        acts, cost = calculate_dance_lane_cost_and_actions(ash_calc, r, lane_plants[r])
        dance_lane_results[r] = {"actions": acts, "cost": cost}

    # 步骤三：穷举全局所有舞王摆放可能性
    best_global_cost = float('inf')
    best_dance_rows = []

    all_dance_possibilities = [[]] + [[r] for r in range(5)] + [list(c) for c in itertools.combinations(range(5), 2)]

    for dance_rows in all_dance_possibilities:
        current_combination_cost = 0
        covered_lanes = set()
        
        for d_row in dance_rows:
            covered_lanes.add(d_row)
            if d_row > 0: covered_lanes.add(d_row - 1)
            if d_row < 4: covered_lanes.add(d_row + 1)
            
        for r in range(5):
            if r in dance_rows:
                current_combination_cost += dance_lane_results[r]["cost"]
            elif r in covered_lanes:
                current_combination_cost += 0
            else:
                current_combination_cost += base_single_results[r]["cost"]

        if current_combination_cost < best_global_cost:
            best_global_cost = current_combination_cost
            best_dance_rows = dance_rows

    # 步骤四：装配最终决策计划包
    final_actions = []
    reasons = [f"灰烬博弈动态总花费: {best_global_cost} 阳光"]
    
    final_covered = set()
    for d_row in best_dance_rows:
        final_covered.add(d_row)
        if d_row > 0: final_covered.add(d_row - 1)
        if d_row < 4: final_covered.add(d_row + 1)

    for r in range(5):
        display_idx = r + 1
        if r in best_dance_rows:
            final_actions.extend(dance_lane_results[r]["actions"])
            reasons.append(f"R{display_idx}: 舞王主攻线({dance_lane_results[r]['cost']})")
        elif r in final_covered:
            reasons.append(f"R{display_idx}: 伴舞免费覆盖")
        else:
            final_actions.extend(base_single_results[r]["actions"])
            reasons.append(f"R{display_idx}: 真空区独立单破({base_single_results[r]['cost']})")

    return BreakPlan(
        theme=THEME_NAME,
        actions=final_actions,
        confidence=0.99,
        reason="即死全局灰烬感知最优解: " + " | ".join(reasons)
    )