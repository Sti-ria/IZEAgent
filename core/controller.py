import time
import pyautogui


pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.02


class PVZController:
    """
    PVZ 鼠标控制器。

    注意：
    - 输入坐标是 PVZ 客户区内部坐标。
    - 内部会转换成屏幕绝对坐标。
    - main.py 没有开启 AUTO 模式时，不会调用这里的点击函数。
    """

    def __init__(self, client_region, grid, card_detector):
        self.client_region = client_region
        self.grid = grid
        self.card_detector = card_detector

    def update_client_region(self, client_region):
        self.client_region = client_region

    def _to_screen(self, x, y):
        screen_x = self.client_region["left"] + int(x)
        screen_y = self.client_region["top"] + int(y)
        return screen_x, screen_y

    def click_client(self, x, y):
        sx, sy = self._to_screen(x, y)
        pyautogui.click(sx, sy)

    def click_cell(self, row, col):
        x, y = self.grid.cell_center(row, col)
        self.click_client(x, y)

    def click_card(self, card_info):
        x1, y1, x2, y2 = card_info["rect"]
        x = (x1 + x2) // 2
        y = (y1 + y2) // 2
        self.click_client(x, y)

    def place_zombie(self, card_info, row, col=0):
        """
        我是僵尸模式：
        1. 点击僵尸卡牌
        2. 点击目标格子
        """
        self.click_card(card_info)
        time.sleep(0.08)
        self.click_cell(row, col)
        time.sleep(0.12)

    def release_all(self):
        """
        紧急释放所有可能残留的鼠标 / 键盘状态。

        F8 暂停、F9 紧急停止、F10 退出、Ctrl+C 退出时都会调用。
        """
        try:
            pyautogui.mouseUp()

            keys = [
                "left",
                "right",
                "up",
                "down",
                "space",
                "shift",
                "ctrl",
                "alt",
                "enter",
                "esc",
            ]

            for key in keys:
                pyautogui.keyUp(key)

        except Exception as e:
            print(f"[Controller] release_all failed: {e}")
