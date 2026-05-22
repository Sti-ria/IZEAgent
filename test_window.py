import win32gui


def callback(hwnd, _):
    if not win32gui.IsWindowVisible(hwnd):
        return

    title = win32gui.GetWindowText(hwnd)

    if title:
        print(hwnd, title)


win32gui.EnumWindows(callback, None)
