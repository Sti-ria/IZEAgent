import sys
import time
import ctypes
from ctypes import wintypes
from pathlib import Path

import cv2
import yaml
import numpy as np


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from core.board_recognizer import BoardRecognizer
from core.board_debug import draw_board_results
from core.theme_recognizer import ThemeRecognizer, StableThemeRecognizer
from core.board_corrector import ThemeBoardCorrector

try:
    from core.ize_blood_calculator import IZEBloodCalculator
except Exception as e:
    IZEBloodCalculator = None
    IZEBloodCalculator_IMPORT_ERROR = e
else:
    IZEBloodCalculator_IMPORT_ERROR = None




CONFIG_PATH = ROOT_DIR / "config" / "settings.yaml"
LOCAL_CONFIG_PATH = ROOT_DIR / "config" / "local_settings.yaml"


user32 = ctypes.windll.user32


try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def deep_merge(base, override):
    for key, value in override.items():
        if (
            isinstance(value, dict)
            and key in base
            and isinstance(base[key], dict)
        ):
            deep_merge(base[key], value)
        else:
            base[key] = value

    return base


def load_yaml(path):
    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config():
    config = load_yaml(CONFIG_PATH)
    local_config = load_yaml(LOCAL_CONFIG_PATH)

    if local_config:
        config = deep_merge(config, local_config)
        print(f"Loaded local config: {LOCAL_CONFIG_PATH}")

    return config


def get_window_title(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)

    if length <= 0:
        return ""

    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)

    return buffer.value.strip()


def get_window_rect_on_screen(hwnd):
    rect = wintypes.RECT()
    ok = user32.GetWindowRect(hwnd, ctypes.byref(rect))

    if not ok:
        return None

    return {
        "left": int(rect.left),
        "top": int(rect.top),
        "width": int(rect.right - rect.left),
        "height": int(rect.bottom - rect.top),
    }


def get_client_rect_on_screen(hwnd):
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))

    point = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(point))

    width = rect.right - rect.left
    height = rect.bottom - rect.top

    return {
        "left": int(point.x),
        "top": int(point.y),
        "width": int(width),
        "height": int(height),
    }


def enum_visible_windows():
    windows = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        wintypes.HWND,
        wintypes.LPARAM,
    )

    def callback(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True

        title = get_window_title(hwnd)

        if not title:
            return True

        rect = get_window_rect_on_screen(hwnd)

        if rect is None:
            return True

        if rect["width"] <= 0 or rect["height"] <= 0:
            return True

        windows.append(
            {
                "hwnd": hwnd,
                "title": title,
                "region": rect,
            }
        )

        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)

    return windows


def find_pvz_window(config):
    window_cfg = config.get("window", {})
    title_keywords = window_cfg.get("title_keywords", [])

    if not title_keywords:
        title_keywords = [
            "Plants vs. Zombies",
            "植物大战僵尸",
        ]

    windows = enum_visible_windows()

    candidates = []

    bad_words = [
        "visual studio code",
        "vscode",
        "pvzagent",
        "powershell",
        "cmd.exe",
        "terminal",
        "debug_board_recognition",
    ]

    for win in windows:
        title = win["title"]
        title_lower = title.lower()
        region = win["region"]

        if region["width"] < 400 or region["height"] < 300:
            continue

        if any(bad in title_lower for bad in bad_words):
            continue

        for keyword in title_keywords:
            keyword_lower = str(keyword).lower()

            if keyword_lower in title_lower:
                candidates.append(win)
                break

    if not candidates:
        print("\nVisible windows:")
        for win in windows:
            print(f"- {win['title']!r}, region={win['region']}")

        raise RuntimeError(
            "没有找到 PVZ 窗口。请确认游戏已经打开，并且 settings.yaml 里的 window.title_keywords 正确。"
        )

    candidates.sort(
        key=lambda w: w["region"]["width"] * w["region"]["height"],
        reverse=True,
    )

    return candidates[0]


def bring_window_to_front(hwnd):
    SW_RESTORE = 9

    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.1)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.1)
    except Exception:
        pass


def rect_intersection_area(a, b):
    ax1 = a["left"]
    ay1 = a["top"]
    ax2 = a["left"] + a["width"]
    ay2 = a["top"] + a["height"]

    bx1 = b["left"]
    by1 = b["top"]
    bx2 = b["left"] + b["width"]
    by2 = b["top"] + b["height"]

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    if ix2 <= ix1 or iy2 <= iy1:
        return 0

    return (ix2 - ix1) * (iy2 - iy1)


