import cv2


class DebugView:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.window_name = "PVZ Agent Debug"

    def draw(self, frame, grid, board=None, cards=None):
        if not self.enabled:
            return frame

        vis = frame.copy()

        # 画棋盘
        for row in range(grid.rows):
            for col in range(grid.cols):
                x1, y1, x2, y2 = grid.cell_rect(row, col)

                cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 1)

                if board is not None:
                    plant = board[row][col]["plant"]

                    if plant:
                        cv2.putText(
                            vis,
                            plant[:8],
                            (x1 + 3, y1 + 15),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.35,
                            (0, 255, 255),
                            1,
                        )

        # 画卡槽
        if cards:
            for name, card in cards.items():
                x1, y1, x2, y2 = card["rect"]
                color = (0, 255, 0) if card["available"] else (0, 0, 255)

                cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
                cv2.putText(
                    vis,
                    name[:6],
                    (x1, y2 + 12),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35,
                    color,
                    1,
                )

        return vis

    def show(self, frame):
        if not self.enabled:
            return False

        cv2.imshow(self.window_name, frame)
        key = cv2.waitKey(1) & 0xFF

        return key == ord("q")

    def close(self):
        cv2.destroyAllWindows()
