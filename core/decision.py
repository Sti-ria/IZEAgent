class IZombieDecisionMaker:
    """
    我是僵尸模式的简单策略规划器。

    第一版策略：
    - 统计每一行植物强度
    - 选择防守最弱的一行
    - 根据该行强度选择僵尸
    """

    PLANT_SCORE = {
        None: 0,
        "peashooter": 2,
        "snow_pea": 3,
        "repeater": 4,
        "threepeater": 4,
        "wallnut": 5,
        "tallnut": 8,
        "chomper": 5,
        "potato_mine": 4,
        "starfruit": 4,
        "split_pea": 3,
    }

    def __init__(self, config):
        self.config = config

    def evaluate_rows(self, board):
        row_scores = []

        for row_idx, row in enumerate(board):
            score = 0

            for cell in row:
                plant = cell["plant"]
                score += self.PLANT_SCORE.get(plant, 2 if plant else 0)

            row_scores.append(
                {
                    "row": row_idx,
                    "score": score,
                }
            )

        return row_scores

    def choose_plan(self, board, cards):
        row_scores = self.evaluate_rows(board)

        # 选择分数最低的一行作为突破口
        target = min(row_scores, key=lambda x: x["score"])
        row = target["row"]
        score = target["score"]

        available_cards = {
            name: card for name, card in cards.items() if card["available"]
        }

        zombie = self._choose_zombie(score, available_cards)

        if zombie is None:
            return {
                "action": "WAIT",
                "reason": "No available zombie card",
            }

        return {
            "action": "PLACE_ZOMBIE",
            "zombie": zombie,
            "row": row,
            "col": 0,
            "row_score": score,
            "row_scores": row_scores,
        }

    def _choose_zombie(self, row_score, available_cards):
        """
        简单规则：
        - 弱行：普通僵尸
        - 中等行：路障僵尸
        - 强行：铁桶僵尸
        """

        if row_score <= 3:
            for name in ["normal_zombie", "conehead_zombie", "buckethead_zombie"]:
                if name in available_cards:
                    return name

        if row_score <= 8:
            for name in ["conehead_zombie", "buckethead_zombie", "normal_zombie"]:
                if name in available_cards:
                    return name

        for name in ["buckethead_zombie", "conehead_zombie", "normal_zombie"]:
            if name in available_cards:
                return name

        return None
