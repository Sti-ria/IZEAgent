import cv2
import os
import numpy as np


class PlantDetector:
    """
    基于模板匹配的植物识别。

    第一版策略：
    - 对每个格子裁剪 cell image
    - 和所有植物模板做 matchTemplate
    - 选择分数最高且超过阈值的植物
    """

    def __init__(self, config, grid):
        self.grid = grid

        template_cfg = config.get("templates", {})
        self.template_dir = template_cfg.get("plant_dir", "assets/templates/plants")
        self.threshold = template_cfg.get("threshold", 0.62)

        self.templates = self._load_templates(self.template_dir)

    def _load_templates(self, template_dir):
        templates = {}

        if not os.path.exists(template_dir):
            print(f"[PlantDetector] Template dir not found: {template_dir}")
            return templates

        for filename in os.listdir(template_dir):
            if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
                continue

            name = os.path.splitext(filename)[0]
            path = os.path.join(template_dir, filename)

            img = cv2.imread(path, cv2.IMREAD_COLOR)

            if img is None:
                continue

            templates[name] = img

        print(f"[PlantDetector] Loaded templates: {list(templates.keys())}")
        return templates

    def detect_cell(self, frame, row, col):
        x1, y1, x2, y2 = self.grid.cell_rect(row, col)
        cell_img = frame[y1:y2, x1:x2]

        if cell_img.size == 0:
            return None, 0.0

        best_name = None
        best_score = 0.0

        for name, template in self.templates.items():
            score = self._match(cell_img, template)

            if score > best_score:
                best_score = score
                best_name = name

        if best_score >= self.threshold:
            return best_name, best_score

        return None, best_score

    def detect_board(self, frame):
        board = []

        for row in range(self.grid.rows):
            row_result = []

            for col in range(self.grid.cols):
                plant, score = self.detect_cell(frame, row, col)

                row_result.append(
                    {
                        "row": row,
                        "col": col,
                        "plant": plant,
                        "score": score,
                    }
                )

            board.append(row_result)

        return board

    def _match(self, image, template):
        """
        多尺度简单模板匹配。
        """
        image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

        ih, iw = image_gray.shape[:2]
        th, tw = template_gray.shape[:2]

        if th > ih or tw > iw:
            scale = min(iw / tw, ih / th) * 0.9
            new_w = max(1, int(tw * scale))
            new_h = max(1, int(th * scale))
            template_gray = cv2.resize(template_gray, (new_w, new_h))
            th, tw = template_gray.shape[:2]

        if th > ih or tw > iw:
            return 0.0

        result = cv2.matchTemplate(image_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)

        return float(max_val)
