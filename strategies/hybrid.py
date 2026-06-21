# -*- coding: utf-8 -*-
from core.breaker_types import BreakAction, BreakContext, BreakPlan
import itertools

# 动态引入原生算血器
try:
    from core.ize_blood_calculator import IZEBloodCalculator
except ImportError:
    from ize_blood_calculator import IZEBloodCalculator

THEME_NAME = "综合"

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

# ==============================================================================
# 阶段 1：磁力菇微观精细仿真与清除判断
# ==============================================================================

def simulate_lane_to_magnet(lane: list[str], zombie_type: str, count: int = 1) -> bool:
    """
    遵循规则 4.1：仿真单只或多只僵尸推进至磁力菇并成功将其吃掉/清除的过程
    """
    if 'magnetshroom' not in lane:
        return True
    magnet_idx = lane.index('magnetshroom')
    
    if zombie_type == 'cone':
        base_hp = 640
        is_pole = False
    elif zombie_type == 'pole':
        base_hp = 500
        is_pole = True
    else:
        base_hp = 270
        is_pole = False
        
    total_hp = base_hp * count
    is_chilled = 'snowpea' in lane
    has_jumped = False
    
    # 从右侧（第5列，索引4）向左推进至磁力菇所在列
    for c in range(4, magnet_idx - 1, -1):
        plant = lane[c]
        
        # 计算当前列所承受的这一路所有左侧射手的总 DPS
        dps = 0
        for idx, p in enumerate(lane):
            if p == 'peashooter' and idx <= c:
                dps += 20
            elif p == 'repeater' and idx <= c:
                dps += 40
            elif p == 'snowpea' and idx <= c:
                dps += 20
            elif p == 'threepeater' and idx <= c:
                dps += 20
            elif p == 'starfruit' and idx <= c:
                dps += 20
            elif p == 'puffshroom' and idx <= c and c <= idx + 2:
                dps += 20
            elif p == 'fumeshroom' and idx <= c and c <= idx + 3:
                dps += 20

        # 行进时间计算
        if is_pole and not has_jumped:
            time_to_cross = 2.25  # 撑杆起跳前双倍语速
        else:
            time_to_cross = 9.0 if is_chilled else 4.5
            
        # 扣除行进间伤害
        total_hp -= dps * time_to_cross
        
        # 遵循规则 4.1：地刺伤害乘以 n
        if plant == 'spikeweed':
            total_hp -= 40 * count
            
        if total_hp <= 0:
            return False
            
        # 接触植物事件处理（啃咬或起跳）
        if plant != 'empty' and plant != 'spikeweed':
            if is_pole and not has_jumped:
                has_jumped = True
                if plant == 'magnetshroom':
                    return total_hp > 0
            else:
                plant_hp = 4000 if plant == 'wallnut' else 300
                eating_time = plant_hp / (100 * count)  # n只僵尸合力啃咬
                total_hp -= dps * eating_time
                
                if total_hp <= 0:
                    return False
                if plant == 'magnetshroom':
                    return total_hp > 0
                    
    return total_hp > 0

def can_bungee_magnet(board: list[list[str]], row: int, lane_plants: list[str]) -> bool:
    """
    遵循规则 3：判断飞贼是否可以飞掉磁力菇
    条件：3x3无叶子伞，左侧非窝瓜/大嘴花，右侧非窝瓜
    """
    if 'magnetshroom' not in lane_plants:
        return False
    magnet_idx = lane_plants.index('magnetshroom')
    
    # 1. 3x3 范围叶子伞检测
    for r in range(max(0, row - 1), min(5, row + 2)):
        for c in range(max(0, magnet_idx - 1), min(5, magnet_idx + 2)):
            p_clean = str(board[r][c]).replace('_', '').lower().strip() if board[r][c] else ""
            if p_clean == 'umbrellaleaf':
                return False
                
    # 2. 左侧植物审查
    if magnet_idx > 0:
        left_p = lane_plants[magnet_idx - 1]
        if left_p in ['squash', 'chomper']:
            return False
            
    # 3. 右侧植物审查
    if magnet_idx < 4:
        right_p = lane_plants[magnet_idx + 1]
        if right_p == 'squash':
            return False
            
    return True