def is_capture_region_occluded(target_hwnd, capture_region):
    """
    判断是否有其他窗口盖在 PVZ 客户区上。

    注意：
    - 不再要求 PVZ 必须是前台窗口；
    - 只有其他窗口实际与 capture_region 相交，才冻结；
    - 暂停菜单属于 PVZ 内部内容，不在这里处理，由 BoardRecognizer 处理。
    """
    if user32.IsIconic(target_hwnd):
        return True, "PVZ window is minimized"

    windows = enum_visible_windows()

    capture_area = capture_region["width"] * capture_region["height"]

    if capture_area <= 0:
        return True, "bad capture region"

    ignore_title_keywords = [
        "program manager",
        "windows input experience",
        "windows 小组件",
        "小组件",
        "widgets",
        "widget",
        "nvidia",
        "任务栏",
        "taskbar",
    ]

    for win in windows:
        hwnd = win["hwnd"]

        # EnumWindows 通常按 Z-order 从前到后枚举。
        # 遇到目标 PVZ 窗口后，后面的窗口都在它下面，不会遮挡它。
        if hwnd == target_hwnd:
            return False, "ok"

        title = win["title"]
        title_lower = title.lower()

        if any(k in title_lower for k in ignore_title_keywords):
            continue

        region = win["region"]

        if region["width"] < 50 or region["height"] < 50:
            continue

        inter_area = rect_intersection_area(region, capture_region)

        if inter_area <= 0:
            continue

        inter_ratio = inter_area / float(capture_area)

        # 小于 1% 的相交通常是阴影/边框，忽略。
        if inter_ratio >= 0.01 and inter_area >= 3000:
            return True, (
                f"PVZ capture region occluded by {title!r}, "
                f"ratio={inter_ratio:.3f}"
            )

    return False, "ok"


def grab_region(region):
    import time
    import cv2
    import mss
    import numpy as np
    import pyautogui

    safe_region = {
        "left": int(region["left"]),
        "top": int(region["top"]),
        "width": int(region["width"]),
        "height": int(region["height"]),
    }

    for _ in range(2):
        try:
            with mss.mss() as sct:
                img = np.array(sct.grab(safe_region))

            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        except Exception as e:
            print(f"[Capture] mss grab failed: {type(e).__name__}: {e}")
            time.sleep(0.05)

    try:
        img = pyautogui.screenshot(
            region=(
                safe_region["left"],
                safe_region["top"],
                safe_region["width"],
                safe_region["height"],
            )
        )

        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    except Exception as e:
        print(f"[Capture] fallback screenshot failed: {type(e).__name__}: {e}")
        return None


def read_key():
    """
    读取 OpenCV 窗口里的按键。

    返回值：
    - q / Q / ESC：退出
    - r / R：重置主题识别
    - 其他：普通按键
    - 没按键：255
    """
    return cv2.waitKey(1) & 0xFF


def is_quit_key(key):
    return key in (ord("q"), ord("Q"), 27)


def is_reset_theme_key(key):
    return key in (ord("r"), ord("R"))


def resolve_project_path(path_value):
    path = Path(path_value)

    if path.is_absolute():
        return path

    return ROOT_DIR / path


def make_theme_recognizer(config):
    theme_cfg = config.get("theme", {})

    if not theme_cfg.get("enabled", True):
        return None, None

    signatures_path = theme_cfg.get(
        "signatures_path",
        "config/theme_signatures.yaml",
    )

    signatures_path = resolve_project_path(signatures_path)

    theme_recognizer = ThemeRecognizer(str(signatures_path))

    stable_theme_recognizer = StableThemeRecognizer(
        theme_recognizer,
        required_frames=theme_cfg.get("required_frames", 4),
        min_score=theme_cfg.get("min_score", 0.86),
        min_margin=theme_cfg.get("min_margin", 0.06),
        max_unknown_empty=theme_cfg.get("max_unknown_empty", 1),
    )

    return theme_recognizer, stable_theme_recognizer


THEME_DISPLAY_NAMES = {
    "综合": "Hybrid",
    "控制": "Control",
    "即死": "InstantKill",
    "输出": "Output",
    "倾斜": "Diagonal",
    "穿刺": "Piercing",
    "爆炸": "Explosion",
    "回复": "Recovery",
    "未知": "Unknown",
}


def theme_display_name(theme):
    if theme is None:
        return "None"

    theme = str(theme)

    if theme in THEME_DISPLAY_NAMES:
        return THEME_DISPLAY_NAMES[theme]

    # OpenCV putText cannot draw Chinese reliably.
    # If the theme name is already ASCII, show it directly.
    if theme.isascii():
        return theme

    return "UnknownTheme"


def make_locked_theme_result(locked_theme, last_theme_result=None):
    result = dict(last_theme_result or {})

    result["theme"] = locked_theme
    result["stable"] = True
    result["stable_theme"] = locked_theme

    result.setdefault("score", 1.0)
    result.setdefault("margin", 0.0)
    result.setdefault("unknown_empty_count", 0)
    result.setdefault("candidates", [])

    return result


