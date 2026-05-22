import time
import cv2
import yaml
import mss
import numpy as np
import ctypes
import pyautogui
from ctypes import wintypes
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent

CONFIG_PATH = ROOT_DIR / "config" / "settings.yaml"
LOCAL_CONFIG_PATH = ROOT_DIR / "config" / "local_settings.yaml"

TEMPLATE_DIR = ROOT_DIR / "assets" / "templates"
OUTPUT_DIR = TEMPLATE_DIR / "plants_raw"

PREVIEW_PATH = TEMPLATE_DIR / "grid_preview.png"
FULL_FRAME_PATH = TEMPLATE_DIR / "pvz_full_frame.png"
RESUME_DEBUG_PATH = TEMPLATE_DIR / "resume_detection_debug.png"


user32 = ctypes.windll.user32


# 让 Windows 返回真实像素坐标，避免 DPI 缩放导致坐标错位
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.03


def imwrite_unicode(path, image):
    """
    Windows 中文路径安全保存图片。
    不使用 cv2.imwrite，因为中文路径下可能失败。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    ext = path.suffix
    if not ext:
        ext = ".png"

    success, encoded = cv2.imencode(ext, image)

    if not success:
        raise RuntimeError(f"cv2.imencode failed: {path}")

    encoded.tofile(str(path))

    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"Image save failed: {path}")

    return True


def deep_merge(base, override):
    """
    递归合并配置。
    local_settings.yaml 会覆盖 settings.yaml。
    """
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
    path = Path(path)

    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config():
    config = load_yaml(CONFIG_PATH)
    local_config = load_yaml(LOCAL_CONFIG_PATH)

    if local_config:
        config = deep_merge(config, local_config)

    return config


def get_window_title(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)

    if length <= 0:
        return ""

    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)

    return buffer.value.strip()


def get_client_rect_on_screen(hwnd):
    """
    获取窗口客户区在屏幕上的绝对坐标。
    不包含标题栏和边框。
    """
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

        region = get_client_rect_on_screen(hwnd)

        windows.append(
            {
                "hwnd": hwnd,
                "title": title,
                "region": region,
            }
        )

        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)

    return windows


def find_pvz_window(config):
    """
    根据 settings.yaml 里的 window.title_keywords 找 PVZ 窗口。
    """
    window_cfg = config.get("window", {})
    title_keywords = window_cfg.get("title_keywords", [])

    if not title_keywords:
        title_keywords = [
            "Plants vs. Zombies",
            "植物大战僵尸",
        ]

    bad_words = [
        "visual studio code",
        "vscode",
        "pvzagent",
        "extract_plant_cells",
        "powershell",
        "cmd.exe",
        "terminal",
        "grid preview",
    ]

    windows = enum_visible_windows()

    print("\nVisible windows:")
    for win in windows:
        region = win["region"]
        print(
            f"- title={win['title']!r}, "
            f"left={region['left']}, top={region['top']}, "
            f"width={region['width']}, height={region['height']}"
        )

    exact_candidates = []
    contains_candidates = []

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

            if title_lower == keyword_lower:
                exact_candidates.append(win)

            elif keyword_lower in title_lower:
                contains_candidates.append(win)

    candidates = exact_candidates or contains_candidates

    print("\nPVZ window candidates:")
    for win in candidates:
        print(f"- title={win['title']!r}, region={win['region']}")

    if not candidates:
        raise RuntimeError(
            "没有找到 Plants vs. Zombies 窗口。\n"
            "请确认游戏已打开，并且 config/settings.yaml 里的 window.title_keywords 不要写 PVZAgent。"
        )

    candidates.sort(
        key=lambda w: w["region"]["width"] * w["region"]["height"],
        reverse=True,
    )

    return candidates[0]


def bring_window_to_front(hwnd):
    """
    尝试把 PVZ 窗口恢复并切到前台。
    """
    SW_RESTORE = 9

    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.15)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.15)
    except Exception:
        pass


def grab_region(region):
    """
    使用 mss 截取指定屏幕区域。
    """
    with mss.mss() as sct:
        img = np.array(sct.grab(region))

    frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return frame


def find_resume_game_center(frame, save_debug=True):
    """
    精确寻找暂停菜单里的 RESUME GAME 按钮。

    重点：
    - 不再全画面找绿色
    - 只在画面中间偏下的按钮区域找
    - 避免误选右下角进度条、Menu、植物等绿色区域

    返回：
    - (x, y)：相对于 PVZ 客户区的点击坐标
    - None：没有找到
    """
    h, w = frame.shape[:2]

    # 只搜索暂停菜单下方按钮区域
    # 根据你的截图，Resume Game 在客户区中间偏下：
    # x 约 32% ~ 68%
    # y 约 66% ~ 88%
    roi_x1 = int(w * 0.32)
    roi_x2 = int(w * 0.68)
    roi_y1 = int(h * 0.66)
    roi_y2 = int(h * 0.88)

    roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]

    if roi.size == 0:
        return None

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # Resume Game 文字是亮绿色
    lower_green = np.array([35, 70, 70], dtype=np.uint8)
    upper_green = np.array([95, 255, 255], dtype=np.uint8)

    mask = cv2.inRange(hsv, lower_green, upper_green)

    # 把绿色文字连成横向块
    kernel_open = np.ones((2, 2), np.uint8)
    kernel_close = np.ones((5, 15), np.uint8)

    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close, iterations=2)
    mask = cv2.dilate(mask, kernel_open, iterations=1)

    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    candidates = []

    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cv2.contourArea(cnt)

        abs_x = roi_x1 + x
        abs_y = roi_y1 + y
        center_x = abs_x + cw / 2
        center_y = abs_y + ch / 2

        # 过滤噪声
        if area < 20:
            continue

        # RESUME GAME 是一条较长的绿色文字
        if cw < 60:
            continue

        if ch < 8:
            continue

        if ch > 45:
            continue

        # 必须靠近画面中心，避免右下角误检
        if not (w * 0.38 <= center_x <= w * 0.62):
            continue

        # 必须在按钮区域附近
        if not (h * 0.68 <= center_y <= h * 0.84):
            continue

        center_distance = abs(center_x - w * 0.5)
        score = cw * 3 + area - center_distance * 2

        candidates.append(
            {
                "box": (abs_x, abs_y, cw, ch),
                "center": (int(center_x), int(center_y)),
                "score": score,
                "area": area,
            }
        )

    debug_vis = frame.copy()

    # 蓝框：搜索区域
    cv2.rectangle(
        debug_vis,
        (roi_x1, roi_y1),
        (roi_x2, roi_y2),
        (255, 0, 0),
        2,
    )

    # 绿框：候选区域
    for item in candidates:
        x, y, cw, ch = item["box"]
        score = item["score"]

        cv2.rectangle(
            debug_vis,
            (int(x), int(y)),
            (int(x + cw), int(y + ch)),
            (0, 255, 0),
            2,
        )

        cv2.putText(
            debug_vis,
            f"{int(score)}",
            (int(x), max(0, int(y) - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 255, 0),
            1,
        )

    if save_debug:
        imwrite_unicode(RESUME_DEBUG_PATH, debug_vis)

    if not candidates:
        return None

    candidates.sort(key=lambda item: item["score"], reverse=True)
    best = candidates[0]

    text_x, text_y = best["center"]

    # 不点文字正中心，点按钮中间区域。
    # 按你当前截图，按钮可点击区域比绿色文字略低一点。
    click_x = text_x
    click_y = text_y + int(h * 0.015)

    return int(click_x), int(click_y)


def click_resume_game_auto(region):
    """
    自动点击 Resume Game。
    这版只点击一次，不再多点乱点。
    """
    frame_before = grab_region(region)

    center = find_resume_game_center(frame_before, save_debug=True)

    if center is None:
        print("\nResume Game not detected in precise button area.")
        print("Detection debug image saved to:")
        print(RESUME_DEBUG_PATH)
        return False

    local_x, local_y = center
    screen_x = region["left"] + local_x
    screen_y = region["top"] + local_y

    print(
        f"\nDetected Resume Game button: "
        f"local=({local_x}, {local_y}), screen=({screen_x}, {screen_y})"
    )

    # 只点击一次，避免乱点
    pyautogui.moveTo(screen_x, screen_y, duration=0.05)
    time.sleep(0.05)
    pyautogui.click(screen_x, screen_y)
    time.sleep(0.6)

    # 验证是否还在暂停菜单
    frame_after = grab_region(region)
    still_has_resume = find_resume_game_center(frame_after, save_debug=False)

    if still_has_resume is None:
        print("Resume click verified: pause menu disappeared.")
        return True

    print("Clicked Resume Game, but pause menu still seems visible.")
    return False


def grab_pvz_frame(config, try_resume=True):
    """
    找到 PVZ 窗口，自动点击 Resume Game，然后截图。
    """
    win = find_pvz_window(config)

    hwnd = win["hwnd"]
    title = win["title"]

    bring_window_to_front(hwnd)

    region = get_client_rect_on_screen(hwnd)

    print("\nSelected PVZ window:")
    print(f"title={title!r}")
    print(f"region={region}")

    if try_resume:
        clicked = click_resume_game_auto(region)

        if clicked:
            print("Resume Game clicked automatically.")
        else:
            print("Could not verify Resume Game click. Continuing with screenshot.")

        bring_window_to_front(hwnd)
        region = get_client_rect_on_screen(hwnd)

    time.sleep(0.25)

    frame = grab_region(region)

    return frame, region


def get_grid_config(config):
    if "grid" not in config:
        raise KeyError("settings.yaml 里缺少 grid 配置")

    grid = config["grid"]

    required = [
        "rows",
        "cols",
        "board_left",
        "board_top",
        "board_width",
        "board_height",
    ]

    for key in required:
        if key not in grid:
            raise KeyError(f"settings.yaml 里缺少 grid.{key}")

    return grid


def draw_grid_preview(frame, config):
    grid = get_grid_config(config)

    rows = int(grid["rows"])
    cols = int(grid["cols"])

    board_left = int(grid["board_left"])
    board_top = int(grid["board_top"])
    board_width = int(grid["board_width"])
    board_height = int(grid["board_height"])

    frame_h, frame_w = frame.shape[:2]

    print("\nCaptured frame size:")
    print(f"width={frame_w}, height={frame_h}")

    print("\nGrid config:")
    print(f"board_left={board_left}")
    print(f"board_top={board_top}")
    print(f"board_width={board_width}")
    print(f"board_height={board_height}")

    if board_left + board_width > frame_w or board_top + board_height > frame_h:
        print("\nWARNING:")
        print("你的 grid 范围超出了截图画面。")
        print("说明当前 PVZ 窗口大小和你调 grid 时的窗口大小不一致。")

    cell_w = board_width / cols
    cell_h = board_height / rows

    vis = frame.copy()

    for row in range(rows):
        for col in range(cols):
            x1 = int(board_left + col * cell_w)
            y1 = int(board_top + row * cell_h)
            x2 = int(board_left + (col + 1) * cell_w)
            y2 = int(board_top + (row + 1) * cell_h)

            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 1)

            cv2.putText(
                vis,
                f"{row},{col}",
                (x1 + 4, y1 + 16),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 255, 0),
                1,
            )

    imwrite_unicode(PREVIEW_PATH, vis)

    return vis


def crop_grid_cells(frame, config):
    """
    按 grid 配置切格子。
    每次运行都会保存到新的 batch_xxx 文件夹。
    """
    grid = get_grid_config(config)

    rows = int(grid["rows"])
    cols = int(grid["cols"])

    board_left = int(grid["board_left"])
    board_top = int(grid["board_top"])
    board_width = int(grid["board_width"])
    board_height = int(grid["board_height"])

    # 只保存 c0-c4；不要改 settings.yaml 里的 cols=9
    save_cols = min(cols, 5)

    cell_w = board_width / cols
    cell_h = board_height / rows

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    batch_dir = OUTPUT_DIR / f"batch_{timestamp}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    saved_count = 0

    for row in range(rows):
        for col in range(5):
            x1 = int(board_left + col * cell_w)
            y1 = int(board_top + row * cell_h)
            x2 = int(board_left + (col + 1) * cell_w)
            y2 = int(board_top + (row + 1) * cell_h)

            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(frame.shape[1], x2)
            y2 = min(frame.shape[0], y2)

            cell_img = frame[y1:y2, x1:x2]

            if cell_img.size == 0:
                print(f"Skip empty crop: row={row}, col={col}")
                continue

            output_path = batch_dir / f"cell_r{row}_c{col}.png"
            imwrite_unicode(output_path, cell_img)

            print(f"Saved: {output_path}")
            saved_count += 1

    print(f"\nSaved {saved_count} cell images to:")
    print(batch_dir)

    actual_files = sorted(batch_dir.glob("cell_r*_c*.png"))

    print(f"\nActual files found after saving: {len(actual_files)}")
    for path in actual_files[:5]:
        print(f"- {path}")

    if len(actual_files) == 0:
        raise RuntimeError("保存后 batch 文件夹里没有图片。")



def save_full_frame(frame):
    imwrite_unicode(FULL_FRAME_PATH, frame)
    print("\nFull PVZ frame saved to:")
    print(FULL_FRAME_PATH)


def main():
    config = load_config()

    print("Loading config...")
    print("Capturing PVZ window directly...")

    frame, region = grab_pvz_frame(config, try_resume=True)

    save_full_frame(frame)

    preview = draw_grid_preview(frame, config)

    print("\nGrid preview saved to:")
    print(PREVIEW_PATH)

    print("\nResume detection debug saved to:")
    print(RESUME_DEBUG_PATH)

    print("\n操作说明：")
    print("1. 如果预览网格正确，点击预览窗口，然后按 S 保存 45 个格子")
    print("2. 如果不想保存，按 ESC 退出")
    print("3. 注意：按键要在 OpenCV 预览窗口里按，不是在 PowerShell 里输入")
    print("4. 图片会保存到 assets/templates/plants_raw/")

    cv2.imshow("PVZ Grid Preview - Press S to save cells, ESC to cancel", preview)

    while True:
        key = cv2.waitKey(0) & 0xFF

        if key in (ord("s"), ord("S")):
            cv2.destroyAllWindows()
            crop_grid_cells(frame, config)
            print("\nDone.")
            return

        if key == 27:
            cv2.destroyAllWindows()
            print("Cancelled.")
            return


if __name__ == "__main__":
    main()
