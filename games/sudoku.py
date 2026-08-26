"""Sudoku. Pure PyQt6 (QPainter, mouse/key events), no extra dependencies -
same "self-contained, no external assets" style as games/zuma_endless.py
and games/solitaire.py.

Turn-based like Solitaire (no QTimer game loop): a puzzle is generated once
per "New Game" via randomized backtracking plus a uniqueness check, then
play is just filling cells in.
"""
import json
import os
import random

from PyQt6.QtCore import QRect, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core import config as core_config

CELL = 52
GRID_SIZE = CELL * 9
MARGIN = 20
CANVAS_WIDTH = GRID_SIZE + MARGIN * 2
CANVAS_HEIGHT = GRID_SIZE + MARGIN * 2 + 40  # extra room for the HUD line

BG_CANVAS = QColor("#12121a")
GRID_LINE = QColor("#3a3a48")
GRID_LINE_BOLD = QColor("#6a6a80")
CELL_BG = QColor("#1a1a24")
CELL_BG_SELECTED = QColor("#332a66")
CELL_BG_PEER = QColor("#20202e")
GIVEN_TEXT = QColor("#eaeaf2")
ENTERED_TEXT = QColor("#9d85ff")
CONFLICT_TEXT = QColor("#e5484d")
MUTED_COLOR = QColor("#9494a6")
TEXT_COLOR = QColor("#eaeaf2")

DIFFICULTIES = {"Easy": 42, "Medium": 36, "Hard": 30}
MAX_MISTAKES = 5


def _find_empty(grid):
    for r in range(9):
        for c in range(9):
            if grid[r][c] == 0:
                return r, c
    return None