def draw_theme_overlay(vis, theme_result, locked_theme):
    if theme_result is None:
        return vis

    h, w = vis.shape[:2]

    panel_x1 = 10
    panel_y1 = 10
    panel_x2 = min(w - 10, 420)
    panel_y2 = 105

    overlay = vis.copy()
    cv2.rectangle(
        overlay,
        (panel_x1, panel_y1),
        (panel_x2, panel_y2),
        (0, 0, 0),
        -1,
    )

    cv2.addWeighted(overlay, 0.45, vis, 0.55, 0, vis)

    theme = theme_result.get("theme")
    stable = theme_result.get("stable", False)
    score = theme_result.get("score", 0.0)
    margin = theme_result.get("margin", 0.0)
    unknown_empty_count = theme_result.get("unknown_empty_count", 0)

    theme_text = theme_display_name(theme)
    locked_text = theme_display_name(locked_theme)

    lines = [
        f"Theme: {theme_text}",
        f"Stable: {stable} | Locked: {locked_text}",
        f"Score: {score:.3f} | Margin: {margin:.3f}",
        f"Unknown/Empty: {unknown_empty_count}",
    ]

    y = panel_y1 + 22

    for line in lines:
        cv2.putText(
            vis,
            line,
            (panel_x1 + 10, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )
        y += 20

    return vis


def format_theme_log(theme_result, locked_theme):
    if theme_result is None:
        return ""

    candidates = theme_result.get("candidates", [])
    top_candidates = []

    for item in candidates[:3]:
        theme_cn = item.get("theme")
        top_candidates.append(
            f"{theme_display_name(theme_cn)}({theme_cn}):{item.get('score', 0):.3f}"
        )

    theme_cn = theme_result.get("theme")
    locked_cn = locked_theme

    return (
        f"[Theme] theme={theme_display_name(theme_cn)}({theme_cn}) | "
        f"stable={theme_result.get('stable')} | "
        f"locked={theme_display_name(locked_cn)}({locked_cn}) | "
        f"score={theme_result.get('score', 0):.3f} | "
        f"margin={theme_result.get('margin', 0):.3f} | "
        f"unknown_empty={theme_result.get('unknown_empty_count')} | "
        f"top={top_candidates}"
    )


EMPTY_CELL_LABELS = {
    "",
    "empty",
    "unknown",
    "none",
    "null",
    "background",
}


def iter_cells(cell_results):
    if cell_results is None:
        return

    if isinstance(cell_results, dict):
        for idx, item in enumerate(cell_results.values()):
            yield idx, item
        return

    if isinstance(cell_results, (list, tuple)):
        idx = 0

        for item in cell_results:
            if isinstance(item, (list, tuple)):
                for sub_item in item:
                    yield idx, sub_item
                    idx += 1
            else:
                yield idx, item
                idx += 1


def get_cell_field(cell, names, default=None):
    if isinstance(cell, dict):
        for name in names:
            if name in cell:
                return cell.get(name)

    for name in names:
        if hasattr(cell, name):
            return getattr(cell, name)

    return default


def get_cell_label(cell):
    label = get_cell_field(
        cell,
        [
            "locked_label",
            "corrected_label",
            "stable_label",
            "final_label",
            "label",
            "plant",
            "class_name",
            "name",
            "pred",
        ],
        default=None,
    )

    if label is None:
        return ""

    label = str(label).strip()

    if label.lower() in EMPTY_CELL_LABELS:
        return ""

    return label


def make_board_signature(cell_results):
    signature = []
    plant_count = 0

    for idx, cell in iter_cells(cell_results):
        row = get_cell_field(cell, ["row", "r"], default=None)
        col = get_cell_field(cell, ["col", "column", "c"], default=None)

        if row is None:
            row = idx // 9

        if col is None:
            col = idx % 9

        try:
            row = int(row)
            col = int(col)
        except Exception:
            row = idx // 9
            col = idx % 9

        label = get_cell_label(cell)

        if label:
            plant_count += 1

        signature.append((row, col, label))

    signature.sort()
    return tuple(signature), plant_count


def count_signature_changes(old_signature, new_signature):
    if old_signature is None or new_signature is None:
        return 0

    old_map = {(r, c): label for r, c, label in old_signature}
    new_map = {(r, c): label for r, c, label in new_signature}

    keys = set(old_map.keys()) | set(new_map.keys())

    changed = 0

    for key in keys:
        if old_map.get(key, "") != new_map.get(key, ""):
            changed += 1

    return changed




BLOOD_DEBUG_WINDOW_NAME = "IZE Blood Calculator Debug"
BLOOD_WINDOW_WIDTH = 620
BLOOD_WINDOW_HEIGHT = 520

BLOOD_MODE_KEYS = [
    "pole",
    "slow",
    "ladder",
    "football",
    "pole_ladder",
]

BLOOD_MODE_NAMES_CN = {
    "pole": "撑杆",
    "slow": "慢速",
    "ladder": "梯子",
    "football": "橄榄",
    "pole_ladder": "撑杆梯子",
}

BLOOD_MODE_NAMES_EN = {
    "pole": "Pole",
    "slow": "Slow",
    "ladder": "Ladder",
    "football": "Football",
    "pole_ladder": "Pole+Ladder",
}

BLOOD_ROW_NAMES_CN = ["第一行", "第二行", "第三行", "第四行", "第五行"]
BLOOD_ROW_NAMES_EN = ["Row 1", "Row 2", "Row 3", "Row 4", "Row 5"]

_PIL_READY = None
_PIL_FONT_CACHE = {}


def get_pil_font(size):
    """
    OpenCV 自带字体不能稳定显示中文。
    如果本机安装了 Pillow 且能找到 Windows 中文字体，就用 PIL 画中文；
    否则自动退回英文 OpenCV 文本。
    """
    global _PIL_READY

    if _PIL_READY is False:
        return None

    if size in _PIL_FONT_CACHE:
        return _PIL_FONT_CACHE[size]

    try:
        from PIL import ImageFont
    except Exception:
        _PIL_READY = False
        return None

    font_candidates = [
        "C:/Windows/Fonts/msyh.ttc",       # Microsoft YaHei
        "C:/Windows/Fonts/msyh.ttf",
        "C:/Windows/Fonts/simhei.ttf",     # SimHei
        "C:/Windows/Fonts/simsun.ttc",     # SimSun
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]

    for font_path in font_candidates:
        try:
            path = Path(font_path)
            if path.exists():
                font = ImageFont.truetype(str(path), size=size)
                _PIL_FONT_CACHE[size] = font
                _PIL_READY = True
                return font
        except Exception:
            continue

    _PIL_READY = False
    return None


def _has_cjk(text):
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(text))


