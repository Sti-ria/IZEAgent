class PVZGrid:
    """
    管理 PVZ 棋盘网格。

    我是僵尸一般是 5 行 × 9 列。
    所有坐标都是相对于 PVZ 客户区 / 当前截图 frame。
    """

    def __init__(self, config):
        grid_cfg = config["grid"]

        self.rows = int(grid_cfg.get("rows", 5))
        self.cols = int(grid_cfg.get("cols", 9))

        self.left = int(grid_cfg["board_left"])
        self.top = int(grid_cfg["board_top"])
        self.width = int(grid_cfg["board_width"])
        self.height = int(grid_cfg["board_height"])

        self.crop_padding_ratio = float(
            grid_cfg.get("crop_padding_ratio", 0.08)
        )

        self.cell_width = self.width / self.cols
        self.cell_height = self.height / self.rows

    def cell_rect(self, row, col):
        """
        返回某个格子的矩形区域。

        返回：
            x1, y1, x2, y2
        """
        x1 = int(self.left + col * self.cell_width)
        y1 = int(self.top + row * self.cell_height)
        x2 = int(self.left + (col + 1) * self.cell_width)
        y2 = int(self.top + (row + 1) * self.cell_height)
        return x1, y1, x2, y2

    def cell_bbox(self, row, col):
        """
        返回某个格子的 bbox。

        返回：
            x, y, w, h
        """
        x1, y1, x2, y2 = self.cell_rect(row, col)
        return x1, y1, x2 - x1, y2 - y1

    def cell_center(self, row, col):
        """
        返回某个格子的中心点。

        返回：
            x, y
        """
        x = int(self.left + (col + 0.5) * self.cell_width)
        y = int(self.top + (row + 0.5) * self.cell_height)
        return x, y

    def point_to_cell(self, x, y):
        """
        根据坐标判断它属于哪个格子。

        返回：
            (row, col) 或 None
        """
        if not (self.left <= x <= self.left + self.width):
            return None

        if not (self.top <= y <= self.top + self.height):
            return None

        col = int((x - self.left) / self.cell_width)
        row = int((y - self.top) / self.cell_height)

        if 0 <= row < self.rows and 0 <= col < self.cols:
            return row, col

        return None

    def all_cells(self):
        """
        返回所有格子的 row / col / bbox 信息。

        返回：
        [
            {
                "row": 0,
                "col": 0,
                "bbox": (x, y, w, h)
            },
            ...
        ]
        """
        cells = []

        for row in range(self.rows):
            for col in range(self.cols):
                cells.append(
                    {
                        "row": row,
                        "col": col,
                        "bbox": self.cell_bbox(row, col),
                    }
                )

        return cells


def get_grid_config(config):
    """
    读取棋盘网格配置。

    兼容当前 settings.yaml 写法：

    grid:
      rows: 5
      cols: 9
      board_left: 30
      board_top: 80
      board_width: 735
      board_height: 500
      crop_padding_ratio: 0.08
    """
    if "grid" not in config:
        raise KeyError("Missing grid config in settings.yaml")

    grid = config["grid"]

    rows = int(grid.get("rows", 5))
    cols = int(grid.get("cols", 9))

    x = int(grid.get("board_left", grid.get("x", 0)))
    y = int(grid.get("board_top", grid.get("y", 0)))
    width = int(grid.get("board_width", grid.get("width", 0)))
    height = int(grid.get("board_height", grid.get("height", 0)))

    if width <= 0 or height <= 0:
        raise ValueError(
            "Invalid grid size. Please check board_width and board_height in settings.yaml"
        )

    crop_padding_ratio = float(grid.get("crop_padding_ratio", 0.08))

    return {
        "rows": rows,
        "cols": cols,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "crop_padding_ratio": crop_padding_ratio,
    }


def get_grid_bboxes(config):
    """
    返回所有格子的 bbox。

    bbox 坐标是相对于当前 PVZ 窗口截图 frame 的坐标。

    返回：
    [
        {
            "row": 0,
            "col": 0,
            "bbox": (x, y, w, h)
        },
        ...
    ]
    """
    grid = PVZGrid(config)
    return grid.all_cells()


def crop_cell(frame, bbox, padding_ratio=0.08):
    """
    从 frame 中裁剪一个格子。

    padding_ratio 用来裁掉一点边缘，减少相邻格子、网格线、边界阴影的干扰。
    """
    frame_h, frame_w = frame.shape[:2]

    x, y, w, h = bbox

    pad_x = int(w * padding_ratio)
    pad_y = int(h * padding_ratio)

    x1 = max(0, x + pad_x)
    y1 = max(0, y + pad_y)
    x2 = min(frame_w, x + w - pad_x)
    y2 = min(frame_h, y + h - pad_y)

    if x2 <= x1 or y2 <= y1:
        return None

    return frame[y1:y2, x1:x2].copy()


def crop_grid_cells_for_recognition(frame, config):
    """
    裁剪当前画面中的所有棋盘格子。

    输入：
        frame:
            当前 PVZ 窗口截图。
        config:
            settings.yaml 读取出来的配置。

    返回：
    [
        {
            "row": 0,
            "col": 0,
            "bbox": (x, y, w, h),
            "image": cell_img
        },
        ...
    ]
    """
    grid_cfg = get_grid_config(config)
    padding_ratio = grid_cfg["crop_padding_ratio"]

    cells = []

    for item in get_grid_bboxes(config):
        cell_img = crop_cell(
            frame,
            item["bbox"],
            padding_ratio=padding_ratio,
        )

        cells.append(
            {
                "row": item["row"],
                "col": item["col"],
                "bbox": item["bbox"],
                "image": cell_img,
            }
        )

    return cells
