"""Nonogram (Picross) - fill in the grid using the row/column run-length
clues until the hidden picture emerges. Pure PyQt6 (QPainter, mouse
events), no extra dependencies, turn-based like games/sudoku.py.

Puzzles come from a small hand-drawn pattern bank rather than randomly
generated noise - a random binary grid is usually either unsolvable by
pure logic or has multiple solutions, and either way never resolves into
a satisfying picture the way a real Picross puzzle does.
"""
import json
import os
import random

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core import config as core_config
from games.start_screen import consume_start_input, draw_start_screen

PATTERNS = {
    "Heart": [
        "0110000110", "1111011110", "1111111111", "1111111111", "1111111111",
        "0111111110", "0011111100", "0001111000", "0000110000", "0000000000",
    ],
    "Cross": [
        "0000110000", "0000110000", "0000110000", "0000110000", "1111111111",
        "1111111111", "0000110000", "0000110000", "0000110000", "0000110000",
    ],
    "Diamond": [
        "0000110000", "0001111000", "0011111100", "0111111110", "1111111111",
        "1111111111", "0111111110", "0011111100", "0001111000", "0000110000",
    ],
    "Arrow": [
        "0000110000", "0001111000", "0011111100", "0111111110", "0000110000",
        "0000110000", "0000110000", "0000110000", "0000110000", "0000110000",
    ],
    "House": [
        "0000110000", "0001111000", "0011111100", "0111111110", "1111111111",
        "1111111111", "1111111111", "1111111111", "1111001111", "1111001111",
    ],
}

GRID_SIZE = 10
CELL = 32
CLUE_SLOT = 20
MAX_CLUE_SLOTS = 4  # reserved clue-margin width/height, in CLUE_SLOT units
LEFT_MARGIN = MAX_CLUE_SLOTS * CLUE_SLOT
TOP_MARGIN = MAX_CLUE_SLOTS * CLUE_SLOT
RIGHT_MARGIN = 16
HUD_HEIGHT = 30

BG_CANVAS = QColor("#12121a")
GRID_LINE = QColor("#3a3a48")
GRID_LINE_BOLD = QColor("#565668")
CELL_EMPTY = QColor("#1a1a24")
CELL_FILLED = QColor("#7c5cff")
TEXT_COLOR = QColor("#eaeaf2")
MUTED_COLOR = QColor("#9494a6")
CLUE_SOLVED_COLOR = QColor("#3ecf8e")
MARK_COLOR = QColor("#e5484d")


def _clues_from_line(line):
    clues, run = [], 0
    for ch in line:
        if ch == "1":
            run += 1
        else:
            if run:
                clues.append(run)
            run = 0
    if run:
        clues.append(run)
    return clues or [0]


class NonogramWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(
            LEFT_MARGIN + GRID_SIZE * CELL + RIGHT_MARGIN,
            TOP_MARGIN + GRID_SIZE * CELL + HUD_HEIGHT,
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.puzzles_solved = self._load_stats()
        self.started = False  # gated by a start screen - see games/start_screen.py
        self._new_game()

    # ------------------------------------------------------------------
    # Game state
    # ------------------------------------------------------------------
    def _new_game(self, pattern_name=None):
        if pattern_name is None or pattern_name == "Random":
            pattern_name = random.choice(list(PATTERNS.keys()))
        self.pattern_name = pattern_name
        self.solution = PATTERNS[pattern_name]
        self.row_clues = [_clues_from_line(row) for row in self.solution]
        self.col_clues = [_clues_from_line("".join(row[c] for row in self.solution)) for c in range(GRID_SIZE)]
        # Per-cell state: "empty", "filled", or "marked" (a player note
        # meaning "definitely not filled" - purely an aid, not checked).
        self.cells = [["empty"] * GRID_SIZE for _ in range(GRID_SIZE)]
        self.state = "playing"  # playing -> won
        self.update()

    def _toggle_fill(self, r, c):
        if self.state != "playing":
            return
        self.cells[r][c] = "empty" if self.cells[r][c] == "filled" else "filled"
        self._check_win()

    def _toggle_mark(self, r, c):
        if self.state != "playing" or self.cells[r][c] == "filled":
            return
        self.cells[r][c] = "empty" if self.cells[r][c] == "marked" else "marked"

    def _check_win(self):
        for r in range(GRID_SIZE):
            for c in range(GRID_SIZE):
                filled = self.cells[r][c] == "filled"
                should_fill = self.solution[r][c] == "1"
                if filled != should_fill:
                    return
        self.state = "won"
        self.puzzles_solved += 1
        self.save_now()

    def _row_solved(self, r):
        return all((self.cells[r][c] == "filled") == (self.solution[r][c] == "1") for c in range(GRID_SIZE))

    def _col_solved(self, c):
        return all((self.cells[r][c] == "filled") == (self.solution[r][c] == "1") for r in range(GRID_SIZE))

    # ------------------------------------------------------------------
    # Persistence - just a lifetime solved-count, not per-puzzle progress;
    # a half-finished grid isn't worth resuming across app restarts the way
    # e.g. games/sudoku.py's board is.
    # ------------------------------------------------------------------
    def _save_path(self):
        return os.path.join(core_config.path("games"), "nonogram_save.json")

    def _load_stats(self):
        try:
            with open(self._save_path(), "r", encoding="utf-8") as f:
                return json.load(f).get("puzzles_solved", 0)
        except (OSError, ValueError, json.JSONDecodeError):
            return 0

    def save_now(self):
        path = self._save_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"puzzles_solved": self.puzzles_solved}, f)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def _cell_at(self, pos):
        x, y = pos.x() - LEFT_MARGIN, pos.y() - TOP_MARGIN
        if x < 0 or y < 0:
            return None
        c, r = int(x // CELL), int(y // CELL)
        if 0 <= r < GRID_SIZE and 0 <= c < GRID_SIZE:
            return r, c
        return None

    def mousePressEvent(self, event):
        if consume_start_input(self):
            return
        cell = self._cell_at(event.position().toPoint())
        if cell is None:
            return
        r, c = cell
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_fill(r, c)
        elif event.button() == Qt.MouseButton.RightButton:
            self._toggle_mark(r, c)
        self.update()

    def keyPressEvent(self, event):
        if consume_start_input(self):
            return
        if event.key() == Qt.Key.Key_N:
            self._new_game()
            self.update()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), BG_CANVAS)

        self._draw_clues(painter)
        self._draw_grid(painter)
        self._draw_hud(painter)

        if not self.started:
            draw_start_screen(painter, self.rect(), "Nonogram", [
                "Fill cells using the row/column clues until the picture appears.",
                "Left click to fill a cell, right click to mark one as empty.",
                "A clue turns green once that row or column is fully correct.",
                "Click or press any key to begin.",
            ])
        elif self.state == "won":
            self._draw_won(painter)
        painter.end()

    def _draw_clues(self, painter):
        painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        for r in range(GRID_SIZE):
            solved = self._row_solved(r)
            painter.setPen(QPen(CLUE_SOLVED_COLOR if solved else TEXT_COLOR))
            clue_text = " ".join(str(n) for n in self.row_clues[r])
            rect = QRect(0, TOP_MARGIN + r * CELL, LEFT_MARGIN - 6, CELL)
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, clue_text)

        for c in range(GRID_SIZE):
            solved = self._col_solved(c)
            painter.setPen(QPen(CLUE_SOLVED_COLOR if solved else TEXT_COLOR))
            lines = [str(n) for n in self.col_clues[c]]
            x = LEFT_MARGIN + c * CELL
            for i, line in enumerate(reversed(lines)):
                y = TOP_MARGIN - 4 - i * 16
                painter.drawText(QRect(x, y - 14, CELL, 16), Qt.AlignmentFlag.AlignCenter, line)

    def _draw_grid(self, painter):
        for r in range(GRID_SIZE + 1):
            painter.setPen(QPen(GRID_LINE_BOLD if r % 5 == 0 else GRID_LINE, 1.5 if r % 5 == 0 else 1))
            y = TOP_MARGIN + r * CELL
            painter.drawLine(LEFT_MARGIN, y, LEFT_MARGIN + GRID_SIZE * CELL, y)
        for c in range(GRID_SIZE + 1):
            painter.setPen(QPen(GRID_LINE_BOLD if c % 5 == 0 else GRID_LINE, 1.5 if c % 5 == 0 else 1))
            x = LEFT_MARGIN + c * CELL
            painter.drawLine(x, TOP_MARGIN, x, TOP_MARGIN + GRID_SIZE * CELL)

        for r in range(GRID_SIZE):
            for c in range(GRID_SIZE):
                rect = QRect(LEFT_MARGIN + c * CELL + 1, TOP_MARGIN + r * CELL + 1, CELL - 2, CELL - 2)
                state = self.cells[r][c]
                if state == "filled":
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(CELL_FILLED))
                    painter.drawRect(rect)
                elif state == "marked":
                    painter.setPen(QPen(MARK_COLOR, 2))
                    painter.drawLine(rect.topLeft(), rect.bottomRight())
                    painter.drawLine(rect.topRight(), rect.bottomLeft())

    def _draw_hud(self, painter):
        y = TOP_MARGIN + GRID_SIZE * CELL
        painter.setPen(QPen(MUTED_COLOR))
        painter.setFont(QFont("Arial", 10))
        painter.drawText(QRect(0, y, self.width(), HUD_HEIGHT), Qt.AlignmentFlag.AlignVCenter,
                          f"  {self.pattern_name}  -  Solved: {self.puzzles_solved}  -  N for a new puzzle")

    def _draw_won(self, painter):
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"Solved!\n{self.pattern_name}\nN for a new puzzle")