def _text_size(text, font_size=22, thickness=1, fallback_text=None):
    text = str(text)
    fallback_text = str(fallback_text if fallback_text is not None else text)

    font = get_pil_font(font_size) if _has_cjk(text) else None

    if font is not None:
        try:
            from PIL import Image, ImageDraw
            dummy = Image.new("RGB", (10, 10), (255, 255, 255))
            draw = ImageDraw.Draw(dummy)
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            pass

    scale = max(0.35, font_size / 32.0)
    (w, h), _ = cv2.getTextSize(
        fallback_text,
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        thickness,
    )
    return w, h


def draw_ui_text(
    image,
    text,
    x,
    y,
    font_size=22,
    color=(0, 0, 0),
    bold=False,
    fallback_text=None,
    anchor="left",
):
    """
    在 BGR OpenCV 图像上画文本。
    - x/y 是文本左上角坐标；
    - anchor="center" 时，x 表示中心点；
    - color 是 BGR。
    """
    text = str(text)
    fallback_text = str(fallback_text if fallback_text is not None else text)
    thickness = 2 if bold else 1

    font = get_pil_font(font_size) if _has_cjk(text) else None

    if font is not None:
        try:
            from PIL import Image, ImageDraw

            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            draw = ImageDraw.Draw(pil_img)
            bbox = draw.textbbox((0, 0), text, font=font)
            width = bbox[2] - bbox[0]

            draw_x = int(x - width / 2) if anchor == "center" else int(x)
            draw_y = int(y)
            rgb_color = (int(color[2]), int(color[1]), int(color[0]))

            if bold:
                for dx, dy in [(0, 0), (1, 0), (0, 1)]:
                    draw.text((draw_x + dx, draw_y + dy), text, font=font, fill=rgb_color)
            else:
                draw.text((draw_x, draw_y), text, font=font, fill=rgb_color)

            image[:, :] = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            return image

        except Exception:
            pass

    # Fallback: OpenCV 英文文本。
    draw_text = fallback_text
    scale = max(0.35, font_size / 32.0)
    (w, h), baseline = cv2.getTextSize(
        draw_text,
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        thickness,
    )
    draw_x = int(x - w / 2) if anchor == "center" else int(x)
    draw_y = int(y + h)

    cv2.putText(
        image,
        draw_text,
        (draw_x, draw_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )
    return image


def normalize_blood_label(label):
    if label is None:
        return "empty"

    label = str(label).strip()

    if not label or label.lower() in EMPTY_CELL_LABELS:
        return "empty"

    return label


def extract_ize_board(board, rows=5, cols=5):
    """
    从 BoardRecognizer / BoardCorrector 的 board 中取 IZE 前 5 列。
    只把最终植物 label 传给算血器，避免算血器依赖 CV 细节。
    """
    ize_board = []

    for r in range(rows):
        lane = []

        for c in range(cols):
            label = "empty"

            try:
                cell = board[r][c]
                if isinstance(cell, dict):
                    label = get_cell_label(cell) or "empty"
                else:
                    label = normalize_blood_label(cell)
            except Exception:
                label = "empty"

            lane.append(label)

        ize_board.append(lane)

    return ize_board


def calculate_blood_table(blood_calculator, ize_board):
    if blood_calculator is None:
        return None

    try:
        return blood_calculator.calculate_board(ize_board, explain=False)
    except TypeError:
        # 兼容旧版 calculate_board(board) 接口。
        return blood_calculator.calculate_board(ize_board)


def get_blood_row_result(blood_table, row_idx):
    if blood_table is None:
        return None

    if isinstance(blood_table, (list, tuple)):
        if 0 <= row_idx < len(blood_table):
            return blood_table[row_idx]
        return None

    if isinstance(blood_table, dict):
        keys = [
            row_idx,
            str(row_idx),
            row_idx + 1,
            str(row_idx + 1),
            f"row{row_idx}",
            f"row_{row_idx}",
            f"row{row_idx + 1}",
            f"row_{row_idx + 1}",
            BLOOD_ROW_NAMES_CN[row_idx],
            BLOOD_ROW_NAMES_EN[row_idx],
        ]

        for key in keys:
            if key in blood_table:
                return blood_table[key]

    return None


def get_blood_values(row_result):
    if row_result is None:
        return {}

    if isinstance(row_result, dict):
        values = row_result.get("values")
        if isinstance(values, dict):
            return values
        return row_result

    return {}


def get_blood_status_map(row_result):
    if isinstance(row_result, dict):
        status = row_result.get("status")
        if isinstance(status, dict):
            return status

        highlight = row_result.get("highlight")
        if isinstance(highlight, dict):
            return highlight

    return {}


def get_blood_mode_value(row_result, mode_key):
    values = get_blood_values(row_result)

    aliases = {
        "pole": ["pole", "pv", "pole_vaulting", "撑杆"],
        "slow": ["slow", "normal", "slow_zombie", "慢速"],
        "ladder": ["ladder", "ladder_zombie", "梯子"],
        "football": ["football", "football_zombie", "gargantuar", "橄榄"],
        "pole_ladder": [
            "pole_ladder",
            "pole+ladder",
            "pole_ladder_zombie",
            "pvl",
            "撑杆梯子",
        ],
    }

    for key in aliases.get(mode_key, [mode_key]):
        if isinstance(values, dict) and key in values:
            return values.get(key)

    return None


def format_blood_value(value):
    if value is None:
        return ""

    if isinstance(value, dict):
        armor = value.get("armor", value.get("accessory", value.get("ladder")))
        body = value.get("body", value.get("zombie"))

        if armor is not None and body is not None:
            return f"{armor}+{body}"

        total = value.get("total")
        if total is not None:
            return str(total)

    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return f"{value[0]}+{value[1]}"

    return str(value)


def normalize_blood_status(value):
    if value is None:
        return 0

    if isinstance(value, bool):
        return 1 if value else 0

    if isinstance(value, (int, float)):
        if value > 0:
            return 1
        if value < 0:
            return -1
        return 0

    text = str(value).lower()

    # 先判断负面状态，避免 "not_recommended" 被 recommend 误判为推荐。
    if any(k in text for k in ["bad", "not", "avoid", "disabled", "不推荐"]):
        return -1

    if any(k in text for k in ["recommend", "good", "highlight", "best", "推荐"]):
        return 1

    return 0


def get_blood_mode_status(row_result, mode_key):
    status_map = get_blood_status_map(row_result)

    aliases = {
        "pole": ["pole", "pv", "pole_vaulting", "撑杆"],
        "slow": ["slow", "normal", "slow_zombie", "慢速"],
        "ladder": ["ladder", "ladder_zombie", "梯子"],
        "football": ["football", "football_zombie", "橄榄"],
        "pole_ladder": ["pole_ladder", "pole+ladder", "pvl", "撑杆梯子"],
    }

    for key in aliases.get(mode_key, [mode_key]):
        if key in status_map:
            return normalize_blood_status(status_map.get(key))

    return 0


def draw_blood_table_window(
    blood_table,
    ize_board=None,
    locked_theme=None,
    error_text=None,
):
    """
    单独绘制一个算血器 debug 窗口。

    设计目标：
    - 终端不刷算血结果，避免信息太快；
    - OpenCV 窗口每帧刷新，类似原 IZE 血量计算器 UI；
    - 推荐项灰底加粗，不推荐项用括号和灰字。
    """
    canvas = np.full(
        (BLOOD_WINDOW_HEIGHT, BLOOD_WINDOW_WIDTH, 3),
        245,
        dtype=np.uint8,
    )

    # 顶部标题栏样式。
    cv2.rectangle(canvas, (0, 0), (BLOOD_WINDOW_WIDTH, 56), (238, 238, 238), -1)
    cv2.line(canvas, (0, 56), (BLOOD_WINDOW_WIDTH, 56), (225, 225, 225), 1)

    draw_ui_text(
        canvas,
        "IZE血量计算器 Debug",
        BLOOD_WINDOW_WIDTH // 2,
        18,
        font_size=22,
        color=(60, 60, 60),
        bold=True,
        fallback_text="IZE Blood Calculator Debug",
        anchor="center",
    )

    if locked_theme is None:
        theme_cn = "未锁定"
        theme_en = "Unlocked"
    else:
        theme_cn = str(locked_theme)
        theme_en = theme_display_name(locked_theme)

    subtitle_cn = f"当前识别算血结果    主题：{theme_cn}"
    subtitle_en = f"Current Blood Result    Theme: {theme_en}"

    draw_ui_text(
        canvas,
        subtitle_cn,
        BLOOD_WINDOW_WIDTH // 2,
        78,
        font_size=21,
        color=(0, 0, 0),
        bold=True,
        fallback_text=subtitle_en,
        anchor="center",
    )

    if error_text:
        draw_ui_text(
            canvas,
            "算血器不可用",
            BLOOD_WINDOW_WIDTH // 2,
            155,
            font_size=26,
            color=(40, 40, 220),
            bold=True,
            fallback_text="Blood calculator unavailable",
            anchor="center",
        )
        draw_ui_text(
            canvas,
            str(error_text)[:90],
            30,
            210,
            font_size=17,
            color=(70, 70, 70),
            fallback_text=str(error_text)[:90],
        )
        return canvas

    header_y = 132
    row_start_y = 188
    row_gap = 72

    row_label_x = 22
    col_centers = {
        "pole": 142,
        "slow": 245,
        "ladder": 350,
        "football": 455,
        "pole_ladder": 555,
    }

    for mode_key in BLOOD_MODE_KEYS:
        draw_ui_text(
            canvas,
            BLOOD_MODE_NAMES_CN[mode_key],
            col_centers[mode_key],
            header_y,
            font_size=22,
            color=(0, 0, 0),
            bold=True,
            fallback_text=BLOOD_MODE_NAMES_EN[mode_key],
            anchor="center",
        )

    # 表格行。
    for row_idx in range(5):
        y = row_start_y + row_idx * row_gap

        draw_ui_text(
            canvas,
            BLOOD_ROW_NAMES_CN[row_idx],
            row_label_x,
            y,
            font_size=22,
            color=(0, 0, 0),
            bold=True,
            fallback_text=BLOOD_ROW_NAMES_EN[row_idx],
        )

        row_result = get_blood_row_result(blood_table, row_idx)

        for mode_key in BLOOD_MODE_KEYS:
            raw_value = get_blood_mode_value(row_result, mode_key)
            value_text = format_blood_value(raw_value)
            status = get_blood_mode_status(row_result, mode_key)

            if not value_text:
                continue

            display_text = value_text
            text_color = (0, 0, 0)
            bold = False

            text_w, text_h = _text_size(
                display_text,
                font_size=23,
                thickness=2 if status > 0 else 1,
            )

            cx = col_centers[mode_key]
            cell_w = max(68, text_w + 30)
            cell_h = 50

            if status > 0:
                x1 = int(cx - cell_w / 2)
                y1 = int(y - 13)
                x2 = int(cx + cell_w / 2)
                y2 = int(y1 + cell_h)
                cv2.rectangle(canvas, (x1, y1), (x2, y2), (210, 210, 210), -1)
                bold = True
            elif status < 0:
                display_text = f"({value_text})"
                text_color = (160, 160, 160)

            draw_ui_text(
                canvas,
                display_text,
                cx,
                y,
                font_size=23,
                color=text_color,
                bold=bold,
                fallback_text=display_text,
                anchor="center",
            )

    # 底部显示送入算血器的前 5 列，便于判断 CV 输入是否对。
    footer_y = BLOOD_WINDOW_HEIGHT - 58
    cv2.line(canvas, (0, footer_y - 14), (BLOOD_WINDOW_WIDTH, footer_y - 14), (225, 225, 225), 1)

    if ize_board is not None:
        lane_texts = []
        for r, lane in enumerate(ize_board[:5]):
            compact = ",".join([str(x)[:3] for x in lane[:5]])
            lane_texts.append(f"R{r + 1}:{compact}")
        board_text = " | ".join(lane_texts)
    else:
        board_text = "No board yet"

    draw_ui_text(
        canvas,
        "输入前5列：",
        18,
        footer_y,
        font_size=16,
        color=(80, 80, 80),
        fallback_text="Input c1-c5:",
    )
    draw_ui_text(
        canvas,
        board_text[:120],
        120,
        footer_y,
        font_size=15,
        color=(80, 80, 80),
        fallback_text=board_text[:120],
    )

    return canvas


def main():
    config = load_config()

    print("Loading board recognizer...")
    board_recognizer = BoardRecognizer(config)

    print("Loading theme recognizer...")
    theme_recognizer, stable_theme_recognizer = make_theme_recognizer(config)

    print("Loading board corrector...")
    board_corrector = ThemeBoardCorrector(config)

    blood_cfg = config.get("blood_calculator", {})
    blood_debug_enabled = blood_cfg.get("debug_window_enabled", True)
    blood_calculator = None
    blood_import_error_text = None

    if blood_debug_enabled:
        if IZEBloodCalculator is None:
            blood_import_error_text = (
                "Failed to import core.ize_blood_calculator. "
                f"{type(IZEBloodCalculator_IMPORT_ERROR).__name__}: "
                f"{IZEBloodCalculator_IMPORT_ERROR}"
            )
            print(f"[BloodCalculator] {blood_import_error_text}")
        else:
            print("Loading IZE blood calculator...")
            blood_calculator = IZEBloodCalculator()


    theme_cfg = config.get("theme", {})
    theme_max_col = theme_cfg.get("max_col", 4)

    theme_log_until_locked = theme_cfg.get("log_until_locked", True)
    theme_log_after_locked = theme_cfg.get("log_after_locked", False)
    theme_check_after_locked = theme_cfg.get("check_after_locked", False)

    theme_reset_on_round_change = theme_cfg.get("reset_on_round_change", True)
    round_change_min_changed_cells = theme_cfg.get("round_change_min_changed_cells", 8)
    round_change_min_plants = theme_cfg.get("round_change_min_plants", 8)
    round_change_cooldown = theme_cfg.get("round_change_cooldown", 1.0)

    locked_theme = None
    last_theme_result = None
    last_theme_log_text = None
    last_theme_log_time = 0

    last_corrector_log_text = None

    last_board_signature = None
    last_theme_reset_time = 0


    win = find_pvz_window(config)
    hwnd = win["hwnd"]

    print("\nSelected PVZ window:")
    print(f"title: {win['title']!r}")

    bring_window_to_front(hwnd)

    print("\nDebug board recognition started.")
    print("Press Q or ESC to quit.")
    print("Press R to reset locked theme.")

    if blood_debug_enabled:
        cv2.namedWindow(BLOOD_DEBUG_WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(
            BLOOD_DEBUG_WINDOW_NAME,
            BLOOD_WINDOW_WIDTH,
            BLOOD_WINDOW_HEIGHT,
        )
        try:
            initial_region = get_client_rect_on_screen(hwnd)
            cv2.moveWindow(
                BLOOD_DEBUG_WINDOW_NAME,
                initial_region["left"] + initial_region["width"] + 20,
                initial_region["top"],
            )
        except Exception:
            pass


    last_window_guard_reason = None
    last_window_guard_log_time = 0

    while True:
        region = get_client_rect_on_screen(hwnd)

        occluded, reason = is_capture_region_occluded(hwnd, region)

        if occluded:
            now = time.time()

            if (
                reason != last_window_guard_reason
                or now - last_window_guard_log_time > 1.0
            ):
                print(f"[WindowGuard] Freeze recognition: {reason}")
                last_window_guard_reason = reason
                last_window_guard_log_time = now

            time.sleep(0.05)

            key = read_key()

            if is_quit_key(key):
                break

            continue

        frame = grab_region(region)

        if frame is None:
            time.sleep(0.05)

            key = read_key()

            if is_quit_key(key):
                break

            continue

        cell_results, board = board_recognizer.recognize(frame)

        now = time.time()

        if theme_reset_on_round_change:
            board_signature, board_plant_count = make_board_signature(cell_results)

            if locked_theme is not None and last_board_signature is not None:
                changed_cells = count_signature_changes(
                    last_board_signature,
                    board_signature,
                )

                if (
                    board_plant_count >= round_change_min_plants
                    and changed_cells >= round_change_min_changed_cells
                    and now - last_theme_reset_time >= round_change_cooldown
                ):
                    if stable_theme_recognizer is not None:
                        stable_theme_recognizer.reset()

                    print(
                        "[Theme] Board changed: "
                        f"changed_cells={changed_cells}, "
                        f"plants={board_plant_count}. "
                        "Reset theme lock for new round."
                    )

                    locked_theme = None
                    last_theme_result = None
                    last_theme_log_text = None
                    last_theme_reset_time = now

            last_board_signature = board_signature

        theme_result = last_theme_result

        if stable_theme_recognizer is not None:
            should_log_theme = False

            if locked_theme is None:
                theme_result = stable_theme_recognizer.update(
                    cell_results,
                    max_col=theme_max_col,
                )
                last_theme_result = theme_result
                should_log_theme = theme_log_until_locked

                if theme_result.get("stable"):
                    locked_theme = theme_result.get("stable_theme")
                    theme_result = make_locked_theme_result(
                        locked_theme,
                        theme_result,
                    )
                    last_theme_result = theme_result

                    print(
                        f"\n[Theme] Locked theme: "
                        f"{theme_display_name(locked_theme)}({locked_theme})\n"
                    )

            else:
                if theme_check_after_locked:
                    theme_result = theme_recognizer.recognize(
                        cell_results,
                        max_col=theme_max_col,
                    )
                    theme_result["stable"] = True
                    theme_result["stable_theme"] = locked_theme
                    last_theme_result = theme_result
                else:
                    theme_result = make_locked_theme_result(
                        locked_theme,
                        last_theme_result,
                    )
                    last_theme_result = theme_result

                should_log_theme = theme_log_after_locked

            if should_log_theme:
                theme_log_text = format_theme_log(theme_result, locked_theme)

                if (
                    theme_log_text != last_theme_log_text
                    or now - last_theme_log_time >= 1.0
                ):
                    print(theme_log_text)
                    last_theme_log_text = theme_log_text
                    last_theme_log_time = now

        correction_info = None
        memory_correction_info = None

        if locked_theme is not None:
            # 先修正 BoardRecognizer 内部 memory。
            # 这样下一帧开始，memory 自己就是修正后的结果。
            if getattr(board_recognizer, "memory_initialized", False):
                memory_correction_info = board_corrector.correct_board_memory(
                    board_recognizer.board_memory,
                    locked_theme,
                    max_col=theme_max_col,
                )

            # 再修正当前这一帧的 cell_results / board，
            # 这样当前 debug 窗口和后续策略立刻能用修正后的结果。
            cell_results, board, correction_info = board_corrector.correct(
                cell_results,
                board,
                locked_theme,
                max_col=theme_max_col,
            )

            log_parts = []

            if (
                memory_correction_info is not None
                and memory_correction_info.get("changed_count", 0) > 0
            ):
                log_parts.append(
                    "[BoardCorrector] memory fixed "
                    f"{memory_correction_info['changed_count']} cells"
                )

            if (
                correction_info is not None
                and correction_info.get("changed_count", 0) > 0
            ):
                changes = correction_info.get("changes", [])

                change_text = ", ".join(
                    [
                        f"r{c['row'] + 1}c{c['col'] + 1}:"
                        f"{c['from']}->{c['to']}"
                        for c in changes[:8]
                    ]
                )

                log_parts.append(
                    "[BoardCorrector] frame fixed "
                    f"{correction_info['changed_count']} cells | "
                    f"{change_text}"
                )

            if correction_info is not None:
                if (
                    correction_info.get("changed_count", 0) > 0
                    and not correction_info.get("signature_matched_after", False)
                ):
                    log_parts.append(
                        "[BoardCorrector] warning: signature still mismatched "
                        f"after correction. after={correction_info.get('after_counts')}, "
                        f"expected={correction_info.get('expected_counts')}"
                    )

            if log_parts:
                corrector_log_text = "\n".join(log_parts)

                if corrector_log_text != last_corrector_log_text:
                    print(corrector_log_text)
                    last_corrector_log_text = corrector_log_text


        if blood_debug_enabled:
            blood_error_text = blood_import_error_text
            blood_table = None
            ize_board = None

            if blood_calculator is not None:
                try:
                    ize_board = extract_ize_board(board, rows=5, cols=5)
                    blood_table = calculate_blood_table(
                        blood_calculator,
                        ize_board,
                    )
                except Exception as e:
                    blood_error_text = (
                        f"{type(e).__name__}: {e}"
                    )

            blood_vis = draw_blood_table_window(
                blood_table,
                ize_board=ize_board,
                locked_theme=locked_theme,
                error_text=blood_error_text,
            )
            cv2.imshow(BLOOD_DEBUG_WINDOW_NAME, blood_vis)


        vis = draw_board_results(
            frame,
            cell_results,
            show_confidence=True,
        )

        vis = draw_theme_overlay(
            vis,
            theme_result,
            locked_theme,
        )

        cv2.imshow("PVZ Board Recognition Debug", vis)


        key = read_key()

        if is_reset_theme_key(key):
            if stable_theme_recognizer is not None:
                stable_theme_recognizer.reset()

            locked_theme = None
            last_theme_result = None
            last_theme_log_text = None
            last_board_signature = None
            last_corrector_log_text = None
            last_theme_reset_time = time.time()
            print("[Theme] Reset locked theme.")


        if is_quit_key(key):
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
