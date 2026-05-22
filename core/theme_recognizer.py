from collections import Counter, deque
from pathlib import Path
import yaml


class ThemeRecognizer:
    """
    IZE 主题识别器。

    核心思路：
    1. 只统计 IZE 初始植物区域，也就是 5 行 × 前 5 列 = 25 格；
    2. sunflower / puffshroom 作为 support plants，不直接决定大多数主题；
    3. 每个主题有自己的 support_total 和 signature_total；
    4. 使用 Counter 可重集距离匹配主题。
    """

    def __init__(self, config_path="config/theme_signatures.yaml"):
        self.config_path = Path(config_path)

        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}

        self.ignore_for_theme = set(
            self.config.get(
                "ignore_for_theme",
                ["empty", "unknown", "invalid_frame"],
            )
        )

        self.support_plants = set(
            self.config.get(
                "support_plants",
                ["sunflower", "puffshroom"],
            )
        )

        self.total_cells = int(self.config.get("total_cells", 25))

        self.themes = self._load_themes()

    def _load_themes(self):
        raw_themes = self.config.get("themes", {})
        if not raw_themes:
            raise ValueError("No themes found in theme_signatures.yaml")

        themes = {}

        for theme_name, data in raw_themes.items():
            plants = data.get("plants", {}) or {}

            signature = Counter()
            for plant, count in plants.items():
                count = int(count)
                if count > 0:
                    signature[plant] += count

            support_total = int(data.get("support_total", 8))
            signature_total = int(data.get("signature_total", sum(signature.values())))

            actual_signature_total = sum(signature.values())
            if actual_signature_total != signature_total:
                raise ValueError(
                    f"Theme {theme_name} signature_total mismatch: "
                    f"configured={signature_total}, actual={actual_signature_total}"
                )

            themes[theme_name] = {
                "support_total": support_total,
                "signature_total": signature_total,
                "signature": signature,
            }

        return themes

    def _normalize_label(self, label):
        mapping = {
            "sun": "sunflower",
            "sun_flower": "sunflower",

            "puff": "puffshroom",
            "puff_shroom": "puffshroom",
            "puff-shroom": "puffshroom",

            "fume_shroom": "fumeshroom",
            "fume-shroom": "fumeshroom",

            "scaredy": "scaredyshroom",
            "scaredy_shroom": "scaredyshroom",
            "scaredy-shroom": "scaredyshroom",

            "potato_mine": "potatomine",
            "potato-mine": "potatomine",

            "wall_nut": "wallnut",
            "wall-nut": "wallnut",

            "snow_pea": "snowpea",
            "snow-pea": "snowpea",

            "split_pea": "splitpea",
            "split-pea": "splitpea",

            "three_peater": "threepeater",
            "three-peater": "threepeater",

            "magnet_shroom": "magnetshroom",
            "magnet-shroom": "magnetshroom",

            "umbrella_leaf": "umbrellaleaf",
            "umbrella-leaf": "umbrellaleaf",

            "kernel_pult": "kernelpult",
            "kernel-pult": "kernelpult",

            "spike_weed": "spikeweed",
            "spike-weed": "spikeweed",
        }

        label = str(label).strip()
        return mapping.get(label, label)

    def count_from_cell_results(self, cell_results, max_col=4):
        """
        cell_results 来自 BoardRecognizer.recognize(frame)。

        每个 cell 至少需要包含：
        {
            "row": 0,
            "col": 0,
            "label": "snowpea",
            "memory_label": "snowpea"
        }
        """
        counts = Counter()

        for cell in cell_results:
            row = int(cell.get("row", -1))
            col = int(cell.get("col", -1))

            if row < 0 or col < 0:
                continue

            if col > max_col:
                continue

            label = cell.get("memory_label", cell.get("label", "unknown"))
            label = self._normalize_label(label)

            counts[label] += 1

        return counts

    def count_from_board(self, board, max_col=4):
        """
        board 是 5x9 或 5x5 的二维数组。
        只统计前 5 列。
        """
        counts = Counter()

        for row in range(len(board)):
            for col in range(min(len(board[row]), max_col + 1)):
                label = self._normalize_label(board[row][col])
                counts[label] += 1

        return counts

    def _build_signature_counter(self, counts):
        observed = Counter()

        for label, count in counts.items():
            if label in self.ignore_for_theme:
                continue
            if label in self.support_plants:
                continue
            if count <= 0:
                continue

            observed[label] += count

        return observed

    def _counter_distance(self, observed, expected):
        keys = set(observed.keys()) | set(expected.keys())
        return sum(abs(observed.get(k, 0) - expected.get(k, 0)) for k in keys)

    def _score_theme(self, counts, theme_name, theme_data):
        observed_signature = self._build_signature_counter(counts)
        expected_signature = theme_data["signature"]

        plant_distance = self._counter_distance(
            observed_signature,
            expected_signature,
        )

        support_count = sum(
            counts.get(label, 0)
            for label in self.support_plants
        )

        expected_support = theme_data["support_total"]
        support_distance = abs(support_count - expected_support)

        total_count = sum(counts.values())
        total_distance = abs(total_count - self.total_cells)

        # support_total 对区分“回复主题”很重要，所以权重稍微高一点。
        distance = plant_distance + support_distance * 2 + total_distance * 2

        max_distance = self.total_cells * 2
        score = 1.0 - distance / max_distance
        score = max(0.0, min(1.0, score))

        problems = []

        if total_count != self.total_cells:
            problems.append(
                f"total cells should be {self.total_cells}, got {total_count}"
            )

        if support_count != expected_support:
            problems.append(
                f"support plants should be {expected_support}, got {support_count}"
            )

        if sum(observed_signature.values()) != theme_data["signature_total"]:
            problems.append(
                f"signature plants should be {theme_data['signature_total']}, "
                f"got {sum(observed_signature.values())}"
            )

        unknown_empty_count = (
            counts.get("unknown", 0)
            + counts.get("empty", 0)
            + counts.get("invalid_frame", 0)
        )

        return {
            "theme": theme_name,
            "score": score,
            "distance": distance,
            "plant_distance": plant_distance,
            "support_distance": support_distance,
            "support_count": support_count,
            "expected_support": expected_support,
            "signature_count": sum(observed_signature.values()),
            "expected_signature_count": theme_data["signature_total"],
            "unknown_empty_count": unknown_empty_count,
            "strict_valid": len(problems) == 0,
            "problems": problems,
            "observed_signature": dict(observed_signature),
            "expected_signature": dict(expected_signature),
        }

    def recognize_from_counts(self, counts):
        candidates = []

        for theme_name, theme_data in self.themes.items():
            candidates.append(
                self._score_theme(counts, theme_name, theme_data)
            )

        candidates.sort(key=lambda x: x["score"], reverse=True)

        best = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None

        margin = best["score"] - second["score"] if second else 1.0

        return {
            "theme": best["theme"],
            "score": best["score"],
            "margin": margin,
            "distance": best["distance"],
            "strict_valid": best["strict_valid"],
            "problems": best["problems"],
            "counts": dict(counts),
            "observed_signature": best["observed_signature"],
            "expected_signature": best["expected_signature"],
            "support_count": best["support_count"],
            "expected_support": best["expected_support"],
            "signature_count": best["signature_count"],
            "expected_signature_count": best["expected_signature_count"],
            "unknown_empty_count": best["unknown_empty_count"],
            "candidates": candidates[:3],
        }

    def recognize(self, cell_results, max_col=4):
        counts = self.count_from_cell_results(cell_results, max_col=max_col)
        return self.recognize_from_counts(counts)

    def recognize_board(self, board, max_col=4):
        counts = self.count_from_board(board, max_col=max_col)
        return self.recognize_from_counts(counts)


