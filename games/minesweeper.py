"""Minesweeper. Pure PyQt6 (QPainter, mouse events), no extra dependencies -
same self-contained style as games/sudoku.py. Turn-based rather than a
QTimer game loop, aside from a slow tick that just refreshes the on-screen
clock while a round is in progress.
"""
import json
import os
import random
import time

from PyQt6.QtCore import QPointF, QRect, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from core import config as core_config
from games.start_screen import consume_start_input, draw_start_screen

CELL = 26
HEADER_HEIGHT = 46
MARGIN = 10

# (columns, rows, mine_count) - the three standard Minesweeper presets.
DIFFICULTIES = {
    "Beginner": (9, 9, 10),
    "Intermediate": (16, 16, 40),
    "Expert": (30, 16, 99),
}

BG_CANVAS = QColor("#12121a")
HEADER_BG = QColor("#1a1a24")
CELL_HIDDEN = QColor("#2a2a38")
CELL_HIDDEN_BORDER = QColor("#3e3e50")
CELL_REVEALED = QColor("#1a1a24")
CELL_REVEALED_BORDER = QColor("#2a2a38")
CELL_MINE_HIT = QColor("#e5484d")
TEXT_COLOR = QColor("#eaeaf2")
MUTED_COLOR = QColor("#9494a6")
ACCENT = QColor("#7c5cff")
FLAG_COLOR = QColor("#e5484d")
NUMBER_COLORS = {
    1: QColor("#4c8bf5"), 2: QColor("#3ecf8e"), 3: QColor("#e5484d"),
    4: QColor("#7c5cff"), 5: QColor("#b5495b"), 6: QColor("#2ea8a8"),
    7: QColor("#eaeaf2"), 8: QColor("#9494a6"),
}


def _neighbors(r, c, rows, cols):
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                yield nr, nc


class MinesweeperWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self.best_times = self._load_best_times()
        self.started = False  # gated by a start screen - see games/start_screen.py
        self.difficulty = "Beginner"
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
        self.cols, self.rows, self.mine_count = DIFFICULTIES[self.difficulty]
        self.setFixedSize(
            self.cols * CELL + MARGIN * 2,
            self.rows * CELL + MARGIN * 2 + HEADER_HEIGHT,
        )

        self.mines = set()
        self.adjacent = [[0] * self.cols for _ in range(self.rows)]
        self.revealed = [[False] * self.cols for _ in range(self.rows)]
        self.flagged = [[False] * self.cols for _ in range(self.rows)]
        self.state = "ready"  # ready -> playing -> won/lost
        self.mines_placed = False
        self.start_time = None
        self.elapsed = 0.0
        self.exploded = None
        self.update()

    def _place_mines(self, safe_r, safe_c):
        safe_cells = {(safe_r, safe_c)} | set(_neighbors(safe_r, safe_c, self.rows, self.cols))
        candidates = [
            (r, c) for r in range(self.rows) for c in range(self.cols)
            if (r, c) not in safe_cells
        ]
        self.mines = set(random.sample(candidates, min(self.mine_count, len(candidates))))
        for r in range(self.rows):
            for c in range(self.cols):
                if (r, c) not in self.mines:
                    self.adjacent[r][c] = sum(1 for n in _neighbors(r, c, self.rows, self.cols) if n in self.mines)
        self.mines_placed = True

    # ------------------------------------------------------------------
    # Reveal / flag / chord
    # ------------------------------------------------------------------
    def _reveal(self, r, c):
        if self.state not in ("ready", "playing"):
            return
        if self.flagged[r][c] or self.revealed[r][c]:
            return
        if self.state == "ready":
            self._place_mines(r, c)
            self.state = "playing"
            self.start_time = time.monotonic()

        if (r, c) in self.mines:
            self.exploded = (r, c)
            self._lose()
            return

        self._flood_reveal(r, c)
        self._check_win()

    def _flood_reveal(self, r, c):
        stack = [(r, c)]
        while stack:
            cr, cc = stack.pop()
            if self.revealed[cr][cc] or self.flagged[cr][cc]:
                continue
            self.revealed[cr][cc] = True
            if self.adjacent[cr][cc] == 0:
                for nr, nc in _neighbors(cr, cc, self.rows, self.cols):
                    if not self.revealed[nr][nc] and (nr, nc) not in self.mines:
                        stack.append((nr, nc))

    def _toggle_flag(self, r, c):
        if self.state not in ("ready", "playing") or self.revealed[r][c]:
            return
        self.flagged[r][c] = not self.flagged[r][c]

    def _chord(self, r, c):
        if self.state != "playing" or not self.revealed[r][c] or self.adjacent[r][c] == 0:
            return
        neighbors = list(_neighbors(r, c, self.rows, self.cols))
        flagged_count = sum(1 for nr, nc in neighbors if self.flagged[nr][nc])
        if flagged_count != self.adjacent[r][c]:
            return
        for nr, nc in neighbors:
            if not self.flagged[nr][nc] and not self.revealed[nr][nc]:
                if (nr, nc) in self.mines:
                    self.exploded = (nr, nc)
                    self._lose()
                    return
                self._flood_reveal(nr, nc)
        self._check_win()

    def _check_win(self):
        total = self.rows * self.cols
        if sum(row.count(True) for row in self.revealed) == total - len(self.mines):
            self.state = "won"
            self.flagged = [[(r, c) in self.mines for c in range(self.cols)] for r in range(self.rows)]
            self._finish_timer()
            prev = self.best_times.get(self.difficulty)
            if prev is None or self.elapsed < prev:
                self.best_times[self.difficulty] = self.elapsed
            self.save_now()

    def _lose(self):
        self.state = "lost"
        self._finish_timer()

    def _finish_timer(self):
        if self.start_time is not None:
            self.elapsed = time.monotonic() - self.start_time

    # ------------------------------------------------------------------
    # Persistence - only best completion time per difficulty. A round is a
    # short, self-contained session (like games/neon_racer.py's races), not
    # an in-progress board worth freezing and resuming like Sudoku's.
    # ------------------------------------------------------------------
    def _save_path(self):
        return os.path.join(core_config.path("games"), "minesweeper_save.json")

    def _load_best_times(self):
        try:
            with open(self._save_path(), "r", encoding="utf-8") as f:
                return json.load(f).get("best_times", {})
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def save_now(self):
        path = self._save_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"best_times": self.best_times}, f)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def _cell_at(self, pos):
        x, y = pos.x() - MARGIN, pos.y() - MARGIN - HEADER_HEIGHT
        if x < 0 or y < 0:
            return None
        c, r = int(x // CELL), int(y // CELL)
        if 0 <= r < self.rows and 0 <= c < self.cols:
            return r, c
        return None

    def mousePressEvent(self, event):
        if consume_start_input(self):
            return
        if self.state in ("won", "lost") or self.state == "ready":
            if event.button() == Qt.MouseButton.LeftButton and self._smiley_rect().contains(event.position().toPoint()):
                self._new_game()
                return
        cell = self._cell_at(event.position().toPoint())
        if cell is None:
            return
        r, c = cell
        if event.button() == Qt.MouseButton.LeftButton:
            if self.revealed[r][c]:
                self._chord(r, c)
            else:
                self._reveal(r, c)
        elif event.button() == Qt.MouseButton.RightButton:
            self._toggle_flag(r, c)
        elif event.button() == Qt.MouseButton.MiddleButton:
            self._chord(r, c)
        self.update()

    def keyPressEvent(self, event):
        if consume_start_input(self):
            return
        if event.key() == Qt.Key.Key_N:
            self._new_game()

    def _smiley_rect(self):
        return QRect(self.width() // 2 - 16, MARGIN, 32, 32)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), BG_CANVAS)

        self._draw_header(painter)
        self._draw_grid(painter)

        if not self.started:
            draw_start_screen(painter, self.rect(), "Minesweeper", [
                "Left click to reveal a cell, right click to flag a suspected mine.",
                "Click a revealed number whose flagged neighbors match it to clear the rest.",
                "Clear every non-mine cell to win. N for a new game.",
                "Click or press any key to begin.",
            ])
        painter.end()

    def _draw_header(self, painter):
        painter.fillRect(0, 0, self.width(), HEADER_HEIGHT, HEADER_BG)
        flags = sum(row.count(True) for row in self.flagged)
        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        painter.drawText(QRect(MARGIN, 0, 100, HEADER_HEIGHT), Qt.AlignmentFlag.AlignVCenter, f"{self.mine_count - flags:03d}")

        elapsed = self.elapsed if self.state in ("won", "lost") else (
            time.monotonic() - self.start_time if self.start_time else 0.0
        )
        painter.drawText(QRect(self.width() - MARGIN - 100, 0, 100, HEADER_HEIGHT),
                          Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{elapsed:05.1f}")

        smiley = {"ready": "🙂", "playing": "🙂", "won": "😎", "lost": "💀"}[self.state]
        painter.setFont(QFont("Arial", 16))
        painter.drawText(self._smiley_rect(), Qt.AlignmentFlag.AlignCenter, smiley)

        if self.best_times.get(self.difficulty) is not None:
            painter.setFont(QFont("Arial", 9))
            painter.setPen(QPen(MUTED_COLOR))
            painter.drawText(QRect(0, HEADER_HEIGHT - 14, self.width(), 14), Qt.AlignmentFlag.AlignCenter,
                              f"Best: {self.best_times[self.difficulty]:.1f}s")

    def _draw_grid(self, painter):
        for r in range(self.rows):
            for c in range(self.cols):
                x = MARGIN + c * CELL
                y = MARGIN + HEADER_HEIGHT + r * CELL
                rect = QRect(x, y, CELL - 1, CELL - 1)
                is_mine = (r, c) in self.mines
                if self.revealed[r][c] or (self.state == "lost" and is_mine):
                    bg = CELL_MINE_HIT if self.exploded == (r, c) else CELL_REVEALED
                    painter.setPen(QPen(CELL_REVEALED_BORDER))
                    painter.setBrush(QBrush(bg))
                    painter.drawRect(rect)
                    if is_mine:
                        self._draw_mine(painter, rect)
                    elif self.adjacent[r][c] > 0:
                        painter.setPen(QPen(NUMBER_COLORS.get(self.adjacent[r][c], TEXT_COLOR)))
                        painter.setFont(QFont("Arial", 12, QFont.Weight.Bold))
                        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(self.adjacent[r][c]))
                else:
                    painter.setPen(QPen(CELL_HIDDEN_BORDER))
                    painter.setBrush(QBrush(CELL_HIDDEN))
                    painter.drawRect(rect)
                    if self.flagged[r][c]:
                        self._draw_flag(painter, rect)

    def _draw_mine(self, painter, rect):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#0c0c12")))
        cx, cy = rect.center().x(), rect.center().y()
        radius = rect.height() // 3
        painter.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)

    def _draw_flag(self, painter, rect):
        cx, cy = rect.center().x(), rect.center().y()
        painter.setPen(QPen(QColor("#0c0c12"), 1))
        painter.setBrush(QBrush(FLAG_COLOR))
        pole_x = cx - 2
        painter.drawLine(pole_x, cy - 8, pole_x, cy + 8)
        painter.drawPolygon(QPolygonF([
            QPointF(pole_x, cy - 8), QPointF(pole_x, cy - 1), QPointF(pole_x + 8, cy - 4.5),
        ]))
