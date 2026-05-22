from collections import Counter
from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]


class ThemeBoardCorrector:
    """
    根据已锁定主题修正棋盘识别结果。

    当前只做 peashooter / repeater 的主题先验修正：
    - 综合：repeater -> peashooter
    - 输出、控制：peashooter -> repeater

    注意：
    - 只修正 c0-c4，也就是 IZE 初始化阵型区域；
    - 如果当前主题植物可重集已经和配置一致，则跳过纠正；
    - 不把未知植物直接改 empty。
    """

    DEFAULT_RULES = {
        "综合": {
            "repeater": "peashooter",
        },
        "输出": {
            "peashooter": "repeater",
        },
        "控制": {
            "peashooter": "repeater",
        },
    }

    def __init__(self, config):
        self.config = config

        corrector_cfg = config.get("board_corrector", {})
        theme_cfg = config.get("theme", {})

        self.enabled = bool(corrector_cfg.get("enabled", True))

        self.max_col = int(
            corrector_cfg.get(
                "max_col",
                theme_cfg.get("max_col", 4),
            )
        )

        self.only_when_signature_mismatch = bool(
            corrector_cfg.get("only_when_signature_mismatch", True)
        )

        self.signatures_path = corrector_cfg.get(
            "signatures_path",
            theme_cfg.get("signatures_path", "config/theme_signatures.yaml"),
        )

        self.signatures_path = self._resolve_project_path(self.signatures_path)

        self.signature_config = self._load_yaml(self.signatures_path)

        self.ignore_for_theme = set(
            self.signature_config.get(
                "ignore_for_theme",
                ["empty", "unknown", "invalid_frame"],
            )
        )

        self.support_plants = set(
            self.signature_config.get(
                "support_plants",
                ["sunflower", "puffshroom"],
            )
        )

        self.theme_signatures = self._load_theme_signatures()

        self.rules = self._load_rules(
            corrector_cfg.get("rules", self.DEFAULT_RULES)
        )

    def _resolve_project_path(self, path_value):
        path = Path(path_value)

        if path.is_absolute():
            return path

        return ROOT_DIR / path

    def _load_yaml(self, path):
        if not path.exists():
            raise FileNotFoundError(f"Board corrector config not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _load_theme_signatures(self):
        raw_themes = self.signature_config.get("themes", {})
        signatures = {}

        for theme_name, theme_data in raw_themes.items():
            plants = theme_data.get("plants", {}) or {}
            counter = Counter()

            for plant, count in plants.items():
                count = int(count)

                if count > 0:
                    counter[self._normalize_label(plant)] += count

            signatures[theme_name] = counter

        return signatures

    def _load_rules(self, raw_rules):
        rules = {}

        for theme_name, mapping in raw_rules.items():
            rules[theme_name] = {}

            for src, dst in mapping.items():
                src = self._normalize_label(src)
                dst = self._normalize_label(dst)
                rules[theme_name][src] = dst

        return rules

    def _normalize_label(self, label):
        if label is None:
            return "unknown"

        label = str(label).strip()

        mapping = {
            "sun": "sunflower",
            "sun_flower": "sunflower",

            "puff": "puffshroom",
            "puff_shroom": "puffshroom",
            "puff-shroom": "puffshroom",

            "pea": "peashooter",
            "pea_shooter": "peashooter",
            "pea-shooter": "peashooter",

            "repeat": "repeater",
            "double_pea": "repeater",
            "double-pea": "repeater",

            "potato_mine": "potatomine",
            "wall_nut": "wallnut",
            "wall-nut": "wallnut",
            "snow_pea": "snowpea",
            "snow-pea": "snowpea",
        }

        return mapping.get(label, label)

    def _get_cell_label(self, cell):
        for key in (
            "corrected_label",
            "label",
            "memory_label",
            "live_label",
            "raw_label",
        ):
            value = cell.get(key)

            if value is not None:
                return self._normalize_label(value)

        return "unknown"

    def _set_cell_label(self, cell, new_label, reason):
        old_label = self._get_cell_label(cell)

        if "label_before_correction" not in cell:
            cell["label_before_correction"] = old_label

        cell["corrected_label"] = new_label
        cell["label"] = new_label
        cell["memory_label"] = new_label
        cell["correction_reason"] = reason

    def _count_from_cell_results(self, cell_results, max_col=None):
        if max_col is None:
            max_col = self.max_col

        counts = Counter()

        for cell in cell_results:
            row = int(cell.get("row", -1))
            col = int(cell.get("col", -1))

            if row < 0 or col < 0:
                continue

            if col > max_col:
                continue

            label = self._get_cell_label(cell)

            if label in self.ignore_for_theme:
                continue

            if label in self.support_plants:
                continue

            counts[label] += 1

        return counts

    def _count_from_board(self, board, max_col=None):
        if max_col is None:
            max_col = self.max_col

        counts = Counter()

        if board is None:
            return counts

        for row_idx, row in enumerate(board):
            for col_idx, label in enumerate(row):
                if col_idx > max_col:
                    continue

                label = self._normalize_label(label)

                if label in self.ignore_for_theme:
                    continue

                if label in self.support_plants:
                    continue

                counts[label] += 1

        return counts

    def signature_matches(self, theme, cell_results, max_col=None):
        expected = self.theme_signatures.get(theme)

        if expected is None:
            return False

        observed = self._count_from_cell_results(
            cell_results,
            max_col=max_col,
        )

        return observed == expected

    def correct(self, cell_results, board, theme, max_col=None):
        """
        修正当前这一帧输出的 cell_results 和 board。

        返回：
        corrected_cell_results, corrected_board, info
        """
        info = {
            "enabled": self.enabled,
            "theme": theme,
            "changed_count": 0,
            "changes": [],
            "signature_matched_before": False,
            "signature_matched_after": False,
            "skipped_reason": "",
        }

        if not self.enabled:
            info["skipped_reason"] = "disabled"
            return cell_results, board, info

        if theme is None:
            info["skipped_reason"] = "no_theme"
            return cell_results, board, info

        if max_col is None:
            max_col = self.max_col

        expected = self.theme_signatures.get(theme)

        if expected is None:
            info["skipped_reason"] = f"theme_not_found: {theme}"
            return cell_results, board, info

        before_counts = self._count_from_cell_results(
            cell_results,
            max_col=max_col,
        )

        info["before_counts"] = dict(before_counts)
        info["expected_counts"] = dict(expected)

        if before_counts == expected:
            info["signature_matched_before"] = True

            if self.only_when_signature_mismatch:
                info["skipped_reason"] = "signature_already_matched"
                info["signature_matched_after"] = True
                return cell_results, board, info

        rule = self.rules.get(theme, {})

        if not rule:
            info["skipped_reason"] = f"no_rule_for_theme: {theme}"
            return cell_results, board, info

        for cell in cell_results:
            row = int(cell.get("row", -1))
            col = int(cell.get("col", -1))

            if row < 0 or col < 0:
                continue

            if col > max_col:
                continue

            old_label = self._get_cell_label(cell)

            if old_label not in rule:
                continue

            new_label = rule[old_label]

            reason = f"{theme}: {old_label} -> {new_label}"

            self._set_cell_label(cell, new_label, reason)

            if (
                board is not None
                and 0 <= row < len(board)
                and 0 <= col < len(board[row])
            ):
                board[row][col] = new_label

            info["changed_count"] += 1
            info["changes"].append(
                {
                    "row": row,
                    "col": col,
                    "from": old_label,
                    "to": new_label,
                    "reason": reason,
                }
            )

        after_counts = self._count_from_cell_results(
            cell_results,
            max_col=max_col,
        )

        info["after_counts"] = dict(after_counts)
        info["signature_matched_after"] = after_counts == expected

        return cell_results, board, info

    def correct_board_memory(self, board_memory, theme, max_col=None):
        """
        直接修正 BoardRecognizer 内部的 board_memory。

        这样下一帧开始，BoardMemory 自己也会输出修正后的结果，
        不会每帧都靠外部重新改。
        """
        info = {
            "enabled": self.enabled,
            "theme": theme,
            "changed_count": 0,
            "changes": [],
            "signature_matched_before": False,
            "signature_matched_after": False,
            "skipped_reason": "",
        }

        if not self.enabled:
            info["skipped_reason"] = "disabled"
            return info

        if board_memory is None:
            info["skipped_reason"] = "no_board_memory"
            return info

        if theme is None:
            info["skipped_reason"] = "no_theme"
            return info

        if max_col is None:
            max_col = self.max_col

        expected = self.theme_signatures.get(theme)

        if expected is None:
            info["skipped_reason"] = f"theme_not_found: {theme}"
            return info

        before_counts = self._count_from_board(
            board_memory,
            max_col=max_col,
        )

        info["before_counts"] = dict(before_counts)
        info["expected_counts"] = dict(expected)

        if before_counts == expected:
            info["signature_matched_before"] = True

            if self.only_when_signature_mismatch:
                info["skipped_reason"] = "signature_already_matched"
                info["signature_matched_after"] = True
                return info

        rule = self.rules.get(theme, {})

        if not rule:
            info["skipped_reason"] = f"no_rule_for_theme: {theme}"
            return info

        for row_idx, row in enumerate(board_memory):
            for col_idx, label in enumerate(row):
                if col_idx > max_col:
                    continue

                old_label = self._normalize_label(label)

                if old_label not in rule:
                    continue

                new_label = rule[old_label]
                board_memory[row_idx][col_idx] = new_label

                info["changed_count"] += 1
                info["changes"].append(
                    {
                        "row": row_idx,
                        "col": col_idx,
                        "from": old_label,
                        "to": new_label,
                        "reason": f"{theme}: {old_label} -> {new_label}",
                    }
                )

        after_counts = self._count_from_board(
            board_memory,
            max_col=max_col,
        )

        info["after_counts"] = dict(after_counts)
        info["signature_matched_after"] = after_counts == expected

        return info
