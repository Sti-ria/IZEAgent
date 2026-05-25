from core.breaker_types import BreakAction, BreakContext, BreakPlan

THEME_NAME = "输出"
DANCER_COST_THRESHOLD = 350

# 全量定义具有正面高输出/减速威胁的植物列表（纯字母命名，不含下划线）
ATTACK_PLANTS = ['fumeshroom', 'puffshroom', 'peashooter', 'repeater', 'snowpea', 'splitpea']
# 极高输出/强减速植物
HEAVY_ATTACK_PLANTS = ['fumeshroom', 'repeater', 'snowpea']

def get_row_plants(context: BreakContext, row: int) -> list[str]:
    """获取某一行前5列的植物列表，清洗格式并去除下划线与首尾空格"""
    row_plants = []
    for col in range(5):
        plant = context.board_5x5[row][col]
        if plant:
            # 确保清洗掉可能残余的下划线，并转为小写、去除空格
            plant_clean = str(plant).replace('_', '').lower().strip()
            row_plants.append(plant_clean)
        else:
            row_plants.append("")
    return row_plants

def count_outputs(plants: list[str]) -> int:
    """计算整行的总输出植物数量（包含喷菇和豌豆系列）"""
    return sum(1 for p in plants if p in ATTACK_PLANTS)

def count_split_peas_past_col1(plants: list[str]) -> int:
    """精准计算第2列到第5列（索引1到4）的裂荚射手总数，防止矿工送死"""
    return sum(1 for p in plants[1:5] if p == 'splitpea')

def check_dance_lane_rules(plants: list[str], total_output: int) -> tuple[bool, str]:
    """
    针对输出主题改良的舞王下落判定规则（全面防范豌豆高输出与大喷菇）
    返回: (是否允许, "single"代表单下舞王 / "cone"代表路障+舞王 / ""代表不能下)
    """
    front_3_plants = plants[0:3]
    back_3_plants = plants[2:5]
    back_2_plants = plants[3:5]
    
    back_3_outputs = sum(1 for p in back_3_plants if p in ATTACK_PLANTS)
    back_2_outputs = sum(1 for p in back_2_plants if p in ATTACK_PLANTS)
    
    # 核心禁忌条件 1：只要 1、2、3 列存在双发射手 (repeater) 或寒冰射手 (snowpea)，绝对不单下舞王
    if 'repeater' in front_3_plants or 'snowpea' in front_3_plants:
        return False, ""

    # 核心禁忌条件 2：后两列存在大喷菇、双发或寒冰，或者后排输出植物数量 >= 2（绝不单下或垫刀送舞王）
    has_heavy_back_2 = any(p in HEAVY_ATTACK_PLANTS for p in back_2_plants)
    if has_heavy_back_2 or back_2_outputs >= 2:
        return False, ""

    # 核心禁忌条件 3：如果整行总输出植物极多（>= 4），单下舞王生存率极低
    if total_output >= 4:
        return False, ""

    # 1. 后三列无任何输出植物 -> 极度安全，单下舞王
    if back_3_outputs == 0:
        return True, "single"
    
    # 2. 后两列无输出，且整行 <= 2 个输出植物 -> 较安全，单下舞王
    if back_2_outputs == 0 and total_output <= 2:
        return True, "single"
    
    # 3. 后三列只有1个非重型输出植物（如单小喷/单普豌），且整行 <= 2 输出 -> 单下舞王
    has_heavy_back_3 = any(p in HEAVY_ATTACK_PLANTS for p in back_3_plants)
    if back_3_outputs == 1 and not has_heavy_back_3 and total_output <= 2:
        return True, "single"
        
    # 4. 恰好3输出且后两列威胁低的特殊防御转换 -> 先路障再舞王
    if back_2_outputs == 0 and total_output == 3:
        return True, "cone"

    return False, ""

