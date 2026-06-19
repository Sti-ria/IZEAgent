# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import List

# 保证项目根路径导入正确
_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parents[1] if len(_THIS_FILE.parents) >= 2 else Path.cwd()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 导入现有的底层算血内核
try:
    from core.ize_blood_calculator import (
        IZEBloodCalculator,
        explain_pole,
        format_result_table,
    )
except ModuleNotFoundError:
    sys.path.insert(0, str(_THIS_FILE.parent))
    from ize_blood_calculator import (
        IZEBloodCalculator,
        explain_pole,
        format_result_table,
    )

# ==============================================================================
# 🛠️ 核心重构：灰烬感知单破花费计算器（完整左侧火力模拟版）
# ==============================================================================
class AshAwareBloodCalculator:
    """
    自适应灰烬植物单破计算器。
    模拟反复派遣单一僵尸解决最右侧灰烬的过程。计算时保留左侧全部植物以保留真实DPS输出。
    """
    def __init__(self, base_calculator: IZEBloodCalculator):
        self.base_calculator = base_calculator
        self.ash_types = {'potatomine', 'squash', 'chomper'}
        self.spike_plants = {'spikeweed', 'spikerock'}
        # 所有具备主动攻击/射击能力的输出植物集合
        self.attack_plants = {
            'peashooter', 'repeater', 'snowpea', 'fumeshroom', 'puffshroom', 
            'starfruit', 'kernelpult', 'splitpea'
        }

    def _clean_lane(self, lane: List[str]) -> List[str]:
        return [str(p).replace('_', '').lower().strip() for p in lane]

    def calculate_lane(self, lane: List[str], explain: bool = False) -> dict:
        cleaned = self._clean_lane(lane)
        
        sacrifice_cost = 0
        sacrifice_zombies = []
        current_lane = list(cleaned)
        
        # 1. 步进式排雷循环
        while True:
            ash_idx = -1
            for i in range(4, -1, -1):
                if current_lane[i] in self.ash_types:
                    ash_idx = i
                    break
                    
            if ash_idx == -1:
                break
                
            # --- 判定派遣什么僵尸去填这个灰烬 ---
            has_no_attack = not any(p in self.attack_plants for p in current_lane)
            spike_count_right = sum(1 for p in current_lane[ash_idx + 1:] if p in self.spike_plants)
            
            if has_no_attack and spike_count_right <= 1:
                zombie = "imp"
                cost = 50
            else:
                res = self.base_calculator.calculate_lane(current_lane)
                
                # 安全提取原生算血器的开销，防止非整型干扰
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
            sacrifice_zombies.append(zombie)
            
            # --- 状态转移 ---
            for i in range(ash_idx + 1, 5):
                if current_lane[i] not in self.spike_plants:
                    current_lane[i] = 'empty'
                    
            if current_lane[ash_idx] in {'potatomine', 'squash'}:
                current_lane[ash_idx] = 'empty'
            elif current_lane[ash_idx] == 'chomper':
                current_lane[ash_idx] = 'sunflower'

        # 2. 吃脑收尾阶段
        final_res = self.base_calculator.calculate_lane(current_lane)
        
        # 3. 整合组装结果字典 (★ 引入核心类型防御，解决 int + list 报错)
        total_costs = {}
        for mode, cost_val in final_res.items():
            if isinstance(cost_val, (int, float)):
                # 标准整型花费，直接相加
                total_costs[mode] = sacrifice_cost + cost_val
            elif isinstance(cost_val, list):
                # 如果是列表，检查其内部是否为纯数字（比如某些算血器变体返回的花费序列）
                if cost_val and all(isinstance(c, (int, float)) for c in cost_val):
                    total_costs[mode] = [sacrifice_cost + c for c in cost_val]
                else:
                    # 如果是行动动作、僵尸名称等非数值列表，直接原样保留，不参与相加
                    total_costs[mode] = cost_val
            else:
                # 字符串或其他类型，原样保留
                total_costs[mode] = cost_val
            
        if "slow" not in total_costs or not isinstance(total_costs["slow"], (int, float)):
            total_costs["slow"] = sacrifice_cost + 250
            
        total_costs["_sacrifices"] = sacrifice_zombies
        total_costs["_sacrifice_cost"] = sacrifice_cost
        
        return total_costs


# ==============================================================================
# 🎮 CLI 调试主入口
# ==============================================================================
DEFAULT_BOARD = [
    ["empty", "empty", "empty", "empty", "empty"],
    ["peashooter", "empty", "empty", "empty", "empty"],
    ["snowpea", "repeater", "wallnut", "empty", "puffshroom"],
    ["sunflower", "squash", "squash", "fumeshroom", "puffshroom"],  # 测试行
    ["potatomine", "chomper", "chomper", "magnetshroom", "umbrellaleaf"],
]

def parse_lane(text: str) -> List[str]:
    return [part.strip() for part in text.split(",") if part.strip() != ""]

def parse_board(text: str) -> List[List[str]]:
    rows = []
    for row_text in text.split(";"):
        row = parse_lane(row_text)
        if row:
            rows.append(row)
    return rows

def main() -> int:
    parser = argparse.ArgumentParser(description="Debug Ash-Aware IZE blood calculator.")
    parser.add_argument("--lane", type=str, default=None)
    parser.add_argument("--board", type=str, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-status", action="store_true")
    
    args = parser.parse_args()

    native_calculator = IZEBloodCalculator(use_modified_pole=True)
    ash_calculator = AshAwareBloodCalculator(native_calculator)

    if args.lane:
        lane = parse_lane(args.lane)
        results = [ash_calculator.calculate_lane(lane)]
    elif args.board:
        board = parse_board(args.board)
        results = ash_calculator.calculate_board(board)
    else:
        results = ash_calculator.calculate_board(DEFAULT_BOARD)

    if args.json:
        print(json.dumps(results[0] if args.lane else results, ensure_ascii=False, indent=2))
    else:
        print(format_result_table(results, no_status=args.no_status))

    return 0

if __name__ == "__main__":
    raise SystemExit(main())