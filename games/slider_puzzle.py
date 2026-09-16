"""Sliding tile puzzle (the classic 15-puzzle, plus 8- and 24-puzzle
variants) - slide numbered tiles around the one empty slot until they're
back in order. Pure PyQt6 (QPainter, mouse/key events), no extra
dependencies, turn-based like games/sudoku.py.
"""
import json
import os
import random
import time

from PyQt6.QtCore import QRect, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core import config as core_config
from games.start_screen import consume_start_input, draw_start_screen

# Grid side length per difficulty - an NxN board has N*N-1 numbered tiles.
DIFFICULTIES = {
    "3x3 (8-puzzle)": 3,
    "4x4 (15-puzzle)": 4,
    "5x5 (24-puzzle)": 5,
}

TILE_SIZE = 90
MARGIN = 12
HUD_HEIGHT = 40
SHUFFLE_MOVES = 200

BG_CANVAS = QColor("#12121a")
BOARD_BG = QColor("#1a1a24")
TILE_BG = QColor("#3a2f66")
TILE_BORDER = QColor("#7c5cff")
TEXT_COLOR = QColor("#eaeaf2")
MUTED_COLOR = QColor("#9494a6")

# Arrow key -> which way the blank slot itself moves. Convention: an arrow
# key names the direction the TILE next to the blank slides (Up = the tile
# below the blank slides up into it), so the blank moves the opposite way.
_ARROW_BLANK_DELTA = {
    Qt.Key.Key_Up: (1, 0),
    Qt.Key.Key_Down: (-1, 0),
    Qt.Key.Key_Left: (0, 1),
    Qt.Key.Key_Right: (0, -1),
}


class SliderPuzzleWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.best_records = self._load_best_records()
        self.started = False  # gated by a start screen - see games/start_screen.py
        self.difficulty = "4x4 (15-puzzle)"
        self._new_game(self.difficulty)

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update)
        self.clock_timer.start(200)

    # ------------------------------------------------------------------
    # Game state
    # ------------------------------------------------------------------
    def _new_game(self, difficulty=None):
        if difficulty:
            self.difficulty = difficulty
        self.n = DIFFICULTIES[self.difficulty]
        self.setFixedSize(self.n * TILE_SIZE + MARGIN * 2, self.n * TILE_SIZE + MARGIN * 2 + HUD_HEIGHT)

        self.board = [[r * self.n + c + 1 for c in range(self.n)] for r in range(self.n)]
        self.board[self.n - 1][self.n - 1] = 0
        self.blank_r, self.blank_c = self.n - 1, self.n - 1
        self._shuffle()

        self.move_count = 0
        self.start_time = None
        self.elapsed = 0.0
        self.state = "playing"  # playing -> won
        self.update()

    def _shuffle(self):
        last_delta = None
        for _ in range(SHUFFLE_MOVES):
            options = [d for d in ((1, 0), (-1, 0), (0, 1), (0, -1)) if d != last_delta and self._blank_can_move(d)]
            if not options:
                options = [d for d in ((1, 0), (-1, 0), (0, 1), (0, -1)) if self._blank_can_move(d)]
            delta = random.choice(options)
            self._move_blank(delta)
            last_delta = (-delta[0], -delta[1])  # never immediately undo the move just made
        if self._is_solved():
            self._shuffle()  # astronomically unlikely, but never hand back a solved board

    def _blank_can_move(self, delta):
        nr, nc = self.blank_r + delta[0], self.blank_c + delta[1]
        return 0 <= nr < self.n and 0 <= nc < self.n

    def _move_blank(self, delta):
        nr, nc = self.blank_r + delta[0], self.blank_c + delta[1]
        self.board[self.blank_r][self.blank_c], self.board[nr][nc] = self.board[nr][nc], self.board[self.blank_r][self.blank_c]
        self.blank_r, self.blank_c = nr, nc

    def _is_solved(self):
        expected = 1
        for r in range(self.n):
            for c in range(self.n):
                if r == self.n - 1 and c == self.n - 1:
                    return self.board[r][c] == 0
                if self.board[r][c] != expected:
                    return False
                expected += 1
        return True

    def _try_slide(self, r, c):
        if self.state != "playing":
            return
        dr, dc = r - self.blank_r, c - self.blank_c
        if abs(dr) + abs(dc) != 1:
            return  # not orthogonally adjacent to the blank
        if self.start_time is None:
            self.start_time = time.monotonic()
        self._move_blank((dr, dc))
        self.move_count += 1
        if self._is_solved():
            self._finish()

    def _finish(self):
        self.state = "won"
        self.elapsed = time.monotonic() - self.start_time if self.start_time else 0.0
        record = self.best_records.get(self.difficulty)
        if record is None or self.move_count < record.get("moves", float("inf")):
            self.best_records[self.difficulty] = {"moves": self.move_count, "time": self.elapsed}
            self.save_now()

    # ------------------------------------------------------------------
    # Persistence - fewest moves (with that run's time alongside) per
    # difficulty. A round is a short session, not a board worth mid-game
    # resume like games/sudoku.py's.
    # ------------------------------------------------------------------
    def _save_path(self):
        return os.path.join(core_config.path("games"), "slider_puzzle_save.json")

    def _load_best_records(self):
        try:
            with open(self._save_path(), "r", encoding="utf-8") as f:
                return json.load(f).get("best_records", {})
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def save_now(self):
        path = self._save_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"best_records": self.best_records}, f)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def _tile_at(self, pos):
        x, y = pos.x() - MARGIN, pos.y() - MARGIN
        if x < 0 or y < 0:
            return None
        c, r = int(x // TILE_SIZE), int(y // TILE_SIZE)
        if 0 <= r < self.n and 0 <= c < self.n:
            return r, c
        return None

    def mousePressEvent(self, event):
        if consume_start_input(self):
            return
        cell = self._tile_at(event.position().toPoint())
        if cell is not None:
            self._try_slide(*cell)
        self.update()

    def keyPressEvent(self, event):
        if consume_start_input(self):
            return
        if event.key() == Qt.Key.Key_N:
            self._new_game()
            self.update()
            return
        delta = _ARROW_BLANK_DELTA.get(event.key())
        if delta and self._blank_can_move(delta):
            tile_r, tile_c = self.blank_r + delta[0], self.blank_c + delta[1]
            self._try_slide(tile_r, tile_c)
            self.update()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), BG_CANVAS)

        painter.fillRect(MARGIN, MARGIN, self.n * TILE_SIZE, self.n * TILE_SIZE, BOARD_BG)
        self._draw_tiles(painter)
        self._draw_hud(painter)

        if not self.started:
            draw_start_screen(painter, self.rect(), "Slider Puzzle", [
                "Slide tiles into the empty slot to put them back in order.",
                "Click a tile next to the empty slot, or use the arrow keys.",
                "N for a new shuffle.",
                "Click or press any key to begin.",
            ])
        elif self.state == "won":
            self._draw_won(painter)
        painter.end()

    def _draw_tiles(self, painter):
        for r in range(self.n):
            for c in range(self.n):
                value = self.board[r][c]
                if value == 0:
                    continue
                rect = QRect(MARGIN + c * TILE_SIZE + 2, MARGIN + r * TILE_SIZE + 2, TILE_SIZE - 4, TILE_SIZE - 4)
                painter.setPen(QPen(TILE_BORDER, 1.5))
                painter.setBrush(QBrush(TILE_BG))
                painter.drawRoundedRect(rect, 6, 6)
                painter.setPen(QPen(TEXT_COLOR))
                painter.setFont(QFont("Arial", 20, QFont.Weight.Bold))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(value))

    def _draw_hud(self, painter):
        y = MARGIN * 2 + self.n * TILE_SIZE
        elapsed = self.elapsed if self.state == "won" else (
            time.monotonic() - self.start_time if self.start_time else 0.0
        )
        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 11))
        painter.drawText(QRect(MARGIN, y, self.width() - MARGIN * 2, HUD_HEIGHT - MARGIN),
                          Qt.AlignmentFlag.AlignVCenter, f"Moves: {self.move_count}   Time: {elapsed:.1f}s")

        record = self.best_records.get(self.difficulty)
        if record is not None:
            painter.setPen(QPen(MUTED_COLOR))
            painter.setFont(QFont("Arial", 9))
            painter.drawText(QRect(MARGIN, y, self.width() - MARGIN * 2, HUD_HEIGHT - MARGIN),
                              Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                              f"Best: {record['moves']} moves ({record['time']:.1f}s)")

    def _draw_won(self, painter):
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                          f"Solved!\n{self.move_count} moves in {self.elapsed:.1f}s\nN for a new shuffle")
