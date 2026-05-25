from core.breaker_types import BreakAction, BreakContext, BreakPlan
from tools.single_lane_calculator import calculate_best_zombie_for_lane

THEME_NAME = "穿刺"

# 定义舞王僵尸的花费
DANCER_COST = 350

def get_row_plants(context: BreakContext, row: int) -> list[str]:
    """获取某一行前5列的植物列表"""
    return [context.board_5x5[row][col] for col in range(5)]

def count_outputs(plants: list[str]) -> int:
    """计算某一行中大喷菇或小喷菇（输出）的总数"""
    return sum(1 for p in plants if p in ['fume_shroom', 'puff_shroom'])

def has_magnet(context: BreakContext) -> bool:
    """检查整个棋盘(5x5)中是否还存在磁力菇"""
    for r in range(5):
        for c in range(5):
            if context.board_5x5[r][c] == 'magnet_shroom':
                return True
    return False

def check_dance_lane_rules(plants: list[str], total_output: int) -> tuple[bool, str]:
    """
    检查指定行是否允许下舞王。
    返回: (是否允许, "single"代表单下舞王 / "cone"代表路障+舞王 / ""代表不能下)
    """
    back_3_plants = plants[2:5]
    back_3_outputs = sum(1 for p in back_3_plants if p in ['fume_shroom', 'puff_shroom'])
    
    back_2_plants = plants[3:5]
    back_2_outputs = sum(1 for p in back_2_plants if p in ['fume_shroom', 'puff_shroom'])
    has_big_output_back_2 = 'fume_shroom' in back_2_plants

    # 核心禁忌条件：后两列有大喷，或者后两列输出 >= 4
    if has_big_output_back_2 or back_2_outputs >= 4:
        return False, ""

    # 1. 后三列无输出 -> 单下舞王
    if back_3_outputs == 0:
        return True, "single"
    
    # 2. 后两列无输出，且整行 <= 2 输出 -> 单下舞王
    if back_2_outputs == 0 and total_output <= 2:
        return True, "single"
    
    # 3. 后三列单小喷，且整行 <= 2 输出 -> 单下舞王
    if back_3_outputs == 1 and 'fume_shroom' not in back_3_plants and total_output <= 2:
        return True, "single"
        
    # 4. 恰好3输出的特殊防御转换 -> 先路障再舞王
    if ((back_2_outputs == 0 or (back_3_outputs == 1 and 'fume_shroom' not in back_3_plants)) 
            and total_output == 3):
        return True, "cone"

    return False, ""