def evaluate_output_single_break(context: BreakContext, row: int) -> tuple[list[BreakAction], int]:
    """
    根据输出主题的优先级单破逻辑，计算单行的最便宜方案。
    返回值: (Action列表, 预估花费)
    """
    recommended_modes = context.recommended_modes(row)
    plants = get_row_plants(context, row)
    display_row = row + 1
    
    has_split_pea_bad_zones = count_split_peas_past_col1(plants) > 0

    # 优先级 1: 撑杆(pole)可单破的直接破
    if "pole" in recommended_modes:
        return [BreakAction(zombie="pole", row=row, count=1, note=f"R{display_row}: 撑杆可单破")], 75
        
    # 优先级 2: 慢速僵尸(slow) 判定逻辑 —— 根据算血器给出的数值精准切分
    if "slow" in recommended_modes:
        slow_val = context.mode_value(row, "slow")
        if slow_val >= 28: 
            return [BreakAction(zombie="bucket", row=row, count=1, note=f"R{display_row}: 铁桶单破（算血值:{slow_val} >= 28）")], 125
        else:
            return [BreakAction(zombie="cone", row=row, count=1, note=f"R{display_row}: 路障单破（算血值:{slow_val} < 28）")], 75

    # 优先级 3: 如果扶梯(ladder)可单破则用扶梯
    if "ladder" in recommended_modes:
        return [BreakAction(zombie="ladder", row=row, count=1, note=f"R{display_row}: 扶梯可单破")], 150

    # 优先级 4: 【核心修改】矿工掘地无敌破阵法
    # 只要后方（2-5列）没有任何能往后打的裂荚射手(splitpea)，完全不用看正面多高火力的慢速僵尸结果
    if not has_split_pea_bad_zones:
        # 矿工单破必须在挖穿后补充小鬼僵尸收尾咬脑子
        return [
            BreakAction(zombie="miner", row=row, count=1, note=f"R{display_row}: 矿工掘地期间无敌，后方无裂荚，强行单破绕后"),
            BreakAction(zombie="imp", row=row, count=1, note=f"R{display_row}: 【等矿工挖穿清场后】补放小鬼僵尸收割脑子")
        ], 175  # 矿工 125 + 小鬼 50 = 175

    # 优先级 5: 如果橄榄(football)可单破则用橄榄
    if "football" in recommended_modes:
        return [BreakAction(zombie="football", row=row, count=1, note=f"R{display_row}: 橄榄可单破")], 175

    # 优先级 6: 如果杆梯可过则用杆梯（先下撑杆越过，再放扶梯搭梯）
    if "pole_ladder" in recommended_modes:
        return [
            BreakAction(zombie="pole", row=row, count=1, note=f"R{display_row}: 杆梯组合-先放撑杆起跳越过"),
            BreakAction(zombie="ladder", row=row, count=1, note=f"R{display_row}: 【起跳后】接扶梯搭梯推进")
        ], 225

    # 优先级 7: 均不满足，采用 橄榄 + 路障 强突保底
    return [
        BreakAction(zombie="football", row=row, count=1, note=f"R{display_row}: 无法常规单破，保底橄榄顶前"),
        BreakAction(zombie="cone", row=row, count=1, note=f"R{display_row}: 【等橄榄吸收伤害】路障跟进")
    ], 250

