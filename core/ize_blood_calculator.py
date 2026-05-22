# -*- coding: utf-8 -*-
"""
IZE blood calculator for PVZAgent.

This module is a Python port of the core segmented calculation idea used by
Rottenham/ize-calculator, with one project-specific correction:

    Pole-vaulting zombie damage = pre-jump pole-running damage + legacy post-jump damage.

The pre-jump phase is calculated as football-speed walking damage up to 0.5 cell
before the first pole-jump target. This matches the modified mechanism discussed
for PVZAgent:
    - if the first jump target is in column 5, no pre-jump damage is added;
    - otherwise, add football-speed walk damage before the jump;
    - potato mine, squash and chomper are considered valid pole-jump targets;
    - normal non-pole modes keep the original converter behavior;
    - scaredy-shroom is treated as peashooter damage with single-lane ducking rules.

Coordinate convention:
    A lane has 5 cells, ordered from left to right in the IZE plant area:
        [col1, col2, col3, col4, col5]
    col5 is the rightmost cell, nearest the zombie entrance.

Public API:
    calc = IZEBloodCalculator()
    calc.calculate_lane(["snowpea", "repeater", "wallnut", "empty", "puffshroom"])
    calc.calculate_board(board_5x5_or_5x9)

The calculator only uses the first 5 columns of every lane.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union


# ---------------------------------------------------------------------------
# Plant constants copied from WP_test/pvzstruct.h
# ---------------------------------------------------------------------------

EMPTY = -1

WDSS_0 = 0      # peashooter / 豌豆射手
XRK_1 = 1       # sunflower / 向日葵
YTZD_2 = 2      # cherry bomb / 樱桃炸弹
JG_3 = 3        # wall-nut / 坚果
TDDL_4 = 4      # potato mine / 土豆雷
HBSS_5 = 5      # snow pea / 寒冰射手
DZH_6 = 6       # chomper / 大嘴花
SCSS_7 = 7      # repeater / 双发射手
XPG_8 = 8       # puff-shroom / 小喷菇
YGG_9 = 9       # sun-shroom / 阳光菇
DPG_10 = 10     # fume-shroom / 大喷菇
MBTSZ_11 = 11   # grave buster / 墓碑吞噬者
MHG_12 = 12     # hypno-shroom / 魅惑菇
DXG_13 = 13     # scaredy-shroom / 胆小菇
HBG_14 = 14     # ice-shroom / 寒冰菇
HMG_15 = 15     # doom-shroom / 毁灭菇
HY_16 = 16      # lily pad / 荷叶
WG_17 = 17      # squash / 窝瓜
SFSS_18 = 18    # threepeater / 三线射手
CRHZ_19 = 19    # tangle kelp / 缠绕海藻
HBLJ_20 = 20    # jalapeno / 火爆辣椒
DC_21 = 21      # spikeweed / 地刺
HJSZ_22 = 22    # torchwood / 火炬树桩
GJG_23 = 23     # tall-nut / 高坚果
SBG_24 = 24     # sea-shroom / 水兵菇
LDH_25 = 25     # plantern / 路灯花
XRZ_26 = 26     # cactus / 仙人掌
SYC_27 = 27     # blover / 三叶草
LJSS_28 = 28    # split pea / 裂荚射手
YT_29 = 29      # starfruit / 杨桃
NGT_30 = 30     # pumpkin / 南瓜头
CLG_31 = 31     # magnet-shroom / 磁力菇
JXCTS_32 = 32   # cabbage-pult / 卷心菜投手
HP_33 = 33      # flower pot / 花盆
YMTS_34 = 34    # kernel-pult / 玉米投手
KFD_35 = 35     # coffee bean / 咖啡豆
DS_36 = 36      # garlic / 大蒜
YZBHS_37 = 37   # umbrella leaf / 叶子保护伞
JZH_38 = 38     # marigold / 金盏花
XGTS_39 = 39    # melon-pult / 西瓜投手
JQSS_40 = 40    # gatling pea / 机枪射手
SZXRK_41 = 41   # twin sunflower / 双子向日葵
YYG_42 = 42     # gloom-shroom / 忧郁菇
XP_43 = 43      # cattail / 香蒲
BXGTS_44 = 44   # winter melon / 冰西瓜
XJC_45 = 45     # gold magnet / 吸金磁
DCW_46 = 46     # spikerock / 地刺王
YMJNP_47 = 47   # cob cannon / 玉米加农炮


# ---------------------------------------------------------------------------
# Modes and display labels
# ---------------------------------------------------------------------------

MODE_POLE = 0
MODE_SLOW = 1
MODE_LADDER = 2
MODE_FOOTBALL = 3
MODE_POLE_LADDER = 4

MODE_KEYS = ["pole", "slow", "ladder", "football", "pole_ladder"]
MODE_LABELS_ZH = {
    "pole": "撑杆",
    "slow": "慢速",
    "ladder": "梯子",
    "football": "橄榄",
    "pole_ladder": "撑杆梯子",
}

STATUS_NOT_RECOMMENDED = -1
STATUS_NORMAL = 0
STATUS_RECOMMENDED = 1

KERNAL_RATE = 0.61
SPAWN_TO_COL5_WALK_FACTOR = 0.5

# Scaredy-shroom / 胆小菇 single-lane approximation.
# It has peashooter-level damage, but stops shooting when a zombie enters
# the half-cell directly in front of it.  For the current project scope we
# only model ducking caused by the zombie breaking this same lane, not by
# zombies from other lanes.
SCAREDY_FRONT_HIDE_DISTANCE_CELLS = 0.5
SCAREDY_HIDE_RIGHT_BITE_MODES = {MODE_POLE}


# ---------------------------------------------------------------------------
# Label conversion
# ---------------------------------------------------------------------------

LABEL_TO_PLANT: Dict[str, int] = {
    "": EMPTY,
    "empty": EMPTY,
    "none": EMPTY,
    "null": EMPTY,
    "blank": EMPTY,
    "unknown": EMPTY,
    "grass": EMPTY,

    "peashooter": WDSS_0,
    "pea": WDSS_0,
    "sunflower": XRK_1,
    "cherrybomb": YTZD_2,
    "cherry_bomb": YTZD_2,
    "wallnut": JG_3,
    "wall_nut": JG_3,
    "wall-nut": JG_3,
    "potatomine": TDDL_4,
    "potato_mine": TDDL_4,
    "potato-mine": TDDL_4,
    "snowpea": HBSS_5,
    "snow_pea": HBSS_5,
    "snow-pea": HBSS_5,
    "chomper": DZH_6,
    "repeater": SCSS_7,
    "puffshroom": XPG_8,
    "puff_shroom": XPG_8,
    "puff-shroom": XPG_8,
    "sunshroom": YGG_9,
    "sun_shroom": YGG_9,
    "fumeshroom": DPG_10,
    "fume_shroom": DPG_10,
    "fume-shroom": DPG_10,
    "gravebuster": MBTSZ_11,
    "grave_buster": MBTSZ_11,
    "hypnoshroom": MHG_12,
    "hypno_shroom": MHG_12,
    "scaredyshroom": DXG_13,
    "scaredy_shroom": DXG_13,
    "iceshroom": HBG_14,
    "ice_shroom": HBG_14,
    "doomshroom": HMG_15,
    "doom_shroom": HMG_15,
    "lilypad": HY_16,
    "lily_pad": HY_16,
    "squash": WG_17,
    "threepeater": SFSS_18,
    "three_peater": SFSS_18,
    "tanglekelp": CRHZ_19,
    "tangle_kelp": CRHZ_19,
    "jalapeno": HBLJ_20,
    "spikeweed": DC_21,
    "torchwood": HJSZ_22,
    "tallnut": GJG_23,
    "tall_nut": GJG_23,
    "seashroom": SBG_24,
    "sea_shroom": SBG_24,
    "plantern": LDH_25,
    "cactus": XRZ_26,
    "blover": SYC_27,
    "splitpea": LJSS_28,
    "split_pea": LJSS_28,
    "starfruit": YT_29,
    "pumpkin": NGT_30,
    "magnetshroom": CLG_31,
    "magnet_shroom": CLG_31,
    "cabbagepult": JXCTS_32,
    "cabbage_pult": JXCTS_32,
    "flowerpot": HP_33,
    "flower_pot": HP_33,
    "kernelpult": YMTS_34,
    "kernel_pult": YMTS_34,
    "coffeebean": KFD_35,
    "coffee_bean": KFD_35,
    "garlic": DS_36,
    "umbrellaleaf": YZBHS_37,
    "umbrella_leaf": YZBHS_37,
    "marigold": JZH_38,
    "melonpult": XGTS_39,
    "melon_pult": XGTS_39,
    "gatlingpea": JQSS_40,
    "gatling_pea": JQSS_40,
    "twinsunflower": SZXRK_41,
    "twin_sunflower": SZXRK_41,
    "gloomshroom": YYG_42,
    "gloom_shroom": YYG_42,
    "cattail": XP_43,
    "wintermelon": BXGTS_44,
    "winter_melon": BXGTS_44,
    "goldmagnet": XJC_45,
    "gold_magnet": XJC_45,
    "spikerock": DCW_46,
    "cobcannon": YMJNP_47,
    "cob_cannon": YMJNP_47,
}

PLANT_TO_CANONICAL_LABEL: Dict[int, str] = {
    EMPTY: "empty",
    WDSS_0: "peashooter",
    XRK_1: "sunflower",
    YTZD_2: "cherrybomb",
    JG_3: "wallnut",
    TDDL_4: "potatomine",
    HBSS_5: "snowpea",
    DZH_6: "chomper",
    SCSS_7: "repeater",
    XPG_8: "puffshroom",
    YGG_9: "sunshroom",
    DPG_10: "fumeshroom",
    DXG_13: "scaredyshroom",
    WG_17: "squash",
    SFSS_18: "threepeater",
    DC_21: "spikeweed",
    HJSZ_22: "torchwood",
    LJSS_28: "splitpea",
    YT_29: "starfruit",
    CLG_31: "magnetshroom",
    YMTS_34: "kernelpult",
    YZBHS_37: "umbrellaleaf",
}

def walk_segment_factor(i: int) -> float:
    """
    walk[5] 表示从僵尸放置点到第 5 列前的距离。
    由于僵尸实际放置在第 6 格中间，所以这一段只算半格。
    """
    return SPAWN_TO_COL5_WALK_FACTOR if i == 5 else 1.0


def normalize_label(label: Union[str, int, None]) -> int:
    """Convert a PVZAgent label or raw PlantType integer into PlantType."""
    if label is None:
        return EMPTY
    if isinstance(label, int):
        return label

    text = str(label).strip().lower()
    text = text.replace(" ", "_")
    if text in LABEL_TO_PLANT:
        return LABEL_TO_PLANT[text]

    # Be forgiving with hyphen/underscore variations.
    alt = text.replace("-", "_")
    if alt in LABEL_TO_PLANT:
        return LABEL_TO_PLANT[alt]
    alt = text.replace("_", "")
    if alt in LABEL_TO_PLANT:
        return LABEL_TO_PLANT[alt]

    raise ValueError(f"Unknown plant label: {label!r}. Add it to LABEL_TO_PLANT if needed.")


def normalize_lane(lane: Sequence[Union[str, int, None]]) -> List[int]:
    """Return exactly 5 plant IDs. Extra columns are ignored and missing columns are padded empty."""
    result = [normalize_label(x) for x in list(lane)[:5]]
    while len(result) < 5:
        result.append(EMPTY)
    return result


def label_of(plant: int) -> str:
    return PLANT_TO_CANONICAL_LABEL.get(plant, f"plant_{plant}")


# ---------------------------------------------------------------------------
# Formula helpers
# ---------------------------------------------------------------------------

def cpp_round(x: float) -> int:
    """C++ std::round equivalent for non-negative values used by the calculator."""
    if x >= 0:
        return int(math.floor(x + 0.5))
    return int(math.ceil(x - 0.5))


def get_butter_rate(i: int) -> float:
    if i <= 0:
        return 1.0
    if i == 1:
        return 1.4665
    if i == 2:
        return 2.1467
    if i == 3:
        return 3.1419
    if i == 4:
        return 4.6022
    return 6.7470


def get_hs_fix(diff: int) -> float:
    if diff <= 0:
        return 0.0
    if diff == 1:
        return 0.2
    if diff == 2:
        return 0.4
    if diff == 3:
        return 0.5
    return 0.74


def is_empty(idx: int) -> bool:
    return idx == EMPTY or idx in {DC_21, TDDL_4, WG_17}


def is_bitable(idx: int) -> bool:
    return idx != EMPTY and idx not in {TDDL_4, WG_17, JG_3, DC_21}


def is_harmless(idx: int) -> bool:
    return idx in {HJSZ_22, CLG_31, YZBHS_37, XRK_1, DC_21, JG_3}


def is_pole_jump_target(idx: int) -> bool:
    """
    Project-specific pole target rule.

    For a single pole-vaulting zombie:
    - empty and spikeweed are not jump targets;
    - potato mine, squash and chomper ARE jump targets;
    - all other non-empty plants are jump targets.
    """
    return idx not in {EMPTY, DC_21}


def get_dps(idx: int) -> float:
    if idx in {WDSS_0, HBSS_5, SFSS_18, XPG_8, DXG_13}:
        return 2.0
    if idx in {SCSS_7, LJSS_28, YT_29}:
        return 4.0
    return 0.0


def get_fume_dps(idx: int) -> float:
    if idx == DPG_10:
        return 2.0
    if idx == DC_21:
        return 3.0
    if idx == YMTS_34:
        return 2.0 * KERNAL_RATE * get_butter_rate(1)
    return 0.0


@dataclass
class Pair:
    x: int
    y: int
    empty: bool = False


class Row:
    """One-lane segmented calculator."""

    def __init__(self, row: Sequence[int], mode: int, *, use_modified_pole: bool = True):
        self.raw_row: List[int] = normalize_lane(row)
        self.row: List[int] = list(self.raw_row)
        self.mode = mode
        self.use_modified_pole = use_modified_pole

        self.bite = [0.0] * 6
        self.walk = [0.0] * 6
        self.fume_bite = [0.0] * 6
        self.fume_walk = [0.0] * 6
        self.extra_bite = [0.0] * 6
        self.extra_walk = [0.0] * 6

        self.bite_slowed = [False] * 6
        self.walk_slowed = [False] * 6
        self.bite_fire = [False] * 6
        self.walk_fire = [False] * 6
        self.bite_butter = [0] * 6
        self.walk_butter = [0] * 6

        self.wallnuts = set()

        self.BITE_DPS = -1.0
        self.WALK_DPS = -1.0
        self.DC_PASSBY = -1.0
        self.DC_BLOCK = -1.0
        self.XPG_FIX = -1.0
        self.YT_DPS = -1.0

        self.bite_lmt = 5
        self.walk_lmt = 5
        self.can_pv = True
        self.HS_fix = 0.0

        self.pole_target_idx: Optional[int] = None
        self.pole_detail: Dict[str, Any] = {}

        if mode == MODE_POLE:
            self.BITE_DPS = 2.0
            self.WALK_DPS = 4.0
            self.XPG_FIX = 3.0
            self.DC_PASSBY = 5.0
            self.DC_BLOCK = 0.0
            self.YT_DPS = 5.0
            self.compute_pv()
        elif mode == MODE_SLOW:
            self.BITE_DPS = 2.0
            self.WALK_DPS = 4.0
            self.XPG_FIX = 3.0
            self.DC_PASSBY = 5.0
            self.DC_BLOCK = 3.0
            self.YT_DPS = 2.0
            self.walk_lmt = 5
            self.bite_lmt = 5
        elif mode == MODE_LADDER:
            self.BITE_DPS = 2.0
            self.WALK_DPS = 1.5
            self.XPG_FIX = 1.0
            self.DC_PASSBY = 2.0
            self.DC_BLOCK = 3.0
            self.YT_DPS = 2.0
            self.walk_lmt = 5
            self.bite_lmt = 5
        elif mode == MODE_FOOTBALL:
            self.BITE_DPS = 2.0
            self.WALK_DPS = 1.75
            self.XPG_FIX = 1.0
            self.DC_PASSBY = 3.0
            self.DC_BLOCK = 3.0
            self.YT_DPS = 5.0
            self.walk_lmt = 5
            self.bite_lmt = 5
        elif mode == MODE_POLE_LADDER:
            self.BITE_DPS = 2.0
            self.WALK_DPS = 1.5
            self.XPG_FIX = 1.0
            self.DC_PASSBY = 2.0
            self.DC_BLOCK = 3.0
            self.YT_DPS = 2.0
        else:
            raise ValueError(f"Unknown mode: {mode}")

    # ---------------------------------------------------------------------
    # Basic row helpers
    # ---------------------------------------------------------------------

    def has_magnet(self) -> bool:
        return self.index_of(CLG_31) != -1

    def get_star_num(self) -> int:
        return sum(1 for i in range(4) if self.row[i] == YT_29)

    def index_of(self, plant: int, lo: int = 0, hi: int = 4) -> int:
        lo = max(0, lo)
        hi = min(4, hi)
        for i in range(lo, hi + 1):
            if self.row[i] == plant:
                return i
        return -1

    def compute_pv(self) -> None:
        """Find pole-vaulting target and set post-jump calculation limits."""
        if self.use_modified_pole:
            iterable = ((i, self.raw_row[i]) for i in range(4, -1, -1))
            skip = lambda p: not is_pole_jump_target(p)
        else:
            # Legacy logic from original calculator: skip spikeweed, squash and empty.
            iterable = ((i, self.row[i]) for i in range(4, -1, -1))
            skip = lambda p: p in {DC_21, WG_17, EMPTY}

        for i, plant in iterable:
            if skip(plant):
                continue

            self.pole_target_idx = i

            if plant in {XRK_1, LJSS_28, YT_29}:
                self.can_pv = False

            self.bite_lmt = i
            self.walk_lmt = i - 1

            # Legacy torchwood bug fix.
            if plant == HJSZ_22 and i != 0:
                if self.row[i - 1] in {WDSS_0, HBSS_5, SCSS_7, LJSS_28}:
                    self.row[i - 1] = XRK_1
            return

        self.pole_target_idx = -1
        self.bite_lmt = -1
        self.walk_lmt = -1

    def convert(self) -> None:
        """
        Original simplification rules:
        - threepeater and split pea become peashooter;
        - magnet, umbrella leaf and chomper become sunflower-like harmless blockers;
        - potato mine and squash become empty.
        """
        for i in range(5):
            if self.row[i] in {SFSS_18, LJSS_28}:
                self.row[i] = WDSS_0
            if self.row[i] in {CLG_31, YZBHS_37, DZH_6}:
                self.row[i] = XRK_1
            if self.row[i] in {TDDL_4, WG_17}:
                self.row[i] = EMPTY

    # ---------------------------------------------------------------------
    # Plant contribution methods
    # ---------------------------------------------------------------------

    def add(self, dps: float, start: int) -> None:
        for i in range(start + 1, 6):
            if not is_empty(self.row[i - 1]):
                self.bite[i] += self.BITE_DPS * dps
        for i in range(start + 1, 5):
            self.walk[i] += self.WALK_DPS * dps
        self.walk[5] += dps

    def add_fume(self, dps: float, start: int) -> None:
        for i in range(start + 1, 6):
            if not is_empty(self.row[i - 1]):
                self.fume_bite[i] += self.BITE_DPS * dps
        for i in range(start + 1, 5):
            self.fume_walk[i] += self.WALK_DPS * dps
        self.fume_walk[5] += dps

    def add_hb(self, start: int) -> None:
        self.add(1.0, start)
        for i in range(start + 1, 6):
            self.bite_slowed[i] = True
            self.walk_slowed[i] = True
        # Delay speed-change correction.
        self.walk_slowed[5] = False

    def add_xpg(self, start: int) -> None:
        if self.mode in {MODE_POLE, MODE_FOOTBALL}:
            for i in range(start + 1, 6):
                if i > start + 4:
                    break
                if not is_empty(self.row[i - 1]):
                    self.bite[i] += self.BITE_DPS
            for i in range(start + 1, 5):
                if i <= start + 3:
                    self.walk[i] += self.WALK_DPS
                else:
                    break
            if start >= 2:
                self.walk[5] += 1.0
        else:
            for i in range(start + 1, 6):
                if i > start + 3:
                    break
                if not is_empty(self.row[i - 1]):
                    self.bite[i] += self.BITE_DPS
            for i in range(start + 1, 5):
                if i <= start + 2:
                    self.walk[i] += self.WALK_DPS
                elif i == start + 3:
                    self.walk[i] += self.XPG_FIX
                else:
                    break
            if start >= 2:
                self.walk[5] += 1.0

    def add_dpg(self, start: int) -> None:
        self.add_fume(1.0, start)
        if self.mode == MODE_LADDER:
            self.add_extra(start)

    def add_extra(self, start: int) -> None:
        for i in range(start + 1, 6):
            if not is_empty(self.row[i - 1]):
                self.extra_bite[i] += self.BITE_DPS
        for i in range(start + 1, 5):
            self.extra_walk[i] += self.WALK_DPS
        self.extra_walk[5] += 1.0

    def add_dc(self, start: int) -> None:
        self.fume_walk[start] += self.DC_PASSBY
        if start == 0 and self.mode != MODE_POLE:
            self.fume_bite[start] += self.DC_BLOCK - 1.0
        elif start > 0 and not is_empty(self.row[start - 1]) and self.mode != MODE_POLE:
            self.fume_bite[start] += self.DC_BLOCK

    def add_yt(self, start: int) -> None:
        self.bite[start + 1] += 2.0 * self.YT_DPS

    def add_ymts(self, start: int) -> None:
        for i in range(start + 1, 6):
            if not is_empty(self.row[i - 1]):
                self.fume_bite[i] += KERNAL_RATE * self.BITE_DPS
        for i in range(start + 1, 5):
            self.fume_walk[i] += KERNAL_RATE * self.WALK_DPS
        self.fume_walk[5] += KERNAL_RATE

        for i in range(start + 1, 6):
            self.bite_butter[i] += 1
            self.walk_butter[i] += 1

    def add_hs(self, start: int) -> None:
        pea_count = 0
        for i in range(start):
            diff = start - i
            if self.row[i] == WDSS_0:
                pea_count += 1
                if start == self.index_of(HJSZ_22):
                    self.HS_fix -= get_hs_fix(diff) * 2.0
            elif self.row[i] == SCSS_7:
                pea_count += 2
                if start == self.index_of(HJSZ_22):
                    self.HS_fix -= get_hs_fix(diff) * 4.0

        for i in range(start + 1, 6):
            self.bite_slowed[i] = False
            self.walk_slowed[i] = False
            if pea_count > 0:
                self.bite_fire[i] = True
                self.walk_fire[i] = True

        self.add(float(pea_count), start)

    def add_jg(self, start: int) -> None:
        self.wallnuts.add(start)

    def _scaredy_walk_contribution(self, walk_idx: int) -> float:
        """
        Return the raw contribution that one scaredy-shroom added to walk[walk_idx]
        before global segment-length scaling is applied.

        self.add(1.0, start) contributes:
        - WALK_DPS to walk[start + 1 .. 4];
        - 1.0 to walk[5].
        """
        if walk_idx == 5:
            return 1.0
        if 0 <= walk_idx <= 4:
            return self.WALK_DPS
        return 0.0

    def _scaredy_front_hide_fraction(self, walk_idx: int) -> float:
        """
        Fraction of the front walk segment during which scaredy-shroom ducks.

        Normal walk segments represent roughly 1 cell, so the last 0.5 cell is
        hidden.  walk[5] is already the spawn-to-col5 segment; in PVZAgent it is
        only half a cell, so a scaredy-shroom in col5 hides for that whole
        segment.
        """
        segment_len = walk_segment_factor(walk_idx)
        if segment_len <= 0:
            return 0.0
        return min(1.0, SCAREDY_FRONT_HIDE_DISTANCE_CELLS / segment_len)

    def add_scaredyshroom(self, start: int) -> None:
        """
        Add scaredy-shroom damage for the single-lane IZE blood calculator.

        Current rules:
        - Base damage is the same as peashooter: self.add(1.0, start).
        - When the zombie enters the half-cell in front of the scaredy-shroom,
          it ducks, so the front walk segment loses that fraction of damage.
        - Slow, ladder and football zombies do NOT make a scaredy-shroom in col i
          duck while biting a plant in col i+1.
        - A pole-vaulting zombie after losing its pole DOES make that scaredy-
          shroom duck while biting the plant in col i+1.

        Cross-lane zombies are intentionally ignored here.
        """
        self.add(1.0, start)

        # Front-half ducking while the zombie walks from the right-neighbour
        # cell toward this scaredy-shroom.
        walk_idx = start + 1
        if 0 <= walk_idx <= 5:
            contribution = self._scaredy_walk_contribution(walk_idx)
            hide_fraction = self._scaredy_front_hide_fraction(walk_idx)
            self.walk[walk_idx] -= contribution * hide_fraction

        # Special pole case: after losing its pole, the pole zombie's biting
        # position at the right-neighbour cell is close enough to make this
        # scaredy-shroom duck.  This is applied before wallnut multiplication,
        # so wallnut biting time will not accidentally include scaredy damage.
        right_col = start + 1
        bite_idx = start + 2
        if (
            self.mode in SCAREDY_HIDE_RIGHT_BITE_MODES
            and 0 <= right_col <= 4
            and 0 <= bite_idx <= 5
            and not is_empty(self.row[right_col])
        ):
            self.bite[bite_idx] -= self.BITE_DPS

    def fix_jg(self) -> None:
        for w in self.wallnuts:
            self.bite[w + 1] *= 14.0
            self.fume_bite[w + 1] *= 14.0

    def add_plants(self) -> None:
        for j in range(5):
            plant = self.row[j]
            if plant == WDSS_0:
                self.add(1.0, j)
            elif plant == HBSS_5:
                self.add_hb(j)
            elif plant == SCSS_7:
                self.add(2.0, j)
            elif plant == XPG_8:
                self.add_xpg(j)
            elif plant == DXG_13:
                self.add_scaredyshroom(j)
            elif plant == DPG_10:
                self.add_dpg(j)
            elif plant == DC_21:
                self.add_dc(j)
            elif plant == YT_29:
                self.add_yt(j)
            elif plant == YMTS_34:
                self.add_ymts(j)
            elif plant == HJSZ_22:
                self.add_hs(j)
            elif plant == JG_3:
                self.add_jg(j)
        self.fix_jg()

    # ---------------------------------------------------------------------
    # Damage segment helpers
    # ---------------------------------------------------------------------

    def build_hbfix(self, *, walk_lmt: Optional[int] = None, bite_lmt: Optional[int] = None, include_bite: bool = True) -> set:
        if walk_lmt is None:
            walk_lmt = self.walk_lmt
        if bite_lmt is None:
            bite_lmt = self.bite_lmt

        hbfix = set()
        for i in range(0, walk_lmt + 1):
            if i == 5:
                break
            a = not self.walk_slowed[i]
            b = self.walk_slowed[i + 1]
            c = self.bite_slowed[i + 1]
            if a and b:
                hbfix.add(i)
            elif include_bite and a and c:
                hbfix.add(i)
        return hbfix

    def calc_walk_segment_damage(self, i: int, hbfix: set, *, bite_lmt: Optional[int] = None) -> float:
        if bite_lmt is None:
            bite_lmt = self.bite_lmt

        walk_dps = self.walk[i] + self.fume_walk[i]

        if self.walk_slowed[i]:
            if self.walk_fire[i]:
                walk_dps *= 1.33
            else:
                walk_dps *= 2.0
        elif i in hbfix:
            if not self.walk_fire[i]:
                if self.mode == MODE_FOOTBALL:
                    walk_dps *= 2.0
                else:
                    walk_dps *= 1.875
        elif (i + 1) in hbfix:
            if (
                not self.walk_fire[i]
                and self.mode == MODE_FOOTBALL
                and i + 1 <= bite_lmt
                and self.bite[i + 1] + self.fume_bite[i + 1] == 0
            ):
                walk_dps *= 2.0

        walk_dps *= get_butter_rate(self.walk_butter[i])
        walk_dps *= walk_segment_factor(i)
        return walk_dps

    def compute_pole_prejump_damage(self) -> float:
        """
        Modified pole-vaulting pre-jump damage.

        First jump target in col5 -> no pre-jump damage.
        Otherwise use football mode to calculate walking damage before jumping.
        Because the zombie is placed at the middle of col6, walk[5] is globally
        scaled to half a cell by walk_segment_factor(5):
            target col4: 0.5 * walk[5] + 0.5 * walk[4]
            target col3: 0.5 * walk[5] + walk[4] + 0.5 * walk[3]
            ...
        """
        target = self.pole_target_idx
        if target is None or target == -1:
            return 0.0
        if target == 4:
            return 0.0

        pre = Row(self.raw_row, MODE_FOOTBALL, use_modified_pole=self.use_modified_pole)
        pre.convert()
        pre.add_plants()

        hbfix = pre.build_hbfix(walk_lmt=5, bite_lmt=5, include_bite=True)

        damage = 0.0

        # Full segments already passed before reaching the half-cell pre-jump point.
        for i in range(5, target + 1, -1):
            damage += pre.calc_walk_segment_damage(i, hbfix, bite_lmt=5)

        # Half of the segment immediately before the target plant.
        half_segment = target + 1
        damage += 0.5 * pre.calc_walk_segment_damage(half_segment, hbfix, bite_lmt=5)

        return damage

    # ---------------------------------------------------------------------
    # Main calculations
    # ---------------------------------------------------------------------

    def compute(self) -> int:
        self.convert()
        self.add_plants()

        torchwood = self.index_of(HJSZ_22)
        hbfix = self.build_hbfix(include_bite=True)

        total = 0.0

        # Legacy pole post-jump correction.
        if self.mode == MODE_POLE and self.bite_lmt >= 0:
            if self.bite_lmt - 1 >= 0 and self.row[self.bite_lmt - 1] == YT_29:
                self.bite[self.bite_lmt] += (self.bite[self.bite_lmt] - 10.0) * 0.25
                self.fume_bite[self.bite_lmt] *= 1.25
            elif self.bite_lmt - 1 >= 0 and self.row[self.bite_lmt - 1] == JG_3:
                self.bite[self.bite_lmt] += (self.bite[self.bite_lmt] / 14.0) * 0.25
                self.fume_bite[self.bite_lmt] *= 1.25
            else:
                self.bite[self.bite_lmt] *= 1.25
                self.fume_bite[self.bite_lmt] *= 1.25

        for i in range(0, self.bite_lmt + 1):
            bite_dps = self.bite[i] + self.fume_bite[i]
            if self.bite_slowed[i]:
                if self.bite_fire[i]:
                    bite_dps *= 1.33
                else:
                    bite_dps *= 2.0
            elif i in hbfix:
                if not self.bite_fire[i]:
                    if self.mode == MODE_FOOTBALL:
                        if (i - 1) in self.wallnuts:
                            bite_dps += bite_dps / 14.0 * 0.5
                        else:
                            bite_dps *= 1.5
            bite_dps *= get_butter_rate(self.bite_butter[i])
            if torchwood != -1 and i == torchwood + 1:
                bite_dps += self.HS_fix
            total += bite_dps

        for i in range(0, self.walk_lmt + 1):
            total += self.calc_walk_segment_damage(i, hbfix)

        postjump_raw = total
        prejump_raw = 0.0

        if self.mode == MODE_POLE and self.use_modified_pole:
            prejump_raw = self.compute_pole_prejump_damage()
            total += prejump_raw

        if self.mode == MODE_POLE:
            target = self.pole_target_idx
            self.pole_detail = {
                "use_modified_pole": self.use_modified_pole,
                "target_idx": target,
                "target_col_from_left": None if target is None or target < 0 else target + 1,
                "target_label": None if target is None or target < 0 else label_of(self.raw_row[target]),
                "can_pv": self.can_pv,
                "postjump_damage_raw": postjump_raw,
                "postjump_damage_rounded": cpp_round(postjump_raw),
                "prejump_damage_raw": prejump_raw,
                "prejump_damage_rounded": cpp_round(prejump_raw),
                "total_raw": total,
                "total": cpp_round(total),
            }

        return cpp_round(total)

    def compute_ladder(self) -> Pair:
        if self.mode == MODE_POLE_LADDER:
            if (not is_bitable(self.row[3])) or self.row[4] == JG_3 or is_empty(self.row[4]):
                return Pair(-1, -1, True)
            self.bite_lmt = 3
            self.walk_lmt = 3

        total = 0.0
        fume_total = 0.0

        if self.mode == MODE_POLE_LADDER:
            total += get_dps(self.row[4])
            fume_total += get_fume_dps(self.row[4])

        self.convert()
        self.add_plants()

        has_ladder = True
        wallnut = self.index_of(JG_3)
        torchwood = self.index_of(HJSZ_22)
        walk_on_wallnut = False
        ladder_lost = -1

        hbfix = self.build_hbfix(include_bite=False)

        # Damage area shifts left for ladder calculation.
        self.walk[5] = 0.0
        self.fume_walk[5] = 0.0
        self.extra_walk[5] = 0.0

        for i in range(5, -1, -1):
            # Walking damage
            if i <= self.walk_lmt:
                if walk_on_wallnut:
                    self.walk[i] *= 1.33
                    self.fume_walk[i] *= 1.33
                    walk_on_wallnut = False
                elif not has_ladder:
                    self.walk[i] *= 2.67
                    self.fume_walk[i] *= 2.67

                walk_dps = self.walk[i]
                if has_ladder:
                    walk_dps += self.extra_walk[i]

                walk_fume_dps = self.fume_walk[i]
                walk_dps *= get_butter_rate(self.walk_butter[i])
                walk_fume_dps *= get_butter_rate(self.walk_butter[i])

                offset = 0.0
                if has_ladder and total + walk_dps >= 25.0 and walk_dps != 0:
                    has_ladder_pct = (25.0 - total) / walk_dps
                    offset = (total + walk_dps - 25.0 - self.extra_walk[i] * (1.0 - has_ladder_pct)) * 2.67
                    walk_fume_dps += walk_fume_dps * (1.0 - has_ladder_pct) * 1.67
                    total = 25.0
                    walk_dps = 0.0
                    has_ladder = False
                    ladder_lost = i
                elif not has_ladder:
                    offset = walk_dps
                    walk_dps = 0.0

                if not has_ladder:
                    if self.walk_slowed[i]:
                        if self.walk_fire[i]:
                            offset *= 1.33
                            walk_fume_dps *= 1.33
                        else:
                            offset *= 2.0
                            walk_fume_dps *= 2.0
                    elif i in hbfix:
                        if not self.walk_fire[i] and ladder_lost < i + 2:
                            offset *= 1.875
                            walk_fume_dps *= 1.875
                    walk_fume_dps += offset

                total += walk_dps
                fume_total += walk_fume_dps

            # Biting damage
            if i <= self.bite_lmt:
                if wallnut != -1 and wallnut + 1 == i and has_ladder:
                    has_ladder = False
                    ladder_lost = i
                    walk_on_wallnut = True
                    continue

                bite_dps = self.bite[i]
                if has_ladder:
                    bite_dps += self.extra_bite[i]

                bite_fume_dps = self.fume_bite[i]
                bite_dps *= get_butter_rate(self.bite_butter[i])
                bite_fume_dps *= get_butter_rate(self.bite_butter[i])

                if torchwood != -1 and i == torchwood + 1:
                    bite_dps += self.HS_fix

                offset = 0.0
                if has_ladder and total + bite_dps >= 25.0 and bite_dps != 0:
                    has_ladder_pct = (25.0 - total) / bite_dps
                    offset = total + bite_dps - 25.0 - self.extra_bite[i] * (1.0 - has_ladder_pct)
                    total = 25.0
                    bite_dps = 0.0
                    has_ladder = False
                    ladder_lost = i
                elif not has_ladder:
                    offset = bite_dps
                    bite_dps = 0.0

                if not has_ladder:
                    if self.bite_slowed[i]:
                        if self.bite_fire[i]:
                            offset *= 1.33
                            bite_fume_dps *= 1.33
                        else:
                            offset *= 2.0
                            bite_fume_dps *= 2.0
                    bite_fume_dps += offset

                total += bite_dps
                fume_total += bite_fume_dps

        return Pair(cpp_round(total), cpp_round(fume_total), False)


class IZEBloodCalculator:
    """High-level API used by PVZAgent."""

    def __init__(self, *, use_modified_pole: bool = True, check_all_starfruit: bool = False):
        self.use_modified_pole = use_modified_pole
        self.check_all_starfruit = check_all_starfruit

    def calculate_lane(self, lane: Sequence[Union[str, int, None]], *, explain: bool = False) -> Dict[str, Any]:
        row = normalize_lane(lane)
        values: Dict[str, Union[int, str]] = {}
        status: Dict[str, int] = {key: STATUS_NORMAL for key in MODE_KEYS}
        details: Dict[str, Any] = {}

        has_highlight = False

        # Pole-vaulting
        r0 = Row(row, MODE_POLE, use_modified_pole=self.use_modified_pole)
        has_magnet = r0.has_magnet()
        pole_value = r0.compute()
        values["pole"] = pole_value
        if (not r0.can_pv) or pole_value > 39:
            status["pole"] = STATUS_NOT_RECOMMENDED
        elif pole_value <= 15:
            status["pole"] = STATUS_RECOMMENDED
            has_highlight = True
        if explain:
            details["pole"] = dict(r0.pole_detail)

        # Slow
        r1 = Row(row, MODE_SLOW, use_modified_pole=self.use_modified_pole)
        slow_value = r1.compute()
        values["slow"] = slow_value
        if not has_highlight:
            if slow_value <= 25:
                status["slow"] = STATUS_RECOMMENDED
                has_highlight = True
            elif slow_value <= 61 and not has_magnet:
                status["slow"] = STATUS_RECOMMENDED
                has_highlight = True
        if slow_value > 72:
            status["slow"] = STATUS_NOT_RECOMMENDED

        # Ladder
        r2 = Row(row, MODE_LADDER, use_modified_pole=self.use_modified_pole)
        ladder_pair = r2.compute_ladder()
        values["ladder"] = f"{ladder_pair.x}+{ladder_pair.y}"
        if not has_highlight:
            if ladder_pair.y <= 14 and not has_magnet:
                status["ladder"] = STATUS_RECOMMENDED
                has_highlight = True
        if has_magnet or ladder_pair.y >= 19:
            status["ladder"] = STATUS_NOT_RECOMMENDED

        # Football
        r3 = Row(row, MODE_FOOTBALL, use_modified_pole=self.use_modified_pole)
        football_value = r3.compute()
        values["football"] = football_value
        if not has_highlight:
            if football_value <= 76 and not has_magnet:
                status["football"] = STATUS_RECOMMENDED
                has_highlight = True
        if football_value > 84 or has_magnet:
            status["football"] = STATUS_NOT_RECOMMENDED

        # Pole + ladder
        r4 = Row(row, MODE_POLE_LADDER, use_modified_pole=self.use_modified_pole)
        pole_ladder_pair = r4.compute_ladder()
        if pole_ladder_pair.empty:
            values["pole_ladder"] = ""
            status["pole_ladder"] = STATUS_NORMAL
        else:
            values["pole_ladder"] = f"{pole_ladder_pair.x}+{pole_ladder_pair.y}"
            if not has_highlight:
                if pole_ladder_pair.y <= 14 and not has_magnet:
                    status["pole_ladder"] = STATUS_RECOMMENDED
                    has_highlight = True
            if has_magnet or pole_ladder_pair.y >= 19:
                status["pole_ladder"] = STATUS_NOT_RECOMMENDED

        result: Dict[str, Any] = {
            "lane": [label_of(x) for x in row],
            "values": values,
            "status": status,
            "has_magnet": has_magnet,
        }
        if explain:
            result["details"] = details
        return result

    def calculate_board(self, board: Sequence[Sequence[Union[str, int, None]]], *, explain: bool = False) -> List[Dict[str, Any]]:
        return [self.calculate_lane(row[:5], explain=explain) for row in list(board)[:5]]

    def dumps(self, obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False, indent=2)


def decorate_value(value: Union[int, str], status: int, *, no_status: bool = False) -> str:
    text = str(value)
    if text == "":
        return ""
    if no_status:
        return text
    if status == STATUS_RECOMMENDED:
        return f"*{text}*"
    if status == STATUS_NOT_RECOMMENDED:
        return f"({text})"
    return text


def format_lane_result(result: Mapping[str, Any], *, row_name: str = "单行", no_status: bool = False) -> str:
    values = result["values"]
    status = result["status"]
    cells = [row_name]
    for key in MODE_KEYS:
        cells.append(decorate_value(values.get(key, ""), status.get(key, 0), no_status=no_status))
    widths = [8, 10, 10, 12, 10, 12]
    return " ".join(str(cells[i]).ljust(widths[i]) for i in range(len(cells)))


def format_result_table(results: Sequence[Mapping[str, Any]], *, no_status: bool = False) -> str:
    headers = ["行", "撑杆", "慢速", "梯子", "橄榄", "撑杆梯子"]
    widths = [8, 10, 10, 12, 10, 12]
    lines = [
        " ".join(headers[i].ljust(widths[i]) for i in range(len(headers))),
        " ".join(("-" * min(widths[i], 8)).ljust(widths[i]) for i in range(len(headers))),
    ]
    for i, result in enumerate(results):
        lines.append(format_lane_result(result, row_name=f"第{i + 1}行", no_status=no_status))
    return "\n".join(lines)


def explain_pole(result: Mapping[str, Any]) -> str:
    details = result.get("details", {}).get("pole")
    if not details:
        return "没有撑杆解释信息。请使用 explain=True 或命令行 --explain。"

    target_col = details.get("target_col_from_left")
    target_label = details.get("target_label")
    if target_col is None:
        target_text = "无起跳目标"
    else:
        target_text = f"第 {target_col} 列 / {target_label}"

    return "\n".join([
        "[撑杆修正解释]",
        f"起跳目标: {target_text}",
        f"是否使用新撑杆逻辑: {details.get('use_modified_pole')}",
        f"canPV: {details.get('can_pv')}",
        f"原跳后伤害 raw: {details.get('postjump_damage_raw'):.4f}",
        f"原跳后伤害 rounded: {details.get('postjump_damage_rounded')}",
        f"新增跳前伤害 raw: {details.get('prejump_damage_raw'):.4f}",
        f"新增跳前伤害 rounded: {details.get('prejump_damage_rounded')}",
        f"修正后撑杆总伤害 raw: {details.get('total_raw'):.4f}",
        f"修正后撑杆总伤害 rounded: {details.get('total')}",
    ])


__all__ = [
    "IZEBloodCalculator",
    "Row",
    "Pair",
    "normalize_label",
    "normalize_lane",
    "format_result_table",
    "format_lane_result",
    "explain_pole",
    "MODE_KEYS",
    "MODE_LABELS_ZH",
]