def find_rightmost_ash(lane: list[str]) -> int:
    """从右向左寻找第一个遇到的灰烬植物索引"""
    for i in range(4, -1, -1):
        if lane[i] in ['potatomine', 'squash', 'chomper']:
            return i
    return -1

def clear_magnet_shroom_lane(board: list[list[str]], row: int, plants: list[str]) -> list[BreakAction]:
    """
    阶段 1 核心循环：针对单路磁力菇动态推演清障动作流
    """
    lane_actions = []
    current_plants = list(plants)
    display_row = row + 1
    
    while True:
        if 'magnetshroom' not in current_plants:
            break
            
        if simulate_lane_to_magnet(current_plants, 'pole', 1):
            lane_actions.append(BreakAction(zombie='pole', row=row, count=1, note=f"R{display_row}: 单撑杆清除磁力菇"))
            break
        if simulate_lane_to_magnet(current_plants, 'cone', 1):
            lane_actions.append(BreakAction(zombie='cone', row=row, count=1, note=f"R{display_row}: 单路障清除磁力菇"))
            break
            
        if can_bungee_magnet(board, row, current_plants):
            lane_actions.append(BreakAction(zombie='bungee', row=row, count=1, note=f"R{display_row}: 飞贼偷取磁力菇"))
            break
            
        ash_idx = find_rightmost_ash(current_plants)
        if ash_idx != -1:
            ash_name = current_plants[ash_idx]
            lane_actions.append(BreakAction(zombie='imp', row=row, count=1, note=f"R{display_row}: 派遣小鬼消耗灰烬【{ash_name}】"))
            if ash_name in ['potatomine', 'squash']:
                current_plants[ash_idx] = 'empty'
            elif ash_name == 'chomper':
                current_plants[ash_idx] = 'sunflower'
            continue
        else:
            found_multi = False
            for count in [2, 3]:
                if simulate_lane_to_magnet(current_plants, 'pole', count):
                    lane_actions.append(BreakAction(zombie='pole', row=row, count=count, note=f"R{display_row}: {count}撑杆强破磁力菇"))
                    found_multi = True
                    break
                if simulate_lane_to_magnet(current_plants, 'cone', count):
                    lane_actions.append(BreakAction(zombie='cone', row=row, count=count, note=f"R{display_row}: {count}路障强破磁力菇"))
                    found_multi = True
                    break
            if found_multi:
                break
            else:
                lane_actions.append(BreakAction(zombie='cone', row=row, count=3, note=f"R{display_row}: 极端防线保底投送3路障"))
                break
                
    return lane_actions

# ==============================================================================
# 阶段 2 & 3：单破候选精细决算（已重构融入灰烬感知排雷流）
# ==============================================================================