def _is_valid(grid, r, c, n):
    if any(grid[r][cc] == n for cc in range(9) if cc != c):
        return False
    if any(grid[rr][c] == n for rr in range(9) if rr != r):
        return False
    box_r, box_c = (r // 3) * 3, (c // 3) * 3
    for rr in range(box_r, box_r + 3):
        for cc in range(box_c, box_c + 3):
            if (rr, cc) != (r, c) and grid[rr][cc] == n:
                return False
    return True


def _fill_grid(grid):
    empty = _find_empty(grid)
    if empty is None:
        return True
    r, c = empty
    nums = list(range(1, 10))
    random.shuffle(nums)
    for n in nums:
        if _is_valid(grid, r, c, n):
            grid[r][c] = n
            if _fill_grid(grid):
                return True
            grid[r][c] = 0
    return False


def _count_solutions(grid, limit=2):
    count = [0]

    def solve():
        if count[0] >= limit:
            return
        empty = _find_empty(grid)
        if empty is None:
            count[0] += 1
            return
        r, c = empty
        for n in range(1, 10):
            if _is_valid(grid, r, c, n):
                grid[r][c] = n
                solve()
                grid[r][c] = 0
                if count[0] >= limit:
                    return

    solve()
    return count[0]


def _generate_puzzle(target_givens):
    """A full solved grid, then cells removed one at a time (in random
    order) as long as removing one still leaves a UNIQUE solution -
    checked via _count_solutions with an early exit at 2, so a bad removal
    is caught without exploring every possible completion. Standard
    generate-then-carve technique; a plain randomized backtracking fill is
    fast enough here without the usual diagonal-box-first shortcut."""
    solved = [[0] * 9 for _ in range(9)]
    _fill_grid(solved)
    puzzle = [row[:] for row in solved]
    cells = [(r, c) for r in range(9) for c in range(9)]
    random.shuffle(cells)
    givens = 81
    for r, c in cells:
        if givens <= target_givens:
            break
        backup = puzzle[r][c]
        puzzle[r][c] = 0
        trial = [row[:] for row in puzzle]
        if _count_solutions(trial, limit=2) == 1:
            givens -= 1
        else:
            puzzle[r][c] = backup
    return puzzle, solved


class SudokuWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(CANVAS_WIDTH, CANVAS_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.difficulty = "Medium"
        saved = self._load_save()
        if saved:
            self._restore_from_save(saved)
        else:
            self._new_game()

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.save_now)
        self.autosave_timer.start(15_000)

    # ------------------------------------------------------------------
    # Game state
    # ------------------------------------------------------------------
    def _new_game(self, difficulty=None):
        if difficulty is not None:
            self.difficulty = difficulty
        puzzle, solved = _generate_puzzle(DIFFICULTIES[self.difficulty])
        self.given = [[puzzle[r][c] != 0 for c in range(9)] for r in range(9)]
        self.grid = [row[:] for row in puzzle]
        self.solution = solved
        self.selected = None
        self.solved = False
        self.failed = False
        self.mistakes = 0
        self.update()
        self.save_now()

    # ------------------------------------------------------------------
    # Persistence - same lazy-mkdir-on-write-only pattern as
    # core/activity_log.py and core/subscriptions.py: a read must never
    # create the directory, only a write does.
    # ------------------------------------------------------------------
    def _save_path(self):
        return os.path.join(core_config.path("games"), "sudoku_save.json")

    def _load_save(self):
        path = self._save_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _restore_from_save(self, data):
        try:
            self.difficulty = data.get("difficulty", "Medium")
            self.given = data["given"]
            self.grid = data["grid"]
            self.solution = data["solution"]
            self.mistakes = data.get("mistakes", 0)
            self.solved = data.get("solved", False)
            self.failed = data.get("failed", False)
        except KeyError:
            self._new_game()
            return
        self.selected = None
        self.update()

    def save_now(self):
        """Called periodically (self.autosave_timer) and by the main
        window before it closes - see webagent_gui.py's closeEvent."""
        if not hasattr(self, "grid"):
            return
        data = {
            "difficulty": self.difficulty, "given": self.given, "grid": self.grid,
            "solution": self.solution, "mistakes": self.mistakes,
            "solved": self.solved, "failed": self.failed,
        }
        path = self._save_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass

    def _is_complete_and_correct(self):
        return all(self.grid[r][c] == self.solution[r][c] for r in range(9) for c in range(9))

    def _is_wrong(self, r, c):
        """Instant, solution-based check - not just a structural duplicate
        check (_is_valid) - a placed digit can be locally valid (no
        duplicate yet in its row/column/box) while still not being the
        one correct value for that cell in this puzzle's unique solution;
        comparing directly against self.solution catches that case, which
        a duplicate check alone would miss."""
        n = self.grid[r][c]
        return n != 0 and not self.given[r][c] and n != self.solution[r][c]

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def _cell_at(self, pos):
        x, y = pos.x() - MARGIN, pos.y() - MARGIN
        if 0 <= x < GRID_SIZE and 0 <= y < GRID_SIZE:
            return int(y // CELL), int(x // CELL)
        return None

    def mousePressEvent(self, event):
        if self.solved or self.failed:
            return
        hit = self._cell_at(event.position().toPoint())
        self.selected = hit
        self.update()

    def keyPressEvent(self, event):
        if self.solved or self.failed:
            return
        if self.selected is None:
            return
        r, c = self.selected
        if self.given[r][c]:
            self._move_selection(event.key())
            return
        key = event.key()
        if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            n = key - Qt.Key.Key_0
            self.grid[r][c] = n
            if n != self.solution[r][c]:
                self.mistakes += 1
                if self.mistakes >= MAX_MISTAKES:
                    self.failed = True
        elif key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete, Qt.Key.Key_0):
            self.grid[r][c] = 0
        else:
            self._move_selection(key)
            return
        if not self.failed and self._is_complete_and_correct():
            self.solved = True
        self.update()

    def _move_selection(self, key):
        if self.selected is None:
            return
        r, c = self.selected
        deltas = {
            Qt.Key.Key_Up: (-1, 0), Qt.Key.Key_Down: (1, 0),
            Qt.Key.Key_Left: (0, -1), Qt.Key.Key_Right: (0, 1),
        }
        if key in deltas:
            dr, dc = deltas[key]
            self.selected = (max(0, min(8, r + dr)), max(0, min(8, c + dc)))
            self.update()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), BG_CANVAS)

        self._draw_cell_backgrounds(painter)
        self._draw_grid_lines(painter)
        self._draw_numbers(painter)
        self._draw_hud(painter)
        if self.solved:
            self._draw_solved(painter)
        elif self.failed:
            self._draw_failed(painter)
        painter.end()

    def _cell_rect(self, r, c):
        return QRect(MARGIN + c * CELL, MARGIN + r * CELL, CELL, CELL)

    def _draw_cell_backgrounds(self, painter):
        sel_r, sel_c = self.selected if self.selected else (None, None)
        for r in range(9):
            for c in range(9):
                rect = self._cell_rect(r, c)
                if (r, c) == (sel_r, sel_c):
                    color = CELL_BG_SELECTED
                elif sel_r is not None and (r == sel_r or c == sel_c):
                    color = CELL_BG_PEER
                else:
                    color = CELL_BG
                painter.fillRect(rect, color)

    def _draw_grid_lines(self, painter):
        for i in range(10):
            bold = i % 3 == 0
            pen = QPen(GRID_LINE_BOLD if bold else GRID_LINE, 2.5 if bold else 1)
            painter.setPen(pen)
            x = MARGIN + i * CELL
            painter.drawLine(x, MARGIN, x, MARGIN + GRID_SIZE)
            y = MARGIN + i * CELL
            painter.drawLine(MARGIN, y, MARGIN + GRID_SIZE, y)

    def _draw_numbers(self, painter):
        painter.setFont(QFont("Arial", 20))
        for r in range(9):
            for c in range(9):
                n = self.grid[r][c]
                if n == 0:
                    continue
                if self._is_wrong(r, c):
                    color = CONFLICT_TEXT
                elif self.given[r][c]:
                    color = GIVEN_TEXT
                else:
                    color = ENTERED_TEXT
                painter.setPen(QPen(color))
                painter.drawText(self._cell_rect(r, c), Qt.AlignmentFlag.AlignCenter, str(n))

    def _draw_hud(self, painter):
        painter.setFont(QFont("Arial", 11))
        y = MARGIN + GRID_SIZE + 24
        painter.setPen(QPen(MUTED_COLOR))
        painter.drawText(MARGIN, y, f"Difficulty: {self.difficulty}")
        painter.setPen(QPen(CONFLICT_TEXT if self.mistakes else MUTED_COLOR))
        painter.drawText(MARGIN + 150, y, f"Mistakes: {self.mistakes}/{MAX_MISTAKES}")
        painter.setPen(QPen(MUTED_COLOR))
        painter.drawText(self.width() - 220, y, "Click a cell, type 1-9, Backspace to clear")

    def _draw_solved(self, painter):
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 28, QFont.Weight.Bold))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Solved!")

    def _draw_failed(self, painter):
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        painter.setPen(QPen(CONFLICT_TEXT))
        painter.setFont(QFont("Arial", 28, QFont.Weight.Bold))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"Game Over\n{MAX_MISTAKES} mistakes reached")