def solve(context: BreakContext) -> BreakPlan:
    """
    输出主题规则式策略
    """
    all_actions = [None] * 5
    reasons = [""] * 5
    
    lane_single_costs = []
    lane_single_actions = []

    # -------------------------------------------------------------
    # 第一步：根据输出主题独有的优先级逻辑，预计算5路单破方案
    # -------------------------------------------------------------
    for row in range(5):
        actions, cost = evaluate_output_single_break(context, row)
        lane_single_costs.append(cost)
        lane_single_actions.append(actions)

    # -------------------------------------------------------------
    # 第二步：战术舞王组合高级判定（连续三路花费之和 > 350 时，且只接受在中间路下舞王）
    # -------------------------------------------------------------
    dance_group_fixed = False
    
    for start_row in range(3):
        r1, r2, r3 = start_row, start_row + 1, start_row + 2
        
        # 判断连续三路的单破花费之和是否大于 350
        total_three_lane_cost = lane_single_costs[r1] + lane_single_costs[r2] + lane_single_costs[r3]
        if total_three_lane_cost > DANCER_COST_THRESHOLD:
            
            # 严格限制：只允许在中间路 (r2) 下舞王
            target_row = r2
            plants = get_row_plants(context, target_row)
            total_output = count_outputs(plants)
            display_row = target_row + 1
            
            dance_actions = []
            dance_combination_type = ""

            # 按照【舞王组合判断标准优先级序列】逐条筛选：
            
            # 组合 1：单下舞王标准
            can_dance, dance_type = check_dance_lane_rules(plants, total_output)
            if can_dance and dance_type == "single":
                dance_actions.append(BreakAction(zombie="dancer", row=target_row, count=1, note=f"R{display_row}: 连续3路总开销高，单放舞王协同破阵"))
                dance_combination_type = "单下舞王"
            
            # 组合 2：路障+舞王标准
            elif can_dance and dance_type == "cone":
                dance_actions.append(BreakAction(zombie="cone", row=target_row, count=1, note=f"R{display_row}: 连续3路总开销高，战术先下路障垫刀"))
                dance_actions.append(BreakAction(zombie="dancer", row=target_row, count=1, note=f"R{display_row}: 【路障速接】放舞王跟进"))
                dance_combination_type = "路障+舞王"

            # 组合 3：矿工+舞王标准（前提：当前行单破确实用到了矿工，说明矿工能挖穿且安全）
            elif any(act.zombie == "miner" for act in lane_single_actions[target_row]):
                dance_actions.append(BreakAction(zombie="miner", row=target_row, count=1, note=f"R{display_row}: 战术舞王-先放矿工绕后拆除火力"))
                dance_actions.append(BreakAction(zombie="dancer", row=target_row, count=1, note=f"R{display_row}: 【等矿工挖穿/确认安全后】再下舞王"))
                dance_combination_type = "矿工+舞王"

            # 组合 4：扶梯+舞王标准（前提：该路算血器支持梯子操作）
            elif "ladder" in context.recommended_modes(target_row) or "pole_ladder" in context.recommended_modes(target_row):
                dance_actions.append(BreakAction(zombie="ladder", row=target_row, count=1, note=f"R{display_row}: 战术舞王-先下扶梯架梯"))
                dance_actions.append(BreakAction(zombie="dancer", row=target_row, count=1, note=f"R{display_row}: 【扶梯吃三口伤害后/临近7列】下舞王推进"))
                dance_combination_type = "扶梯+舞王"

            # 成功拦截并应用了某种舞王组合
            if dance_actions:
                all_actions[target_row] = dance_actions
                reasons[target_row] = f"R{display_row}: 连续高压总花费{total_three_lane_cost}触发【{dance_combination_type}】"
                
                # 伴舞接管上下两路
                for accomplice_row in [r1, r3]:
                    all_actions[accomplice_row] = []
                    reasons[accomplice_row] = f"R{accomplice_row+1}: 已由第 {display_row} 行舞王伴舞自动破阵"
                
                dance_group_fixed = True
                break
                
        if dance_group_fixed:
            break

    # -------------------------------------------------------------
    # 第三步：常规逐行处理（填入未被舞王战术覆盖的行）
    # -------------------------------------------------------------
    for row in range(5):
        if all_actions[row] is not None:
            continue  # 跳过舞王协同行
            
        all_actions[row] = lane_single_actions[row]
        reasons[row] = f"R{row+1}: 执行输出主题特化单破"

    # -------------------------------------------------------------
    # 第四步：汇总输出
    # -------------------------------------------------------------
    final_actions = []
    for act_list in all_actions:
        if act_list:
            final_actions.extend(act_list)

    return BreakPlan(
        theme=THEME_NAME,
        actions=final_actions,
        confidence=0.97,
        reason="输出阵特化规则: " + " | ".join(filter(None, reasons))
    )