def evaluate_hybrid_single_lane(calculator: IZEBloodCalculator, lane: list[str], row: int) -> tuple[list[BreakAction], int]:
    """
    分路单破最优化器：
    1. 反复解决最靠右的灰烬植物直至这一行中没有灰烬植物（参考 AshAware 决策链）
    2. 针对除雷干净后的平真空行，穷举评测 8 种高精细单破候选组合，挑选出开销最低的方案。
    """
    display_row = row + 1
    
    ash_actions = []
    sacrifice_cost = 0
    current_lane = list(lane)
    
    ash_types = {'potatomine', 'squash', 'chomper'}
    spike_plants = {'spikeweed', 'spikerock'}
    attack_plants = {
        'peashooter', 'repeater', 'snowpea', 'fumeshroom', 'puffshroom', 
        'starfruit', 'kernelpult', 'splitpea', 'threepeater'
    }
    
    # --------------------------------------------------------------------------
    # 核心新增：步进式排雷循环（直至无灰烬植物）
    # --------------------------------------------------------------------------
    while True:
        ash_idx = -1
        for i in range(4, -1, -1):
            if current_lane[i] in ash_types:
                ash_idx = i
                break
                
        if ash_idx == -1:
            break  # 行内已无灰烬植物，跳出循环
            
        # 判定派遣什么僵尸去填/排这个灰烬
        has_no_attack = not any(p in attack_plants for p in current_lane)
        spike_count_right = sum(1 for p in current_lane[ash_idx + 1:] if p in spike_plants)
        
        if has_no_attack and spike_count_right <= 1:
            zombie = "imp"
            cost = 50
        else:
            res = calculator.calculate_lane(current_lane)
            
            def get_safe_cost(mode_key: str) -> int:
                val = res.get(mode_key, 999)
                if isinstance(val, (int, float)):
                    return int(val)
                if isinstance(val, list) and val and isinstance(val[0], (int, float)):
                    return int(val[0])
                return 999

            slow_c = get_safe_cost("slow")
            ladder_c = get_safe_cost("ladder")
            football_c = get_safe_cost("football")
            
            min_cost = min(slow_c, ladder_c, football_c)
            
            if min_cost == slow_c:
                if min_cost < 125:
                    zombie = "cone"
                elif min_cost < 175:
                    zombie = "bucket"
                else:
                    zombie = "football"
            elif min_cost == ladder_c:
                zombie = "ladder"
            else:
                zombie = "football"
            cost = min_cost
            
        sacrifice_cost += cost
        ash_actions.append(BreakAction(zombie=zombie, row=row, count=1, note=f"R{display_row}: 排雷派遣 {zombie}"))
        
        # 状态转移
        for i in range(ash_idx + 1, 5):
            if current_lane[i] not in spike_plants:
                current_lane[i] = 'empty'
                
        if current_lane[ash_idx] in {'potatomine', 'squash'}:
            current_lane[ash_idx] = 'empty'
        elif current_lane[ash_idx] == 'chomper':
            current_lane[ash_idx] = 'sunflower'

    # --------------------------------------------------------------------------
    # 核心衔接：基于除雷后的全新 current_lane 状态，依次考虑 8 种单破组合
    # --------------------------------------------------------------------------
    cost_dict = calculator.calculate_lane(current_lane)
    candidates = []
    
    # 候选 1：单撑杆 (75)
    if cost_dict.get('pole', 999) <= 75:
        candidates.append((75, [BreakAction(zombie='pole', row=row, count=1, note=f"R{display_row}: 单撑杆单破")]))
        
    # 候选 2：单路障 (75)
    if cost_dict.get('slow', 999) <= 75:
        candidates.append((75, [BreakAction(zombie='cone', row=row, count=1, note=f"R{display_row}: 单路障单破")]))
        
    # 候选 3：单铁桶 (125)
    if cost_dict.get('slow', 999) <= 125:
        candidates.append((125, [BreakAction(zombie='bucket', row=row, count=1, note=f"R{display_row}: 单铁桶单破")]))
        
    # 候选 4：单扶梯 (125)
    if cost_dict.get('ladder', 999) <= 125:
        candidates.append((125, [BreakAction(zombie='ladder', row=row, count=1, note=f"R{display_row}: 单扶梯单破")]))
        
    # 候选 7：单橄榄 (175)
    if cost_dict.get('football', 999) <= 175:
        candidates.append((175, [BreakAction(zombie='football', row=row, count=1, note=f"R{display_row}: 单橄榄单破")]))
        
    # 候选 8：扶梯 + 撑杆 (200)
    if cost_dict.get('ladder', 999) <= 200 or cost_dict.get('pole', 999) <= 200:
        candidates.append((200, [
            BreakAction(zombie='ladder', row=row, count=1, note=f"R{display_row}: 扶梯前置铺路"),
            BreakAction(zombie='pole', row=row, count=1, note=f"R{display_row}: 撑杆突击吃脑")
        ]))
        
    # 核心限制锁：下矿工时战线上不能包含杨桃或残留未爆的土豆雷
    has_miner_ban_plant = 'starfruit' in current_lane or 'potatomine' in current_lane
    
    # 候选 5：矿工 + 小鬼 (225)
    if not has_miner_ban_plant and 'splitpea' not in current_lane:
        candidates.append((225, [
            BreakAction(zombie='miner', row=row, count=1, note=f"R{display_row}: 矿工挖后单破"),
            BreakAction(zombie='imp', row=row, count=1, note=f"R{display_row}: 小鬼垫后吃脑")
        ]))
        
    # 候选 6：矿工 + 路障 (250)
    if not has_miner_ban_plant:
        candidates.append((250, [
            BreakAction(zombie='miner', row=row, count=1, note=f"R{display_row}: 矿工挖后干扰"),
            BreakAction(zombie='cone', row=row, count=1, note=f"R{display_row}: 路障正面平推")
        ]))
    print(candidates)

    # 保底自适应降级兜底
    if not candidates:
        min_c = 999
        best_m = 'slow'
        for m in ['slow', 'ladder', 'football']:
            val = cost_dict.get(m, 999)
            if isinstance(val, list) and val:
                val = val[0]
            if not isinstance(val, (int, float)):
                val = 999
            if val < min_c:
                min_c = val
                best_m = m
                
        if best_m == 'slow':
            z = 'bucket' if min_c >= 125 else 'cone'
            break_actions = [BreakAction(zombie=z, row=row, count=1, note=f"R{display_row}: {z}保底单破")]
            final_cost = min_c
        elif best_m == 'ladder':
            break_actions = [BreakAction(zombie='ladder', row=row, count=1, note=f"R{display_row}: 扶梯保底单破")]
            final_cost = min_c
        else:
            break_actions = [BreakAction(zombie='football', row=row, count=1, note=f"R{display_row}: 橄榄保底单破")]
            final_cost = min_c
    else:
        candidates.sort(key=lambda x: x[0])
        final_cost = candidates[0][0]
        break_actions = candidates[0][1]

    # 总动作流 = 前置排雷动作集 + 后续单破突防动作集
    # 总阳光开销 = 排雷开销 + 组合突防开销
    return ash_actions + break_actions, sacrifice_cost + final_cost

