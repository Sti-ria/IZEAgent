# -*- coding: utf-8 -*-
"""
Field status detector for I, Zombie / IZE.

This detector intentionally does NOT track zombies lane-by-lane.

Current strategy assumption:
- Most strategies break one lane at a time.
- Dancer may affect nearby lanes, but as long as any zombie is alive,
  we should not immediately replan.
- When the whole field has no zombie and some brains are still alive,
  we should call the theme breaker again.

Output:
{
    "brain_alive_rows": [True, True, False, True, False],
    "alive_brain_rows": [0, 1, 3],
    "any_zombie_present": True,
    "should_replan": False,
    ...
}
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


class FieldStatusDetector:
    """
    Detect:
    - per-row brain alive/dead
    - global zombie present/absent
    - should_replan = has_alive_brain and not any_zombie_present

    Notes:
    - Brain state is one-way by default: alive -> dead.
      It will not become alive again until reset().
    - Zombie detection uses global foreground/motion detection.
      It is intentionally conservative:
        present: fast confirmation
        absent: slower confirmation
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}

        grid_cfg = self.config.get("grid", {})
        self.rows = _safe_int(grid_cfg.get("rows", 5), 5)
        self.cols = _safe_int(grid_cfg.get("cols", 9), 9)

        self.board_left = _safe_int(grid_cfg.get("board_left", 30), 30)
        self.board_top = _safe_int(grid_cfg.get("board_top", 80), 80)
        self.board_width = _safe_int(grid_cfg.get("board_width", 735), 735)
        self.board_height = _safe_int(grid_cfg.get("board_height", 500), 500)

        self.cell_width = self.board_width / max(1, self.cols)
        self.cell_height = self.board_height / max(1, self.rows)

        status_cfg = self.config.get("field_status", {})
        brain_cfg = status_cfg.get("brain", {})
        zombie_cfg = status_cfg.get("zombie", {})
        debug_cfg = status_cfg.get("debug", {})

        self.enabled = bool(status_cfg.get("enabled", True))

        # -------------------------
        # Brain detection settings
        # -------------------------
        # If these are None, use automatic ROI around the left side of board.
        self.brain_x1 = brain_cfg.get("x1", None)
        self.brain_x2 = brain_cfg.get("x2", None)

        self.brain_y_margin_ratio = _safe_float(
            brain_cfg.get("y_margin_ratio", 0.22),
            0.22,
        )

        # Brain is pink/red. Ratio of pink pixels inside ROI.
        self.brain_pink_ratio_threshold = _safe_float(
            brain_cfg.get("pink_ratio_threshold", 0.025),
            0.025,
        )

        self.brain_dead_confirm_frames = _safe_int(
            brain_cfg.get("dead_confirm_frames", 5),
            5,
        )
        self.brain_alive_confirm_frames = _safe_int(
            brain_cfg.get("alive_confirm_frames", 2),
            2,
        )
        self.brain_one_way_dead = bool(brain_cfg.get("one_way_dead", True))

        # -------------------------
        # Zombie global detection settings
        # -------------------------
        self.zombie_x1 = zombie_cfg.get("x1", None)
        self.zombie_x2 = zombie_cfg.get("x2", None)
        self.zombie_y1 = zombie_cfg.get("y1", None)
        self.zombie_y2 = zombie_cfg.get("y2", None)

        self.zombie_extend_left_ratio = _safe_float(
            zombie_cfg.get("extend_left_ratio", 0.15),
            0.15,
        )
        self.zombie_extend_right_ratio = _safe_float(
            zombie_cfg.get("extend_right_ratio", 0.75),
            0.75,
        )
        self.zombie_y_margin_ratio = _safe_float(
            zombie_cfg.get("y_margin_ratio", 0.04),
            0.04,
        )

        self.bg_diff_threshold = _safe_int(
            zombie_cfg.get("bg_diff_threshold", 30),
            30,
        )
        self.motion_diff_threshold = _safe_int(
            zombie_cfg.get("motion_diff_threshold", 24),
            24,
        )

        self.min_component_area = _safe_int(
            zombie_cfg.get("min_component_area", 650),
            650,
        )
        self.min_component_width = _safe_int(
            zombie_cfg.get("min_component_width", 20),
            20,
        )
        self.min_component_height = _safe_int(
            zombie_cfg.get("min_component_height", 36),
            36,
        )
        self.min_motion_area = _safe_int(
            zombie_cfg.get("min_motion_area", 120),
            120,
        )

        self.present_confirm_frames = _safe_int(
            zombie_cfg.get("present_confirm_frames", 2),
            2,
        )
        self.absent_confirm_frames = _safe_int(
            zombie_cfg.get("absent_confirm_frames", 14),
            14,
        )

        self.background_update_alpha = _safe_float(
            zombie_cfg.get("background_update_alpha", 0.03),
            0.03,
        )

        # After placing a zombie, the detector may need a few frames to see it.
        # This manual grace prevents immediate duplicate replans.
        self.after_place_grace_seconds = _safe_float(
            zombie_cfg.get("after_place_grace_seconds", 1.0),
            1.0,
        )

        self.replan_cooldown_seconds = _safe_float(
            status_cfg.get("replan_cooldown_seconds", 1.5),
            1.5,
        )

        self.debug_enabled = bool(debug_cfg.get("enabled", True))

        # -------------------------
        # State
        # -------------------------
        self.brain_alive_rows = [True for _ in range(self.rows)]
        self.brain_alive_streak = [0 for _ in range(self.rows)]
        self.brain_dead_streak = [0 for _ in range(self.rows)]

        self.any_zombie_present = False
        self.zombie_present_streak = 0
        self.zombie_absent_streak = 0

        self.background_gray: Optional[np.ndarray] = None
        self.prev_gray: Optional[np.ndarray] = None
        self.last_zombie_bbox: Optional[Tuple[int, int, int, int]] = None
        self.last_zombie_score = 0.0

        self.last_replan_time = 0.0
        self.last_zombie_place_time = 0.0

        self.last_state = self._make_state(
            brain_scores=[0.0 for _ in range(self.rows)],
            raw_brain_alive=[True for _ in range(self.rows)],
            zombie_score=0.0,
            raw_zombie_present=False,
        )

    def reset(self):
        """
        Call this when a new round starts or when manually pressing R.
        """
        self.brain_alive_rows = [True for _ in range(self.rows)]
        self.brain_alive_streak = [0 for _ in range(self.rows)]
        self.brain_dead_streak = [0 for _ in range(self.rows)]

        self.any_zombie_present = False
        self.zombie_present_streak = 0
        self.zombie_absent_streak = 0

        self.background_gray = None
        self.prev_gray = None
        self.last_zombie_bbox = None
        self.last_zombie_score = 0.0

        self.last_replan_time = 0.0
        self.last_zombie_place_time = 0.0

    def notify_zombie_placed(self):
        """
        Call this after the controller actually places a zombie.

        This prevents repeated replans during the short time before
        visual zombie detection becomes stable.
        """
        now = time.time()
        self.last_zombie_place_time = now
        self.any_zombie_present = True
        self.zombie_present_streak = self.present_confirm_frames
        self.zombie_absent_streak = 0

    def mark_replanned(self):
        """
        Call this after generating or executing a replan.
        """
        self.last_replan_time = time.time()

    def update(self, frame: np.ndarray) -> Dict[str, Any]:
        if frame is None or frame.size == 0 or not self.enabled:
            return self.last_state

        brain_scores = []
        raw_brain_alive = []

        for row in range(self.rows):
            score, raw_alive = self._detect_brain_raw(frame, row)
            brain_scores.append(score)
            raw_brain_alive.append(raw_alive)
            self._update_brain_state(row, raw_alive)

        zombie_score, raw_zombie_present, zombie_bbox = self._detect_zombie_raw(frame)
        self._update_zombie_state(raw_zombie_present)

        self.last_zombie_score = zombie_score
        self.last_zombie_bbox = zombie_bbox

        state = self._make_state(
            brain_scores=brain_scores,
            raw_brain_alive=raw_brain_alive,
            zombie_score=zombie_score,
            raw_zombie_present=raw_zombie_present,
        )

        self.last_state = state
        return state

    def state_signature(self, state: Optional[Dict[str, Any]] = None) -> Tuple:
        """
        Used to invalidate cached strategy plan.
        """
        state = state or self.last_state
        return (
            tuple(bool(x) for x in state.get("brain_alive_rows", [])),
            bool(state.get("any_zombie_present", False)),
            bool(state.get("should_replan", False)),
        )

    def _make_state(
        self,
        *,
        brain_scores: List[float],
        raw_brain_alive: List[bool],
        zombie_score: float,
        raw_zombie_present: bool,
    ) -> Dict[str, Any]:
        now = time.time()

        alive_brain_rows = [
            row
            for row, alive in enumerate(self.brain_alive_rows)
            if bool(alive)
        ]

        has_alive_brain = len(alive_brain_rows) > 0
        in_place_grace = (
            now - self.last_zombie_place_time
            < self.after_place_grace_seconds
        )
        replan_cooldown_passed = (
            now - self.last_replan_time
            >= self.replan_cooldown_seconds
        )

        should_replan = (
            has_alive_brain
            and not self.any_zombie_present
            and not in_place_grace
            and replan_cooldown_passed
        )

        if should_replan:
            reason = "全场无僵尸，且仍有脑子，允许重新调用破阵策略"
        elif not has_alive_brain:
            reason = "没有检测到仍存在的脑子"
        elif self.any_zombie_present:
            reason = "场上仍有僵尸，等待当前进攻结束"
        elif in_place_grace:
            reason = "刚放置僵尸，等待视觉检测稳定"
        else:
            reason = "重新规划冷却中"

        return {
            "brain_alive_rows": list(self.brain_alive_rows),
            "alive_brain_rows": alive_brain_rows,
            "has_alive_brain": has_alive_brain,
            "any_zombie_present": bool(self.any_zombie_present),
            "should_replan": bool(should_replan),
            "reason": reason,
            "brain_scores": [float(x) for x in brain_scores],
            "raw_brain_alive": [bool(x) for x in raw_brain_alive],
            "zombie_score": float(zombie_score),
            "raw_zombie_present": bool(raw_zombie_present),
            "zombie_bbox": self.last_zombie_bbox,
            "in_place_grace": bool(in_place_grace),
            "replan_cooldown_passed": bool(replan_cooldown_passed),
        }

    def _clip_rect(
        self,
        frame: np.ndarray,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
    ) -> Tuple[int, int, int, int]:
        h, w = frame.shape[:2]

        x1 = max(0, min(w - 1, int(x1)))
        y1 = max(0, min(h - 1, int(y1)))
        x2 = max(0, min(w, int(x2)))
        y2 = max(0, min(h, int(y2)))

        if x2 <= x1:
            x2 = min(w, x1 + 1)
        if y2 <= y1:
            y2 = min(h, y1 + 1)

        return x1, y1, x2, y2

    def brain_roi(self, frame: np.ndarray, row: int) -> Tuple[int, int, int, int]:
        lane_y1 = self.board_top + row * self.cell_height
        lane_y2 = self.board_top + (row + 1) * self.cell_height
        margin_y = int(self.cell_height * self.brain_y_margin_ratio)

        y1 = int(lane_y1 + margin_y)
        y2 = int(lane_y2 - margin_y)

        if self.brain_x1 is None:
            x1 = int(self.board_left - self.cell_width * 0.55)
        else:
            x1 = int(self.brain_x1)

        if self.brain_x2 is None:
            x2 = int(self.board_left + self.cell_width * 0.35)
        else:
            x2 = int(self.brain_x2)

        return self._clip_rect(frame, x1, y1, x2, y2)

    def zombie_roi(self, frame: np.ndarray) -> Tuple[int, int, int, int]:
        if self.zombie_x1 is None:
            x1 = int(self.board_left - self.cell_width * self.zombie_extend_left_ratio)
        else:
            x1 = int(self.zombie_x1)

        if self.zombie_x2 is None:
            x2 = int(
                self.board_left
                + self.board_width
                + self.cell_width * self.zombie_extend_right_ratio
            )
        else:
            x2 = int(self.zombie_x2)

        if self.zombie_y1 is None:
            y1 = int(self.board_top + self.board_height * self.zombie_y_margin_ratio)
        else:
            y1 = int(self.zombie_y1)

        if self.zombie_y2 is None:
            y2 = int(
                self.board_top
                + self.board_height
                - self.board_height * self.zombie_y_margin_ratio
            )
        else:
            y2 = int(self.zombie_y2)

        return self._clip_rect(frame, x1, y1, x2, y2)

    def _detect_brain_raw(self, frame: np.ndarray, row: int) -> Tuple[float, bool]:
        x1, y1, x2, y2 = self.brain_roi(frame, row)
        roi = frame[y1:y2, x1:x2]

        if roi.size == 0:
            return 0.0, False

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        h = hsv[:, :, 0]
        s = hsv[:, :, 1]
        v = hsv[:, :, 2]

        # Brain is usually pink/red.
        # OpenCV hue range is 0-179.
        pink_mask_1 = (h >= 135) & (h <= 179) & (s >= 35) & (v >= 55)
        pink_mask_2 = (h >= 0) & (h <= 14) & (s >= 45) & (v >= 65)

        pink_mask = pink_mask_1 | pink_mask_2

        score = float(np.count_nonzero(pink_mask)) / float(pink_mask.size + 1e-6)
        alive = score >= self.brain_pink_ratio_threshold

        return score, alive

    def _update_brain_state(self, row: int, raw_alive: bool) -> bool:
        if raw_alive:
            self.brain_alive_streak[row] += 1
            self.brain_dead_streak[row] = 0
        else:
            self.brain_dead_streak[row] += 1
            self.brain_alive_streak[row] = 0

        if self.brain_alive_rows[row]:
            if self.brain_dead_streak[row] >= self.brain_dead_confirm_frames:
                self.brain_alive_rows[row] = False
        else:
            if (
                not self.brain_one_way_dead
                and self.brain_alive_streak[row] >= self.brain_alive_confirm_frames
            ):
                self.brain_alive_rows[row] = True

        return self.brain_alive_rows[row]

    def _detect_zombie_raw(
        self,
        frame: np.ndarray,
    ) -> Tuple[float, bool, Optional[Tuple[int, int, int, int]]]:
        x1, y1, x2, y2 = self.zombie_roi(frame)
        roi = frame[y1:y2, x1:x2]

        if roi.size == 0:
            return 0.0, False, None

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if self.background_gray is None:
            self.background_gray = gray.astype(np.float32)
            self.prev_gray = gray.copy()
            return 0.0, False, None

        bg_u8 = cv2.convertScaleAbs(self.background_gray)
        bg_diff = cv2.absdiff(gray, bg_u8)

        _, bg_mask = cv2.threshold(
            bg_diff,
            self.bg_diff_threshold,
            255,
            cv2.THRESH_BINARY,
        )

        if self.prev_gray is not None:
            motion_diff = cv2.absdiff(gray, self.prev_gray)
            _, motion_mask = cv2.threshold(
                motion_diff,
                self.motion_diff_threshold,
                255,
                cv2.THRESH_BINARY,
            )
        else:
            motion_mask = np.zeros_like(bg_mask)

        kernel = np.ones((5, 5), dtype=np.uint8)

        bg_mask = cv2.morphologyEx(bg_mask, cv2.MORPH_OPEN, kernel)
        bg_mask = cv2.morphologyEx(bg_mask, cv2.MORPH_CLOSE, kernel)

        motion_mask = cv2.morphologyEx(motion_mask, cv2.MORPH_OPEN, kernel)
        motion_mask = cv2.morphologyEx(motion_mask, cv2.MORPH_CLOSE, kernel)

        raw_present = False
        best_area = 0
        best_bbox_local = None

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
            bg_mask,
            connectivity=8,
        )

        for label_id in range(1, num_labels):
            bx = int(stats[label_id, cv2.CC_STAT_LEFT])
            by = int(stats[label_id, cv2.CC_STAT_TOP])
            bw = int(stats[label_id, cv2.CC_STAT_WIDTH])
            bh = int(stats[label_id, cv2.CC_STAT_HEIGHT])
            area = int(stats[label_id, cv2.CC_STAT_AREA])

            if area < self.min_component_area:
                continue
            if bw < self.min_component_width or bh < self.min_component_height:
                continue

            comp_motion = motion_mask[by : by + bh, bx : bx + bw]
            motion_area = int(np.count_nonzero(comp_motion))

            # Detect new zombie by motion.
            # Keep existing zombie by foreground component, because some zombies move slowly.
            has_enough_motion = motion_area >= self.min_motion_area
            can_keep_existing = self.any_zombie_present and area >= best_area

            if not has_enough_motion and not can_keep_existing:
                continue

            if area > best_area:
                best_area = area
                best_bbox_local = (bx, by, bw, bh)
                raw_present = True

        self.prev_gray = gray.copy()

        # Only update background when the field looks clean.
        if not raw_present and not self.any_zombie_present:
            cv2.accumulateWeighted(
                gray.astype(np.float32),
                self.background_gray,
                self.background_update_alpha,
            )

        if best_bbox_local is None:
            return float(best_area), False, None

        bx, by, bw, bh = best_bbox_local
        bbox_global = (x1 + bx, y1 + by, bw, bh)

        return float(best_area), raw_present, bbox_global

    def _update_zombie_state(self, raw_present: bool) -> bool:
        if raw_present:
            self.zombie_present_streak += 1
            self.zombie_absent_streak = 0
        else:
            self.zombie_absent_streak += 1
            self.zombie_present_streak = 0

        if not self.any_zombie_present:
            if self.zombie_present_streak >= self.present_confirm_frames:
                self.any_zombie_present = True
        else:
            if self.zombie_absent_streak >= self.absent_confirm_frames:
                self.any_zombie_present = False

        return self.any_zombie_present

    def draw_debug(self, frame: np.ndarray, state: Optional[Dict[str, Any]] = None) -> np.ndarray:
        if not self.debug_enabled:
            return frame

        state = state or self.last_state
        vis = frame

        brain_alive_rows = state.get("brain_alive_rows", [])
        brain_scores = state.get("brain_scores", [])

        for row in range(self.rows):
            x1, y1, x2, y2 = self.brain_roi(vis, row)
            alive = bool(brain_alive_rows[row]) if row < len(brain_alive_rows) else False
            score = float(brain_scores[row]) if row < len(brain_scores) else 0.0

            color = (0, 220, 0) if alive else (0, 0, 220)
            cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)

            label = f"B{row + 1}:{'Y' if alive else 'N'} {score:.3f}"
            cv2.putText(
                vis,
                label,
                (x1, max(16, y1 - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                color,
                1,
                cv2.LINE_AA,
            )

        zx1, zy1, zx2, zy2 = self.zombie_roi(vis)
        zombie_color = (0, 180, 255) if state.get("any_zombie_present") else (160, 160, 160)
        cv2.rectangle(vis, (zx1, zy1), (zx2, zy2), zombie_color, 1)

        bbox = state.get("zombie_bbox")
        if bbox is not None:
            bx, by, bw, bh = bbox
            cv2.rectangle(vis, (bx, by), (bx + bw, by + bh), (0, 255, 255), 2)

        panel_x = 10
        panel_y = 118

        any_zombie = bool(state.get("any_zombie_present"))
        should_replan = bool(state.get("should_replan"))
        alive_rows = state.get("alive_brain_rows", [])

        lines = [
            f"Brains alive: {[r + 1 for r in alive_rows]}",
            f"Any zombie: {'Y' if any_zombie else 'N'}",
            f"Should replan: {'Y' if should_replan else 'N'}",
        ]

        for idx, line in enumerate(lines):
            color = (0, 0, 255) if should_replan and idx == 2 else (255, 255, 255)
            cv2.putText(
                vis,
                line,
                (panel_x, panel_y + idx * 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                color,
                1,
                cv2.LINE_AA,
            )

        return vis