def solve(context: BreakContext) -> BreakPlan:
    """
    穿刺阵规则式策略（已集成铁桶降级为双路障逻辑）
    """
    all_actions = [None] * 5  # 5行行动槽
    reasons = [""] * 5
    
    magnet_present = has_magnet(context)
    lane_single_costs = []
    lane_single_actions = []

    # -------------------------------------------------------------
    # 第一步：预估5路常规单破方案并严格执行“一般ban铁器”
    # -------------------------------------------------------------
    for row in range(5):
        base_actions = calculate_best_zombie_for_lane(context, row)
        filtered_actions = []
        
        for act in base_actions:
            # 核心新增逻辑：如果推荐的是铁桶(bucket)，因为血量悬殊，降级为【两个路障】打消耗
            if act.zombie == "bucket":
                filtered_actions.append(BreakAction(zombie="cone", row=row, count=1, note=f"R{row+1}: 铁桶降级，下第一只路障"))
                filtered_actions.append(BreakAction(zombie="cone", row=row, count=1, note=f"R{row+1}: 【等前一只死后】补第二只路障凑血量"))
            
            # 如果是其他铁器家族成员 (梯子、矿工、橄榄)，由于Ban位或磁力菇降级为单个路障
            elif act.zombie in ["ladder", "miner", "football"]:
                filtered_actions.append(BreakAction(zombie="cone", row=row, count=1, note=f"R{row+1}: 规避铁器被吸/常规Ban，降级为单路障"))
                
            elif act.zombie == "slow":
                # 泛指慢速转换为具体路障
                filtered_actions.append(BreakAction(zombie="cone", row=row, count=1, note=f"R{row+1}: 转换慢速为具体路障"))
                
            else:
                filtered_actions.append(act)
        
        # 估算过滤后的开销（用于辅助第二步的舞王全局大局观判定）
        cost = 0
        for act in filtered_actions:
            if act.zombie == "cone" or act.zombie == "pole": 
                cost += 75  # 路障/撑杆花费 75
            else: 
                cost += 150 # 其他高级僵尸基础线
                
        lane_single_costs.append(cost)
        lane_single_actions.append(filtered_actions)

    # -------------------------------------------------------------
    # 第二步：舞王全局扫描（存在连续三路高花费时，只接受在中间路下舞王）
    # -------------------------------------------------------------
    dance_group_fixed = False
    
    # 扫描连续三行的三种可能组合: (0,1,2), (1,2,3), (2,3,4)
    for start_row in range(3):
        r1, r2, r3 = start_row, start_row + 1, start_row + 2
        
        # 条件 1：连续三路的单破花费均 > 舞王花费(350)
        if lane_single_costs[r1] > DANCER_COST and lane_single_costs[r2] > DANCER_COST and lane_single_costs[r3] > DANCER_COST:
            
            # 严格约束：只允许将舞王下在中间行 (即 r2)
            target_row = r2 
            plants = get_row_plants(context, target_row)
            total_output = count_outputs(plants)
            
            can_dance, dance_type = check_dance_lane_rules(plants, total_output)
            
            # 条件 2：只有当中间行本身也完美符合放舞王的环境时，才执行舞王策略
            if can_dance:
                display_row = target_row + 1
                dance_actions = []
                
                if dance_type == "single":
                    dance_actions.append(BreakAction(zombie="dancer", row=target_row, count=1, note=f"R{display_row}: 连续3路高开销，在中间路单放舞王"))
                    reasons[target_row] = f"R{display_row}: 连续高压中间路单下舞王"
                elif dance_type == "cone":
                    dance_actions.append(BreakAction(zombie="cone", row=target_row, count=1, note=f"R{display_row}: 3输出特殊情况，先下【路障】垫刀"))
                    dance_actions.append(BreakAction(zombie="dancer", row=target_row, count=1, note=f"R{display_row}: 确认路障死亡，补放舞王"))
                    reasons[target_row] = f"R{display_row}: 连续高压中间路路障+舞王"
                
                all_actions[target_row] = dance_actions
                
                # 上下两路成功被伴舞接管，单路动作清空
                for accomplice_row in [r1, r3]:
                    all_actions[accomplice_row] = []
                    reasons[accomplice_row] = f"R{accomplice_row+1}: 已被第 {display_row} 行舞王的伴舞自动收割"
                
                dance_group_fixed = True
                break # 成功部署战术舞王，退出扫描
                
    # -------------------------------------------------------------
    # 第三步：常规逐行审查（针对未被舞王战术覆盖的行）
    # -------------------------------------------------------------
    for row in range(5):
        if all_actions[row] is not None:
            continue  # 跳过已被中间路舞王协同覆盖的行
            
        plants = get_row_plants(context, row)
        total_output = count_outputs(plants)
        display_row = row + 1
        
        back_3_plants = plants[2:5]
        back_3_outputs = sum(1 for p in back_3_plants if p in ['fume_shroom', 'puff_shroom'])

        # 规则 2：5路单输出不赌小鬼，统一下路障 
        if total_output == 1:
            all_actions[row] = [BreakAction(zombie="cone", row=row, count=1, note=f"R{display_row}: 单输出不赌小鬼，下【路障】稳过")]
            reasons[row] = f"R{display_row}: 单输出下路障"
            continue

        # 规则 4：前三列全是顶配大喷菇 (数量 >= 3) 极端火力情况
        front_3_plants = plants[0:3]
        if front_3_plants.count('fume_shroom') >= 3:
            if not magnet_present:
                # 特例：虽然常规ban铁器，但如果没有磁力菇，允许放矿工(miner)打穿地道
                all_actions[row] = [BreakAction(zombie="miner", row=row, count=1, note=f"R{display_row}: 火力离谱且无磁力菇，解禁地底【矿工】")]
                reasons[row] = f"R{display_row}: 极端高压放矿工"
            else:
                # 有磁力菇时铁器瘫痪，由于火力极猛，使用高血量高级铁器家族【铁桶】作为纯肉盾吸收伤害
                all_actions[row] = [
                    BreakAction(zombie="bucket", row=row, count=1, note=f"R{display_row}: 极端火力有磁力，下第一只【铁桶】吃伤害"),
                    BreakAction(zombie="bucket", row=row, count=1, note=f"R{display_row}: 【确认前一只死亡】补第二只【铁桶】")
                ]
                reasons[row] = f"R{display_row}: 极端高压磁力阵顶铁桶"
            continue

        # 规则 3：后排输出较高 -> 路障垫刀(吃4/3列) + 撑杆冲刺 
        if back_3_outputs >= 2:
            all_actions[row] = [
                BreakAction(zombie="cone", row=row, count=1, note=f"R{display_row}: 后排输出高，放【路障】进去吃掉四/三列"),
                BreakAction(zombie="pole", row=row, count=1, note=f"R{display_row}: 【确认路障死后】补放【撑杆】起跳冲刺")
            ]
            reasons[row] = f"R{display_row}: 路障垫刀+撑杆"
            continue

        # 默认兜底：采用第一步中计算好、且处理了铁桶降级为双路障的常规单破安全方案
        all_actions[row] = lane_single_actions[row]
        reasons[row] = f"R{display_row}: 常规安全单破"

    # -------------------------------------------------------------
    # 第四步：输出打包
    # -------------------------------------------------------------
    final_actions = []
    for act_list in all_actions:
        if act_list:
            final_actions.extend(act_list)

    return BreakPlan(
        theme=THEME_NAME,
        actions=final_actions,
        confidence=0.96,
        reason="穿刺阵最新细分策略: " + " | ".join(filter(None, reasons))
    )