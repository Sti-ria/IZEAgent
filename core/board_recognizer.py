from collections import defaultdict
import time

import cv2
import numpy as np

from core.grid import crop_grid_cells_for_recognition
from core.plant_classifier import PlantClassifier


class BoardRecognizer:
    """
    PVZ 棋盘识别器。

    目标：
    1. 只在有效游戏画面上初始化和更新棋盘记忆；
    2. 暂停菜单、选项菜单、最小化、异常截图时冻结；
    3. 初始化后不允许 plant -> another plant；
    4. 只允许 plant -> empty；
    5. plant -> empty 必须连续多帧确认；
    6. plant -> empty 还必须通过“干净空地”视觉检查，避免子弹、僵尸、菜单遮挡误删。
    """

    def __init__(self, config):
        self.config = config

        grid_cfg = config.get("grid", {})
        self.rows = int(grid_cfg.get("rows", 5))
        self.cols = int(grid_cfg.get("cols", 9))

        classifier_cfg = config.get("plant_classifier", {})

        model_path = classifier_cfg.get(
            "model_path",
            "models/plant_cell_classifier.npz",
        )

        unknown_threshold = float(
            classifier_cfg.get("unknown_threshold", 0.55)
        )

        k = int(classifier_cfg.get("k", 5))

        self.classifier = PlantClassifier(
            model_path=model_path,
            unknown_threshold=unknown_threshold,
            k=k,
        )

        self.class_thresholds = classifier_cfg.get("class_thresholds", {}) or {}

        self.default_class_threshold = float(
            self.class_thresholds.get(
                "default",
                unknown_threshold,
            )
        )


        memory_cfg = config.get("board_memory", {})

        self.memory_enabled = bool(
            memory_cfg.get("enabled", True)
        )

        self.init_frames_required = max(
            1,
            int(memory_cfg.get("init_frames", 8)),
        )

        self.init_min_confidence = float(
            memory_cfg.get("init_min_confidence", 0.45)
        )

        self.empty_confirm_frames = max(
            1,
            int(memory_cfg.get("empty_confirm_frames", 5)),
        )

        self.bulk_empty_candidate_threshold = max(
            1,
            int(memory_cfg.get("bulk_empty_candidate_threshold", 3)),
        )

        self.bulk_empty_confirm_frames = max(
            self.empty_confirm_frames,
            int(memory_cfg.get("bulk_empty_confirm_frames", 9)),
        )

        self.empty_confidence_threshold = float(
            memory_cfg.get("empty_confidence_threshold", 0.82)
        )

        self.allow_raw_empty = bool(
            memory_cfg.get("allow_raw_empty", False)
        )

        self.raw_empty_confidence_threshold = float(
            memory_cfg.get("raw_empty_confidence_threshold", 0.90)
        )

        self.clean_empty_required = bool(
            memory_cfg.get("clean_empty_required", True)
        )

        self.clean_empty_edge_density_max = float(
            memory_cfg.get("clean_empty_edge_density_max", 0.18)
        )

        self.clean_empty_bright_ratio_max = float(
            memory_cfg.get("clean_empty_bright_ratio_max", 0.22)
        )

        self.clean_empty_neutral_ratio_max = float(
            memory_cfg.get("clean_empty_neutral_ratio_max", 0.38)
        )

        self.valid_frame_warmup = max(
            0,
            int(memory_cfg.get("valid_frame_warmup", 4)),
        )

        # IZE 无尽新关卡检测：
        # 一关内部仍然禁止 empty -> plant；
        # 但检测到新一关后，调用 reset_memory() 重新进入初始化阶段。
        self.auto_reinitialize = bool(
            memory_cfg.get("auto_reinitialize", True)
        )

        self.reinit_check_cols = min(
            self.cols,
            max(1, int(memory_cfg.get("reinit_check_cols", 6))),
        )

        self.reinit_min_confidence = float(
            memory_cfg.get("reinit_min_confidence", 0.78)
        )

        self.reinit_min_confident_plants = max(
            1,
            int(memory_cfg.get("reinit_min_confident_plants", 6)),
        )

        self.reinit_mismatch_cells = max(
            1,
            int(memory_cfg.get("reinit_mismatch_cells", 6)),
        )

        self.reinit_confirm_frames = max(
            1,
            int(memory_cfg.get("reinit_confirm_frames", 5)),
        )

        self.reinit_cooldown_seconds = float(
            memory_cfg.get("reinit_cooldown_seconds", 3.0)
        )

        self.reinit_candidate_frames = 0
        self.last_reinit_time = 0.0

        frame_guard_cfg = config.get("frame_guard", {})

        self.frame_guard_enabled = bool(
            frame_guard_cfg.get("enabled", True)
        )

        self.min_frame_std = float(
            frame_guard_cfg.get("min_std", 8.0)
        )

        self.min_frame_brightness = float(
            frame_guard_cfg.get("min_brightness", 8.0)
        )

        self.max_frame_brightness = float(
            frame_guard_cfg.get("max_brightness", 245.0)
        )

        self.board_overlay_enabled = bool(
            frame_guard_cfg.get("board_overlay_enabled", True)
        )

        self.board_overlay_largest_ratio_threshold = float(
            frame_guard_cfg.get("board_overlay_largest_ratio_threshold", 0.10)
        )

        self.board_overlay_neutral_ratio_threshold = float(
            frame_guard_cfg.get("board_overlay_neutral_ratio_threshold", 0.18)
        )

        self.board_overlay_dark_ratio_threshold = float(
            frame_guard_cfg.get("board_overlay_dark_ratio_threshold", 0.05)
        )

        self.pause_overlay_largest_ratio_threshold = float(
            frame_guard_cfg.get("pause_overlay_largest_ratio_threshold", 0.14)
        )

        self.pause_gray_ratio_threshold = float(
            frame_guard_cfg.get("pause_gray_ratio_threshold", 0.26)
        )

        self.pause_dark_ratio_threshold = float(
            frame_guard_cfg.get("pause_dark_ratio_threshold", 0.08)
        )

        self.valid_frame_streak = 0
        self._last_freeze_reason = None
        self._last_freeze_log_time = 0
        self._last_status_reason = None
        self._last_status_log_time = 0

        self.reset_memory()

    def reset_memory(self, reason=""):
        """
        清空棋盘记忆，重新进入初始化阶段。

        用途：
        - 程序刚启动；
        - IZE 无尽进入新一关；
        - 手动调试时强制重置。
        """
        self.memory_initialized = False
        self.init_frame_count = 0

        self.board_memory = [
            ["unknown" for _ in range(self.cols)]
            for _ in range(self.rows)
        ]

        self.empty_streak = [
            [0 for _ in range(self.cols)]
            for _ in range(self.rows)
        ]

        self.init_votes = [
            [defaultdict(float) for _ in range(self.cols)]
            for _ in range(self.rows)
        ]

        self.reinit_candidate_frames = 0
        self.last_reinit_time = time.time()

        if reason:
            print(f"[BoardMemory] Reset memory: {reason}")


    def _reset_empty_streaks(self):
        self.empty_streak = [
            [0 for _ in range(self.cols)]
            for _ in range(self.rows)
        ]

    def _log_freeze(self, reason):
        now = time.time()

        if (
            reason != self._last_freeze_reason
            or now - self._last_freeze_log_time > 1.5
        ):
            print(f"[BoardMemory] Freeze recognition: {reason}")
            self._last_freeze_reason = reason
            self._last_freeze_log_time = now

    def _log_status(self, reason):
        now = time.time()

        if (
            reason != self._last_status_reason
            or now - self._last_status_log_time > 2.0
        ):
            print(f"[BoardMemory] {reason}")
            self._last_status_reason = reason
            self._last_status_log_time = now

    def _clip_rect(self, frame, left, top, width, height):
        h, w = frame.shape[:2]

        x1 = max(0, int(left))
        y1 = max(0, int(top))
        x2 = min(w, int(left + width))
        y2 = min(h, int(top + height))

        if x2 <= x1 or y2 <= y1:
            return None

        return x1, y1, x2, y2

    def _crop_board_region(self, frame):
        grid_cfg = self.config.get("grid", {})

        rect = self._clip_rect(
            frame,
            grid_cfg.get("board_left", 0),
            grid_cfg.get("board_top", 0),
            grid_cfg.get("board_width", frame.shape[1]),
            grid_cfg.get("board_height", frame.shape[0]),
        )

        if rect is None:
            return None

        x1, y1, x2, y2 = rect
        return frame[y1:y2, x1:x2]

    def _detect_neutral_overlay(
        self,
        region,
        region_name,
        largest_ratio_threshold,
        neutral_ratio_threshold,
        dark_ratio_threshold,
    ):
        """
        检测大块灰色/暗色菜单覆盖。

        PVZ 菜单的核心特征不是“暗”，而是“中性灰”：
        R/G/B 三个通道差异很小，饱和度低。
        这样可以和正常草地、植物、僵尸区分开。
        """
        if region is None or region.size == 0:
            return False, ""

        rh, rw = region.shape[:2]

        if rh < 80 or rw < 80:
            return False, ""

        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)

        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]

        b = region[:, :, 0].astype(np.int16)
        g = region[:, :, 1].astype(np.int16)
        r = region[:, :, 2].astype(np.int16)

        max_ch = np.maximum.reduce([b, g, r])
        min_ch = np.minimum.reduce([b, g, r])
        channel_delta = max_ch - min_ch

        # 灰色墓碑、灰色按钮、暂停菜单背景
        neutral_mask = (
            (channel_delta < 48)
            & (sat < 95)
            & (val > 28)
            & (val < 232)
        )

        # 暗色菜单内部
        dark_neutral_mask = (
            (channel_delta < 65)
            & (sat < 110)
            & (val > 12)
            & (val < 115)
        )

        overlay_mask = (neutral_mask | dark_neutral_mask).astype(np.uint8) * 255

        kernel = np.ones((9, 9), np.uint8)
        overlay_mask = cv2.morphologyEx(
            overlay_mask,
            cv2.MORPH_CLOSE,
            kernel,
            iterations=2,
        )
        overlay_mask = cv2.morphologyEx(
            overlay_mask,
            cv2.MORPH_OPEN,
            kernel,
            iterations=1,
        )

        contours, _ = cv2.findContours(
            overlay_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        largest_overlay_ratio = 0.0

        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)

            if cw < rw * 0.18 or ch < rh * 0.18:
                continue

            area_ratio = (cw * ch) / float(rw * rh)
            largest_overlay_ratio = max(largest_overlay_ratio, area_ratio)

        neutral_ratio = float(np.mean(neutral_mask))
        dark_ratio = float(np.mean(dark_neutral_mask))
        region_std = float(np.std(gray))

        if (
            largest_overlay_ratio >= largest_ratio_threshold
            and neutral_ratio >= neutral_ratio_threshold
            and dark_ratio >= dark_ratio_threshold
        ):
            return True, (
                f"menu_overlay_{region_name} "
                f"overlay={largest_overlay_ratio:.2f} "
                f"neutral={neutral_ratio:.2f} "
                f"dark={dark_ratio:.2f}"
            )

        # 兜底：如果整个区域有大量中性灰，且纹理变平，也认为被菜单遮挡
        if (
            neutral_ratio >= neutral_ratio_threshold + 0.12
            and dark_ratio >= dark_ratio_threshold
            and region_std < 72
        ):
            return True, (
                f"menu_overlay_flat_{region_name} "
                f"neutral={neutral_ratio:.2f} "
                f"dark={dark_ratio:.2f} "
                f"std={region_std:.1f}"
            )

        return False, ""

    def _is_frame_usable(self, frame):
        if not self.frame_guard_enabled:
            return True, "ok"

        if frame is None:
            return False, "frame_none"

        if len(frame.shape) != 3:
            return False, "bad_frame_shape"

        h, w = frame.shape[:2]

        if h < 100 or w < 100:
            return False, "frame_too_small"

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        mean_val = float(np.mean(gray))
        std_val = float(np.std(gray))

        if mean_val < self.min_frame_brightness:
            return False, "too_dark_or_minimized"

        if mean_val > self.max_frame_brightness:
            return False, "too_bright_or_invalid"

        if std_val < self.min_frame_std:
            return False, "too_flat_or_frozen"

        # 第一优先级：检测棋盘区域是否被暂停菜单/选项菜单覆盖。
        # 你的问题正是这里：菜单挡住棋盘，但 PVZ 仍是前台窗口。
        if self.board_overlay_enabled:
            board_region = self._crop_board_region(frame)

            has_overlay, reason = self._detect_neutral_overlay(
                board_region,
                "board",
                self.board_overlay_largest_ratio_threshold,
                self.board_overlay_neutral_ratio_threshold,
                self.board_overlay_dark_ratio_threshold,
            )

            if has_overlay:
                return False, reason

        # 第二优先级：检测窗口中央区域是否有暂停菜单。
        y1 = int(h * 0.16)
        y2 = int(h * 0.86)
        x1 = int(w * 0.12)
        x2 = int(w * 0.88)

        center = frame[y1:y2, x1:x2]

        has_overlay, reason = self._detect_neutral_overlay(
            center,
            "center",
            self.pause_overlay_largest_ratio_threshold,
            self.pause_gray_ratio_threshold,
            self.pause_dark_ratio_threshold,
        )

        if has_overlay:
            return False, reason

        return True, "ok"

    def _current_board_copy(self):
        if self.memory_initialized:
            return [
                row[:] for row in self.board_memory
            ]

        return [
            ["unknown" for _ in range(self.cols)]
            for _ in range(self.rows)
        ]

    def _build_frozen_results(self, frame, reason):
        if frame is None:
            return [], self._current_board_copy()

        grid_cells = crop_grid_cells_for_recognition(
            frame,
            self.config,
        )

        cell_results = []

        for cell in grid_cells:
            row = cell["row"]
            col = cell["col"]
            bbox = cell["bbox"]

            if (
                self.memory_initialized
                and 0 <= row < self.rows
                and 0 <= col < self.cols
            ):
                memory_label = self.board_memory[row][col]
                streak = self.empty_streak[row][col]
            else:
                memory_label = "unknown"
                streak = 0

            cell_results.append(
                {
                    "row": row,
                    "col": col,
                    "bbox": bbox,

                    "live_label": "invalid_frame",
                    "live_raw_label": reason,
                    "confidence": 0.0,

                    "label": memory_label,
                    "raw_label": reason,
                    "memory_label": memory_label,

                    "memory_initialized": self.memory_initialized,
                    "empty_streak": streak,
                    "empty_required_frames": 0,
                    "empty_candidate": False,

                    "frame_valid": False,
                    "frame_status": reason,

                    "empty_visual_ok": False,
                    "empty_visual_reason": reason,
                }
            )

        return cell_results, self._current_board_copy()

    def _get_class_threshold(self, label):
        """
        获取某个植物类别的额外置信度阈值。

        作用：
        - 对 repeater / peashooter / puffshroom 这种容易误判的类提高门槛；
        - 置信度不够时，不强行写成植物，而是变成 unknown。
        """
        if label in ("unknown", "empty", "invalid_frame"):
            return 0.0

        return float(
            self.class_thresholds.get(
                label,
                self.default_class_threshold,
            )
        )

    def _post_filter_prediction(self, label, confidence):
        """
        对分类器输出做二次过滤。

        注意：
        - 不直接改 raw_label，方便 debug 观察原始分类结果；
        - 只改 live_label；
        - 如果置信度不够，就变 unknown。
        """
        if label in ("unknown", "empty", "invalid_frame"):
            return label, False, 0.0

        threshold = self._get_class_threshold(label)

        if confidence < threshold:
            return "unknown", True, threshold

        return label, False, threshold


    def _evaluate_empty_visual(self, cell_img):
        """
        判断格子是否真的像“干净空地”。

        目的：
        - 子弹遮挡：边缘/亮点多，拒绝；
        - 僵尸遮挡：边缘/中性灰多，拒绝；
        - 暂停菜单遮挡：中性灰多，拒绝；
        - 真实空地：边缘少、亮点少、中性灰少，通过。
        """
        if cell_img is None or cell_img.size == 0:
            return {
                "ok": False,
                "reason": "empty_cell_image",
                "edge_density": 1.0,
                "bright_ratio": 1.0,
                "neutral_ratio": 1.0,
            }

        h, w = cell_img.shape[:2]

        if h < 10 or w < 10:
            return {
                "ok": False,
                "reason": "cell_too_small",
                "edge_density": 1.0,
                "bright_ratio": 1.0,
                "neutral_ratio": 1.0,
            }

        # 稍微裁掉边缘，减少网格线影响
        px = int(w * 0.08)
        py = int(h * 0.08)

        roi = cell_img[
            py:max(py + 1, h - py),
            px:max(px + 1, w - px),
        ]

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]

        b = roi[:, :, 0].astype(np.int16)
        g = roi[:, :, 1].astype(np.int16)
        r = roi[:, :, 2].astype(np.int16)

        max_ch = np.maximum.reduce([b, g, r])
        min_ch = np.minimum.reduce([b, g, r])
        channel_delta = max_ch - min_ch

        edges = cv2.Canny(gray, 60, 140)
        edge_density = float(np.mean(edges > 0))

        bright_ratio = float(np.mean(val > 185))

        neutral_ratio = float(np.mean(
            (channel_delta < 55)
            & (sat < 95)
            & (val > 25)
            & (val < 230)
        ))

        ok = (
            edge_density <= self.clean_empty_edge_density_max
            and bright_ratio <= self.clean_empty_bright_ratio_max
            and neutral_ratio <= self.clean_empty_neutral_ratio_max
        )

        reason = (
            f"edge={edge_density:.2f} "
            f"bright={bright_ratio:.2f} "
            f"neutral={neutral_ratio:.2f}"
        )

        return {
            "ok": ok,
            "reason": reason,
            "edge_density": edge_density,
            "bright_ratio": bright_ratio,
            "neutral_ratio": neutral_ratio,
        }

    def _build_live_predictions(self, frame):
        grid_cells = crop_grid_cells_for_recognition(
            frame,
            self.config,
        )

        live_board = [
            ["unknown" for _ in range(self.cols)]
            for _ in range(self.rows)
        ]

        cell_results = []

        for cell in grid_cells:
            row = cell["row"]
            col = cell["col"]
            bbox = cell["bbox"]
            cell_img = cell["image"]

            pred = self.classifier.predict(cell_img)

            pred_label = pred["label"]
            confidence = float(pred["confidence"])
            live_raw_label = pred["raw_label"]

            live_label, post_blocked, class_threshold = (
                self._post_filter_prediction(
                    pred_label,
                    confidence,
                )
            )


            if 0 <= row < self.rows and 0 <= col < self.cols:
                live_board[row][col] = live_label

            empty_visual = self._evaluate_empty_visual(cell_img)

            cell_results.append(
                {
                    "row": row,
                    "col": col,
                    "bbox": bbox,

                    "cell_image": cell_img,

                    "live_label": live_label,
                    "live_raw_label": live_raw_label,
                    "confidence": confidence,

                    "pred_label": pred_label,
                    "live_post_blocked": post_blocked,
                    "class_threshold": class_threshold,

                    "label": live_label,
                    "raw_label": live_raw_label,

                    "memory_label": live_label,
                    "memory_initialized": self.memory_initialized,
                    "empty_streak": 0,
                    "empty_required_frames": 0,
                    "empty_candidate": False,

                    "frame_valid": True,
                    "frame_status": "ok",

                    "empty_visual_ok": empty_visual["ok"],
                    "empty_visual_reason": empty_visual["reason"],
                    "empty_edge_density": empty_visual["edge_density"],
                    "empty_bright_ratio": empty_visual["bright_ratio"],
                    "empty_neutral_ratio": empty_visual["neutral_ratio"],
                }
            )

        return cell_results, live_board

    def _accumulate_initial_votes(self, cell_results):
        for cell in cell_results:
            row = cell["row"]
            col = cell["col"]

            if not (0 <= row < self.rows and 0 <= col < self.cols):
                continue

            confidence = cell["confidence"]

            if confidence < self.init_min_confidence:
                continue

            # 被类别阈值拦掉的结果，不参与初始化投票
            if cell.get("live_post_blocked", False):
                continue

            live_label = cell["live_label"]

            # 初始化时不要再用 raw_label 兜底。
            # raw_label 只是 debug 用，不能写进 memory。
            if live_label in ("unknown", "invalid_frame"):
                continue

            self.init_votes[row][col][live_label] += confidence


    def _finalize_initial_memory(self, live_board):
        for row in range(self.rows):
            for col in range(self.cols):
                votes = self.init_votes[row][col]

                if votes:
                    best_label = max(
                        votes.items(),
                        key=lambda item: item[1],
                    )[0]
                else:
                    best_label = live_board[row][col]

                self.board_memory[row][col] = best_label

        self.memory_initialized = True

        print(
            f"[BoardMemory] Initialized after "
            f"{self.init_frame_count} valid frames."
        )

    def _is_empty_prediction(self, cell):
        """
        判断当前格子是否可以计入 empty 连续确认。

        注意：
        - live_label == empty 是主要依据；
        - raw_label == empty 默认不信，除非 allow_raw_empty=True；
        - 如果开启 clean_empty_required，还要通过视觉空地检查。
        """
        live_label = cell.get("live_label", "unknown")
        live_raw_label = cell.get("live_raw_label", cell.get("raw_label", "unknown"))
        confidence = float(cell.get("confidence", 0.0))

        is_empty_by_label = (
            live_label == "empty"
            and confidence >= self.empty_confidence_threshold
        )

        is_empty_by_raw = (
            getattr(self, "allow_raw_empty", False)
            and live_raw_label == "empty"
            and confidence >= self.raw_empty_confidence_threshold
        )

        if not (is_empty_by_label or is_empty_by_raw):
            return False

        if getattr(self, "clean_empty_required", False):
            # 如果 cell 里有视觉检查结果，就必须通过。
            # 如果当前旧版本还没有 empty_visual_ok 字段，不强行拦截。
            if "empty_visual_ok" in cell and not cell.get("empty_visual_ok", False):
                return False

        return True

    def _is_reinit_plant_label(self, label):
        """
        新关卡检测时，哪些 live_label 算作植物。

        empty / unknown / invalid_frame 都不能用于触发新关卡。
        """
        return label not in (
            None,
            "",
            "empty",
            "unknown",
            "invalid_frame",
        )

    def _should_reinitialize_for_new_round(self, cell_results):
        """
        判断 IZE 无尽是否进入新一关。

        核心逻辑：
        - 只看红线左侧列；
        - 只相信高置信度植物；
        - 如果连续多帧发现大量 live 植物和 memory 不一致，
          说明红线左侧植物已经被新一关重置；
        - 这时调用 reset_memory()，重新走初始化流程。
        """
        if not self.auto_reinitialize:
            return False

        if not self.memory_initialized:
            return False

        now = time.time()

        if now - self.last_reinit_time < self.reinit_cooldown_seconds:
            return False

        confident_plant_count = 0
        mismatch_count = 0
        empty_to_plant_count = 0
        plant_to_other_plant_count = 0

        for cell in cell_results:
            row = cell["row"]
            col = cell["col"]

            if not (0 <= row < self.rows and 0 <= col < self.cols):
                continue

            # 只看红线左侧。右侧僵尸区域不要参与判断。
            if col >= self.reinit_check_cols:
                continue

            live_label = cell.get("live_label", "unknown")
            confidence = float(cell.get("confidence", 0.0))

            if confidence < self.reinit_min_confidence:
                continue

            if not self._is_reinit_plant_label(live_label):
                continue

            memory_label = self.board_memory[row][col]

            confident_plant_count += 1

            if live_label != memory_label:
                mismatch_count += 1

                if memory_label in ("empty", "unknown"):
                    empty_to_plant_count += 1
                else:
                    plant_to_other_plant_count += 1

        is_candidate = (
            confident_plant_count >= self.reinit_min_confident_plants
            and mismatch_count >= self.reinit_mismatch_cells
        )

        if is_candidate:
            self.reinit_candidate_frames += 1

            self._log_status(
                "New round candidate "
                f"{self.reinit_candidate_frames}/{self.reinit_confirm_frames} "
                f"plants={confident_plant_count} "
                f"mismatch={mismatch_count} "
                f"empty_to_plant={empty_to_plant_count} "
                f"plant_to_other={plant_to_other_plant_count}"
            )
        else:
            self.reinit_candidate_frames = 0

        if self.reinit_candidate_frames >= self.reinit_confirm_frames:
            print(
                "[BoardMemory] New round detected: "
                f"plants={confident_plant_count}, "
                f"mismatch={mismatch_count}, "
                f"empty_to_plant={empty_to_plant_count}, "
                f"plant_to_other={plant_to_other_plant_count}"
            )

            self.reinit_candidate_frames = 0
            return True

        return False



    def _update_memory_after_initialization(self, cell_results):
        """
        初始化完成后更新 memory。

        只允许：
        plant -> empty

        规则：
        - 不允许 plant -> another plant；
        - empty 候选少时，用普通确认帧数；
        - empty 候选多时，用 bulk 确认帧数；
        - 不再因为多个 empty 候选直接冻结，因为多路僵尸可能同时吃植物。
        """

        empty_candidates = []

        # 第一遍：统计这一帧有哪些 plant -> empty 候选
        for cell in cell_results:
            row = cell["row"]
            col = cell["col"]

            cell["empty_required_frames"] = self.empty_confirm_frames
            cell["empty_candidate"] = False

            if not (0 <= row < self.rows and 0 <= col < self.cols):
                continue

            old_label = self.board_memory[row][col]

            if old_label in ("empty", "unknown"):
                continue

            if self._is_empty_prediction(cell):
                empty_candidates.append((row, col))

        bulk_mode = len(empty_candidates) >= self.bulk_empty_candidate_threshold

        if bulk_mode:
            required_frames = self.bulk_empty_confirm_frames
        else:
            required_frames = self.empty_confirm_frames

        empty_candidate_set = set(empty_candidates)

        # 第二遍：累计 empty_streak
        for cell in cell_results:
            row = cell["row"]
            col = cell["col"]

            cell["empty_required_frames"] = required_frames

            if not (0 <= row < self.rows and 0 <= col < self.cols):
                continue

            old_label = self.board_memory[row][col]

            if old_label in ("empty", "unknown"):
                self.empty_streak[row][col] = 0
                cell["empty_streak"] = 0
                cell["empty_candidate"] = False
                continue

            is_empty_now = (row, col) in empty_candidate_set
            cell["empty_candidate"] = is_empty_now

            if is_empty_now:
                self.empty_streak[row][col] += 1
            else:
                self.empty_streak[row][col] = 0

            cell["empty_streak"] = self.empty_streak[row][col]

            if self.empty_streak[row][col] >= required_frames:
                print(
                    f"[BoardMemory] Cell "
                    f"({row + 1}, {col + 1}) "
                    f"{old_label} -> empty"
                )

                self.board_memory[row][col] = "empty"
                self.empty_streak[row][col] = 0

                cell["empty_streak"] = 0
                cell["empty_candidate"] = False



    def _apply_memory_to_results(self, cell_results):
        for cell in cell_results:
            row = cell["row"]
            col = cell["col"]

            if 0 <= row < self.rows and 0 <= col < self.cols:
                memory_label = self.board_memory[row][col]
                streak = self.empty_streak[row][col]
            else:
                memory_label = cell["live_label"]
                streak = 0

            cell["memory_label"] = memory_label
            cell["memory_initialized"] = self.memory_initialized
            cell["empty_streak"] = streak

            # 兼容现有 debug 显示
            cell["label"] = memory_label
            cell["raw_label"] = cell["live_raw_label"]

    def _copy_memory_board(self):
        return [
            row[:] for row in self.board_memory
        ]

    def recognize(self, frame):
        usable, reason = self._is_frame_usable(frame)

        if not usable:
            self.valid_frame_streak = 0
            self._log_freeze(reason)
            self._reset_empty_streaks()
            return self._build_frozen_results(frame, reason)

        self.valid_frame_streak += 1

        if self.valid_frame_streak <= self.valid_frame_warmup:
            warmup_reason = (
                f"valid_frame_warmup "
                f"{self.valid_frame_streak}/{self.valid_frame_warmup}"
            )
            return self._build_frozen_results(frame, warmup_reason)

        cell_results, live_board = self._build_live_predictions(frame)

        if not self.memory_enabled:
            return cell_results, live_board

        # 已经初始化后，先判断是否进入 IZE 无尽新一关。
        # 必须放在 _update_memory_after_initialization() 前面，
        # 因为 update 阶段会禁止 empty -> plant。
        if self.memory_initialized:
            if self._should_reinitialize_for_new_round(cell_results):
                self.reset_memory(reason="new_round")

        if not self.memory_initialized:
            self._accumulate_initial_votes(cell_results)
            self.init_frame_count += 1

            if self.init_frame_count >= self.init_frames_required:
                self._finalize_initial_memory(live_board)
                self._apply_memory_to_results(cell_results)
                return cell_results, self._copy_memory_board()

            return cell_results, live_board

        self._update_memory_after_initialization(cell_results)
        self._apply_memory_to_results(cell_results)

        return cell_results, self._copy_memory_board()

