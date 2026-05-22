import win32gui
import win32con


class WindowNotFoundError(Exception):
    pass


class PVZWindowFinder:
    """
    自动寻找 PVZ 游戏窗口。

    返回的是客户区 client area，不包括标题栏和边框。
    后续所有截图、点击都基于客户区。
    """

    def __init__(self, title_keywords):
        self.title_keywords = title_keywords

    def find_window(self):
        matched = []

        def callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return

            title = win32gui.GetWindowText(hwnd)

            if not title:
                return

            for keyword in self.title_keywords:
                if keyword.lower() in title.lower():
                    matched.append((hwnd, title))
                    return

        win32gui.EnumWindows(callback, None)

        if not matched:
            raise WindowNotFoundError(
                f"Cannot find PVZ window. Tried keywords: {self.title_keywords}"
            )

        # 默认取第一个匹配窗口
        hwnd, title = matched[0]

        # 如果窗口最小化，恢复
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        # 将窗口置前
        win32gui.SetForegroundWindow(hwnd)

        return hwnd, title

    def get_client_rect_on_screen(self, hwnd):
        """
        获取客户区在屏幕上的绝对坐标。

        返回：
        {
            "left": x,
            "top": y,
            "width": w,
            "height": h
        }
        """
        left, top, right, bottom = win32gui.GetClientRect(hwnd)

        screen_left, screen_top = win32gui.ClientToScreen(hwnd, (left, top))
        screen_right, screen_bottom = win32gui.ClientToScreen(hwnd, (right, bottom))

        return {
            "left": screen_left,
            "top": screen_top,
            "width": screen_right - screen_left,
            "height": screen_bottom - screen_top,
        }
