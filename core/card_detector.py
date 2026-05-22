import cv2
import numpy as np


class CardDetector:
    """
    检测僵尸卡槽是否可用。

    第一版：
    - 卡牌种类从 config 固定读取
    - 卡槽坐标根据 slot index 计算
    - 是否可用通过亮度 / 灰度判断
    """

    def __init__(self, config):
        self.config = config

        self.cards = config.get("cards", {})
        slot_cfg = config.get("card_slots", {})

        self.start_x = slot_cfg.get("start_x", 80)
        self.start_y = slot_cfg.get("start_y", 8)
        self.slot_width = slot_cfg.get("slot_width", 55)
        self.slot_height = slot_cfg.get("slot_height", 75)
        self.gap = slot_cfg.get("gap", 5)

    def slot_rect(self, slot):
        x1 = int(self.start_x + slot * (self.slot_width + self.gap))
        y1 = int(self.start_y)
        x2 = int(x1 + self.slot_width)
        y2 = int(y1 + self.slot_height)
        return x1, y1, x2, y2

    def detect_cards(self, frame):
        result = {}

        for name, info in self.cards.items():
            slot = info["slot"]
            cost = info["cost"]

            x1, y1, x2, y2 = self.slot_rect(slot)
            crop = frame[y1:y2, x1:x2]

            available = self._is_card_available(crop)

            result[name] = {
                "name": name,
                "slot": slot,
                "cost": cost,
                "available": available,
                "rect": (x1, y1, x2, y2),
            }

        return result

    def _is_card_available(self, crop):
        if crop.size == 0:
            return False

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        mean_val = float(np.mean(gray))
        std_val = float(np.std(gray))

        # 初始经验规则：
        # 可用卡牌通常更亮、对比度更明显；
        # 不可用 / 冷却 / 灰色时整体更暗或更灰。
        return mean_val > 65 and std_val > 18
