import time
import yaml
import threading
from pathlib import Path

from pynput import keyboard

from core.window_finder import PVZWindowFinder
from core.capture import PVZCapture
from core.grid import PVZGrid
from core.plant_detector import PlantDetector
from core.card_detector import CardDetector
from core.game_state import GameState
from core.decision import IZombieDecisionMaker
from core.controller import PVZController
from utils.debug_view import DebugView


ROOT_DIR = Path(__file__).resolve().parent


class RuntimeControl:
    """
    控制程序运行状态。

    默认状态：
    - 只 debug
    - 不点击
    - 不按键
    - 不执行任何游戏操作

    快捷键：
    - F8  : 开始 / 暂停自动操作
    - F9  : 立刻停止自动操作，但继续 debug
    - F10 : 退出整个程序
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.auto_enabled = False
        self.quit_requested = False

    def is_auto_enabled(self):
        with self._lock:
            return self.auto_enabled

    def should_quit(self):
        with self._lock:
            return self.quit_requested

    def toggle_auto(self):
        with self._lock:
            self.auto_enabled = not self.auto_enabled
            return self.auto_enabled

    def stop_auto(self):
        with self._lock:
            self.auto_enabled = False

    def request_quit(self):
        with self._lock:
            self.auto_enabled = False
            self.quit_requested = True


def start_hotkey_listener(runtime_control, controller=None):
    """
    启动全局快捷键监听。

    注意：
    这个监听是全局的，所以即使当前焦点在 PVZ、VS Code、终端，
    F8 / F9 / F10 也应该能响应。
    """

    def on_press(key):
        try:
            if key == keyboard.Key.f8:
                enabled = runtime_control.toggle_auto()

                if enabled:
                    print("\n[HOTKEY] F8: AUTO MODE ON")
                    print("[AUTO] The agent is now allowed to click / operate.")
                else:
                    print("\n[HOTKEY] F8: AUTO MODE OFF")
                    print("[DEBUG] The agent will only debug, no operation.")
                    if controller is not None:
                        controller.release_all()

            elif key == keyboard.Key.f9:
                runtime_control.stop_auto()
                if controller is not None:
                    controller.release_all()

                print("\n[HOTKEY] F9: EMERGENCY STOP")
                print("[DEBUG] Auto operation stopped. Debug is still running.")

            elif key == keyboard.Key.f10:
                runtime_control.request_quit()
                if controller is not None:
                    controller.release_all()

                print("\n[HOTKEY] F10: QUIT REQUESTED")
                return False

        except Exception as e:
            print(f"[HOTKEY ERROR] {e}")

    listener = keyboard.Listener(on_press=on_press)
    listener.daemon = True
    listener.start()
    return listener


def load_config():
    path = ROOT_DIR / "config" / "settings.yaml"

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_action_interval(config):
    """
    从配置中读取动作间隔。
    如果 settings.yaml 里没有配置，就默认 1 秒执行一次动作。
    """
    strategy_cfg = config.get("strategy", {})
    return float(strategy_cfg.get("action_interval", 1.0))


def main():
    config = load_config()

    window_finder = PVZWindowFinder(
        config["window"]["title_keywords"]
    )

    hwnd, title = window_finder.find_window()
    client_region = window_finder.get_client_rect_on_screen(hwnd)

    print(f"Found PVZ window: {title}")
    print(f"Client region: {client_region}")

    capture = PVZCapture(client_region)

    grid = PVZGrid(config)
    plant_detector = PlantDetector(config, grid)
    card_detector = CardDetector(config)
    game_state = GameState()
    decision_maker = IZombieDecisionMaker(config)
    controller = PVZController(client_region, grid, card_detector)

    runtime_control = RuntimeControl()
    hotkey_listener = start_hotkey_listener(runtime_control, controller)

    debug = DebugView(enabled=config.get("capture", {}).get("debug", True))

    action_interval = get_action_interval(config)
    last_action_time = 0
    last_debug_log_time = 0
    last_plan_log_time = 0

    print("\n========================================")
    print("PVZ Agent started in DEBUG MODE.")
    print("Default behavior: NO mouse click, NO keyboard action.")
    print("----------------------------------------")
    print("F8  : start / pause auto operation")
    print("F9  : emergency stop, keep debug running")
    print("F10 : quit program")
    print("Q   : quit when debug window is focused")
    print("Ctrl+C also works in terminal")
    print("========================================\n")

    try:
        while True:
            if runtime_control.should_quit():
                break

            # 窗口可能移动，所以每轮刷新客户区位置
            client_region = window_finder.get_client_rect_on_screen(hwnd)
            capture.update_region(client_region)
            controller.update_client_region(client_region)

            frame = capture.grab()

            # 识别和规划始终运行
            board = plant_detector.detect_board(frame)
            cards = card_detector.detect_cards(frame)

            game_state.update(board=board, cards=cards)

            plan = decision_maker.choose_plan(board, cards)

            now = time.time()

            # 限制 Plan 打印频率，避免终端刷屏
            if now - last_plan_log_time >= 1.0:
                mode = "AUTO" if runtime_control.is_auto_enabled() else "DEBUG"
                print(f"[{mode}] Plan: {plan}")
                last_plan_log_time = now

            # Debug 窗口始终显示
            vis = debug.draw(
                frame,
                grid=grid,
                board=board,
                cards=cards,
            )

            should_quit_from_debug = debug.show(vis)
            if should_quit_from_debug:
                print("[DEBUG] Q pressed in debug window.")
                break

            # 关键安全逻辑：
            # 没按 F8 之前，只 debug，不允许任何鼠标/键盘操作。
            if not runtime_control.is_auto_enabled():
                if now - last_debug_log_time >= 3.0:
                    print("[DEBUG MODE] Auto operation is OFF. Press F8 to start.")
                    last_debug_log_time = now

                time.sleep(0.01)
                continue

            # 自动模式开启后，才允许执行动作。
            if now - last_action_time < action_interval:
                time.sleep(0.01)
                continue

            if plan["action"] == "PLACE_ZOMBIE":
                zombie = plan["zombie"]
                row = plan["row"]
                col = plan.get("col", 0)

                card_info = cards.get(zombie)

                if card_info and card_info.get("available", False):
                    print(f"[AUTO] Executing: place {zombie} at row={row}, col={col}")
                    controller.place_zombie(card_info, row, col)
                    last_action_time = now
                else:
                    print(f"[AUTO] Skip action: card not available: {zombie}")
                    last_action_time = now

            elif plan["action"] == "WAIT":
                last_action_time = now

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nInterrupted by user")

    finally:
        runtime_control.stop_auto()

        try:
            controller.release_all()
        except Exception as e:
            print(f"[WARN] controller.release_all failed: {e}")

        try:
            debug.close()
        except Exception as e:
            print(f"[WARN] debug.close failed: {e}")

        try:
            hotkey_listener.stop()
        except Exception:
            pass

        print("PVZ Agent stopped.")


if __name__ == "__main__":
    main()
