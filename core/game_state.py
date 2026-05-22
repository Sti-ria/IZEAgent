class GameState:
    """
    保存当前识别到的游戏状态。
    """

    def __init__(self):
        self.board = None
        self.cards = None
        self.sun = 0

    def update(self, board, cards, sun=None):
        self.board = board
        self.cards = cards

        if sun is not None:
            self.sun = sun

    def get_row_plants(self, row):
        if self.board is None:
            return []

        return self.board[row]

    def print_board(self):
        if self.board is None:
            print("[GameState] board=None")
            return

        print("Current board:")

        for row in self.board:
            names = []

            for cell in row:
                plant = cell["plant"] if cell["plant"] else "."
                names.append(f"{plant[:3]:>3}")

            print(" ".join(names))