# ==============================================================================
# 核心入口决策控制逻辑
# ==============================================================================

def solve(context: BreakContext) -> BreakPlan:
    """
    综合主题核心解算器：严格分阶段推进执行
    """
    calculator = IZEBloodCalculator(use_modified_pole=True)
    lane_plants = [get_row_plants(context, r) for r in range(5)]
    
    # --------------------------------------------------------------------------
    # 阶段 1：全局磁力菇拦截检测
    # --------------------------------------------------------------------------
    has_any_magnet = any('magnetshroom' in lane_plants[r] for r in range(5))
    if has_any_magnet:
        stage1_actions = []
        for r in range(5):
            if 'magnetshroom' in lane_plants[r]:
                actions = clear_magnet_shroom_lane(context.board_5x5, r, lane_plants[r])
                stage1_actions.extend(actions)
        return BreakPlan(
            theme=THEME_NAME,
            actions=stage1_actions,
            confidence=0.99,
            reason="阶段 1：优先清除全场磁力菇防线危害"
        )

    # --------------------------------------------------------------------------
    # 阶段 2：准备单破三线(threepeater)和杨桃(starfruit)
    # --------------------------------------------------------------------------
    three_rows = [r for r in range(5) if 'threepeater' in lane_plants[r]]
    star_rows = [r for r in range(5) if 'starfruit' in lane_plants[r]]
    
    if three_rows or star_rows:
        stage2_rows = []
        same_rows = list(set(three_rows) & set(star_rows))
        other_three = [r for r in three_rows if r not in same_rows]
        other_star = [r for r in star_rows if r not in same_rows]
        
        is_adjacent = False
        for t in three_rows:
            for s in star_rows:
                if abs(t - s) == 1:
                    is_adjacent = True
                    break
                    
        if same_rows:
            if is_adjacent:
                stage2_rows = same_rows + other_three + other_star
            else:
                stage2_rows = same_rows + other_star + other_three
        elif is_adjacent:
            stage2_rows = three_rows + star_rows
        else:
            stage2_rows = star_rows + three_rows
            
        stage2_actions = []
        for r in stage2_rows:
            acts, _ = evaluate_hybrid_single_lane(calculator, lane_plants[r], r)
            stage2_actions.extend(acts)
            
        return BreakPlan(
            theme=THEME_NAME,
            actions=stage2_actions,
            confidence=0.99,
            reason=f"阶段 2：拓扑优先单破火力威胁路（顺序行索引: {[idx+1 for idx in stage2_rows]}）"
        )

    # --------------------------------------------------------------------------
    # 阶段 3：全路独立平等单破
    # --------------------------------------------------------------------------
    stage3_actions = []
    for r in range(5):
        acts, _ = evaluate_hybrid_single_lane(calculator, lane_plants[r], r)
        stage3_actions.extend(acts)
        
    return BreakPlan(
        theme=THEME_NAME,
        actions=stage3_actions,
        confidence=0.99,
        reason="阶段 3：清障完毕，全真空行平行精细单破收脑"
    )