class StableThemeRecognizer:
    """
    多帧稳定主题识别。

    不建议单帧直接决定主题。
    开局时连续几帧都识别成同一个主题，再锁定。
    """

    def __init__(
        self,
        theme_recognizer,
        required_frames=4,
        min_score=0.86,
        min_margin=0.06,
        max_unknown_empty=1,
    ):
        self.theme_recognizer = theme_recognizer
        self.required_frames = int(required_frames)
        self.min_score = float(min_score)
        self.min_margin = float(min_margin)
        self.max_unknown_empty = int(max_unknown_empty)

        self.history = deque(maxlen=self.required_frames)

    def reset(self):
        self.history.clear()

    def update(self, cell_results, max_col=4):
        result = self.theme_recognizer.recognize(
            cell_results,
            max_col=max_col,
        )

        confident = (
            result["score"] >= self.min_score
            and result["margin"] >= self.min_margin
            and result["unknown_empty_count"] <= self.max_unknown_empty
        )

        if confident:
            self.history.append(result["theme"])
        else:
            self.history.clear()

        stable = (
            len(self.history) == self.required_frames
            and len(set(self.history)) == 1
        )

        result["stable"] = stable
        result["stable_theme"] = self.history[-1] if stable else None
        result["history"] = list(self.history)

        return result
