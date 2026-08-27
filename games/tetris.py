"""Tetris. Pure PyQt6 (QPainter + QTimer), no extra dependencies - same
"self-contained, no external assets" style as games/zuma_endless.py,
games/solitaire.py and games/sudoku.py.

Standard 10x20 board, 7-bag piece randomizer, NES-style line scoring, a
ghost-piece preview, and a simple (no wall-kick) rotation - good enough for
a casual clone without the complexity of full SRS.
"""
import json
import os
import random
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core import config as core_config
from games.audio import SoundPlayer

COLS = 10
ROWS = 20
CELL = 26
MARGIN = 16
SIDE_PANEL = 170

BOARD_PX_WIDTH = COLS * CELL
BOARD_PX_HEIGHT = ROWS * CELL
CANVAS_WIDTH = MARGIN * 3 + BOARD_PX_WIDTH + SIDE_PANEL
CANVAS_HEIGHT = MARGIN * 2 + BOARD_PX_HEIGHT

BG_CANVAS = QColor("#12121a")
BOARD_BG = QColor("#1a1a24")
BOARD_BORDER = QColor("#7c5cff")
PANEL_BG = QColor("#181822")
PANEL_BORDER = QColor("#2a2a38")
GRID_LINE = QColor("#26263266")
TEXT_COLOR = QColor("#eaeaf2")
ACCENT_COLOR = QColor("#7c5cff")
MUTED_COLOR = QColor("#9494a6")
GHOST_ALPHA = 70
CLEAR_FLASH_DURATION = 0.18

PIECE_COLORS = {
    "I": QColor("#4cd3e5"),
    "O": QColor("#f5c344"),
    "T": QColor("#7c5cff"),
    "S": QColor("#3ecf8e"),
    "Z": QColor("#e5484d"),
    "J": QColor("#4c8bf5"),
    "L": QColor("#f59e44"),
}

# Each shape's cells within a 4x4 bounding box, in its spawn orientation.
BASE_SHAPES = {
    "I": [(1, 0), (1, 1), (1, 2), (1, 3)],
    "O": [(0, 1), (0, 2), (1, 1), (1, 2)],
    "T": [(0, 1), (1, 0), (1, 1), (1, 2)],
    "S": [(0, 1), (0, 2), (1, 0), (1, 1)],
    "Z": [(0, 0), (0, 1), (1, 1), (1, 2)],
    "J": [(0, 0), (1, 0), (1, 1), (1, 2)],
    "L": [(0, 2), (1, 0), (1, 1), (1, 2)],
}

LINE_SCORES = {1: 40, 2: 100, 3: 300, 4: 1200}
LINES_PER_LEVEL = 10
BASE_DROP_MS = 500
MIN_DROP_MS = 80
DROP_STEP_MS = 40


def _rotate_cells(cells):
    """Clockwise rotation within a 4x4 box: (r, c) -> (c, 3 - r). The O
    piece is special-cased by the caller since this formula would
    otherwise drift its position by a cell on every turn."""
    return [(c, 3 - r) for (r, c) in cells]


def _cells_for(piece_type, rotation):
    if piece_type == "O":
        return list(BASE_SHAPES["O"])
    cells = BASE_SHAPES[piece_type]
    for _ in range(rotation % 4):
        cells = _rotate_cells(cells)
    return cells


class TetrisWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(CANVAS_WIDTH, CANVAS_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.sounds = SoundPlayer()

        saved = self._load_save()
        if saved:
            self._restore_from_save(saved)
        else:
            self.high_score = 0
            self._reset_game()

        self._last_tick = time.monotonic()
        self._drop_accum = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.save_now)
        self.autosave_timer.start(15_000)

    # ------------------------------------------------------------------
    # Game state
    # ------------------------------------------------------------------
    def _reset_game(self):
        self.board = [[None] * COLS for _ in range(ROWS)]
        self.score = 0
        self.lines_cleared = 0
        self.level = 1
        self.state = "playing"  # or "paused", "clearing", "game_over"
        self.bag = []
        self.piece = None
        self.clearing_rows = []
        self.clear_timer = 0.0
        self._pending_overflow = False
        self.next_type = self._draw_from_bag()
        self._spawn_piece()
        self._drop_accum = 0.0

    def _draw_from_bag(self):
        if not self.bag:
            self.bag = list(BASE_SHAPES.keys())
            random.shuffle(self.bag)
        return self.bag.pop()

    def _spawn_piece(self):
        piece_type = self.next_type
        self.next_type = self._draw_from_bag()
        col = (COLS - 4) // 2
        self.piece = {"type": piece_type, "rotation": 0, "row": -2, "col": col}
        if self._collides(self.piece):
            self.state = "game_over"
            self.sounds.play("tetris_game_over")
            self.save_now()

    def _drop_interval(self):
        return max(MIN_DROP_MS, BASE_DROP_MS - (self.level - 1) * DROP_STEP_MS) / 1000.0

    # ------------------------------------------------------------------
    # Persistence - same lazy-mkdir-on-write-only pattern as
    # core/activity_log.py and core/subscriptions.py: a read must never
    # create the directory, only a write does.
    # ------------------------------------------------------------------
    def _save_path(self):
        return os.path.join(core_config.path("games"), "tetris_save.json")

    def _load_save(self):
        path = self._save_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _restore_from_save(self, data):
        try:
            self.board = data["board"]
            self.score = data["score"]
            self.lines_cleared = data["lines_cleared"]
            self.level = data["level"]
            self.high_score = data.get("high_score", 0)
            self.state = data.get("state", "playing")
            self.bag = data.get("bag", [])
            self.next_type = data["next_type"]
            piece = data["piece"]
            self.piece = {
                "type": piece["type"], "rotation": piece["rotation"],
                "row": piece["row"], "col": piece["col"],
            }
        except KeyError:
            self.high_score = data.get("high_score", 0)
            self._reset_game()
            return
        self.clearing_rows = []
        self.clear_timer = 0.0
        self._pending_overflow = False
        if self.state in ("paused", "clearing"):
            self.state = "playing"

    def save_now(self):
        """Called periodically (self.autosave_timer) and by the main
        window before it closes - see webagent_gui.py's closeEvent. A
        line-clear flash only ever lasts CLEAR_FLASH_DURATION (~180ms), but
        finishing it here first guarantees a save never lands mid-animation
        with full rows still sitting in self.board unremoved."""
        if not hasattr(self, "board") or self.piece is None:
            return
        if self.state == "clearing":
            self._finish_clear()
        data = {
            "board": self.board, "score": self.score, "lines_cleared": self.lines_cleared,
            "level": self.level, "high_score": self.high_score, "state": self.state,
            "bag": self.bag, "next_type": self.next_type, "piece": self.piece,
        }
        path = self._save_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Movement / collision
    # ------------------------------------------------------------------
    def _collides(self, piece):
        for r, c in _cells_for(piece["type"], piece["rotation"]):
            board_r, board_c = piece["row"] + r, piece["col"] + c
            if board_c < 0 or board_c >= COLS or board_r >= ROWS:
                return True
            if board_r >= 0 and self.board[board_r][board_c] is not None:
                return True
        return False

    def _try_move(self, drow, dcol, drotation=0):
        if self.state != "playing":
            return False
        candidate = dict(self.piece)
        candidate["row"] += drow
        candidate["col"] += dcol
        candidate["rotation"] = (candidate["rotation"] + drotation) % 4
        if self._collides(candidate):
            return False
        self.piece = candidate
        self.update()
        return True

    def _hard_drop(self):
        if self.state != "playing":
            return
        while self._try_move(1, 0):
            pass
        self._lock_piece()

    def _lock_piece(self):
        overflowed = False
        for r, c in _cells_for(self.piece["type"], self.piece["rotation"]):
            board_r, board_c = self.piece["row"] + r, self.piece["col"] + c
            if board_r < 0:
                overflowed = True
                continue
            self.board[board_r][board_c] = PIECE_COLORS[self.piece["type"]].name()

        cleared_rows = [r for r, row in enumerate(self.board) if all(cell is not None for cell in row)]
        if cleared_rows:
            self._apply_line_score(len(cleared_rows))
            self.sounds.play("tetris_tetris" if len(cleared_rows) == 4 else "tetris_line")
            self.state = "clearing"
            self.clearing_rows = cleared_rows
            self.clear_timer = 0.0
            self._pending_overflow = overflowed
            self.update()
            return

        self.sounds.play("tetris_lock")
        if overflowed:
            self.state = "game_over"
            self.sounds.play("tetris_game_over")
            self.save_now()
            self.update()
            return
        self._spawn_piece()
        self.update()

    def _finish_clear(self):
        """Removes the rows that finished flashing (self.clearing_rows) and
        either resumes play or, if the piece that caused the clear had also
        overflowed the top, ends the game - deferred out of _lock_piece so
        the flash has time to actually show before the board shifts."""
        remaining = [row for i, row in enumerate(self.board) if i not in self.clearing_rows]
        cleared = len(self.clearing_rows)
        self.board = [[None] * COLS for _ in range(cleared)] + remaining
        self.clearing_rows = []
        self.clear_timer = 0.0
        if self._pending_overflow:
            self._pending_overflow = False
            self.state = "game_over"
            self.sounds.play("tetris_game_over")
            self.save_now()
        else:
            self.state = "playing"
            self._spawn_piece()

    def _apply_line_score(self, cleared):
        self.score += LINE_SCORES.get(cleared, 1200) * self.level
        self.lines_cleared += cleared
        new_level = self.lines_cleared // LINES_PER_LEVEL + 1
        if new_level > self.level:
            self.level = new_level
            self.sounds.play("tetris_level_up")
        if self.score > self.high_score:
            self.high_score = self.score

    def _ghost_row(self):
        ghost = dict(self.piece)
        while True:
            trial = dict(ghost)
            trial["row"] += 1
            if self._collides(trial):
                return ghost["row"]
            ghost = trial

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------
    def _tick(self):
        now = time.monotonic()
        dt = min(now - self._last_tick, 0.05)
        self._last_tick = now
        if self.state == "clearing":
            self.clear_timer += dt
            if self.clear_timer >= CLEAR_FLASH_DURATION:
                self._finish_clear()
        elif self.state == "playing":
            self._drop_accum += dt
            interval = self._drop_interval()
            while self._drop_accum >= interval:
                self._drop_accum -= interval
                if not self._try_move(1, 0):
                    self._lock_piece()
                    break
        self.update()

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if self.state == "game_over":
            self._reset_game()
            self.update()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_N and self.state == "game_over":
            self._reset_game()
            self.update()
            return
        if key == Qt.Key.Key_P and self.state != "game_over":
            self.state = "paused" if self.state == "playing" else "playing"
            self.update()
            return
        if self.state != "playing":
            return
        if key == Qt.Key.Key_Left:
            if self._try_move(0, -1):
                self.sounds.play("tetris_move")
        elif key == Qt.Key.Key_Right:
            if self._try_move(0, 1):
                self.sounds.play("tetris_move")
        elif key == Qt.Key.Key_Down:
            if not self._try_move(1, 0):
                self._lock_piece()
            self._drop_accum = 0.0
        elif key == Qt.Key.Key_Up:
            if self._try_move(0, 0, drotation=1):
                self.sounds.play("tetris_rotate")
        elif key == Qt.Key.Key_Space:
            self._hard_drop()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), BG_CANVAS)

        board_rect_x, board_rect_y = MARGIN, MARGIN
        painter.fillRect(board_rect_x, board_rect_y, BOARD_PX_WIDTH, BOARD_PX_HEIGHT, BOARD_BG)
        self._draw_grid(painter, board_rect_x, board_rect_y)
        self._draw_locked_cells(painter, board_rect_x, board_rect_y)
        if self.state == "clearing":
            self._draw_clear_flash(painter, board_rect_x, board_rect_y)
        if self.state == "playing":
            self._draw_ghost(painter, board_rect_x, board_rect_y)
            self._draw_piece(painter, board_rect_x, board_rect_y)
        painter.setPen(QPen(BOARD_BORDER, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(board_rect_x, board_rect_y, BOARD_PX_WIDTH, BOARD_PX_HEIGHT)
        self._draw_side_panel(painter, board_rect_x + BOARD_PX_WIDTH + MARGIN)
        if self.state == "paused":
            self._draw_overlay(painter, "Paused")
        elif self.state == "game_over":
            self._draw_overlay(painter, f"Game Over\nScore: {self.score}\nClick or N to restart")
        painter.end()

    def _draw_grid(self, painter, ox, oy):
        painter.setPen(QPen(GRID_LINE, 1))
        for c in range(COLS + 1):
            x = ox + c * CELL
            painter.drawLine(x, oy, x, oy + BOARD_PX_HEIGHT)
        for r in range(ROWS + 1):
            y = oy + r * CELL
            painter.drawLine(ox, y, ox + BOARD_PX_WIDTH, y)

    def _draw_cell(self, painter, ox, oy, row, col, color, alpha=255):
        """A simple beveled block - a lighter top/left edge and a darker
        bottom/right one over the flat fill - so locked pieces read as
        solid blocks instead of flat colored squares."""
        rect_x, rect_y = ox + col * CELL, oy + row * CELL
        size = CELL - 2
        fill = QColor(color)
        fill.setAlpha(alpha)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fill))
        painter.drawRect(rect_x + 1, rect_y + 1, size, size)

        light = fill.lighter(160)
        dark = fill.darker(160)
        bevel = max(2, CELL // 8)
        painter.setBrush(QBrush(light))
        painter.drawRect(rect_x + 1, rect_y + 1, size, bevel)
        painter.drawRect(rect_x + 1, rect_y + 1, bevel, size)
        painter.setBrush(QBrush(dark))
        painter.drawRect(rect_x + 1, rect_y + 1 + size - bevel, size, bevel)
        painter.drawRect(rect_x + 1 + size - bevel, rect_y + 1, bevel, size)

    def _draw_locked_cells(self, painter, ox, oy):
        for r in range(ROWS):
            for c in range(COLS):
                if self.board[r][c] is not None:
                    self._draw_cell(painter, ox, oy, r, c, QColor(self.board[r][c]))

    def _draw_clear_flash(self, painter, ox, oy):
        """Rows finishing a clear flash white, fading out over
        CLEAR_FLASH_DURATION, before _finish_clear actually removes them -
        gives a line clear a beat of visual payoff instead of the rows
        just silently vanishing."""
        progress = min(1.0, self.clear_timer / CLEAR_FLASH_DURATION)
        alpha = int(230 * (1.0 - progress))
        color = QColor(255, 255, 255, alpha)
        for r in self.clearing_rows:
            painter.fillRect(ox, oy + r * CELL, BOARD_PX_WIDTH, CELL, color)

    def _draw_piece(self, painter, ox, oy):
        color = PIECE_COLORS[self.piece["type"]]
        for r, c in _cells_for(self.piece["type"], self.piece["rotation"]):
            board_r = self.piece["row"] + r
            if board_r >= 0:
                self._draw_cell(painter, ox, oy, board_r, self.piece["col"] + c, color)

    def _draw_ghost(self, painter, ox, oy):
        ghost_row = self._ghost_row()
        if ghost_row == self.piece["row"]:
            return
        color = QColor(PIECE_COLORS[self.piece["type"]])
        color.setAlpha(GHOST_ALPHA)
        for r, c in _cells_for(self.piece["type"], self.piece["rotation"]):
            board_r = ghost_row + r
            if board_r >= 0:
                rect_x, rect_y = ox + (self.piece["col"] + c) * CELL, oy + board_r * CELL
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(QColor("#0c0c12"), 1))
                painter.drawRect(rect_x + 1, rect_y + 1, CELL - 2, CELL - 2)

    def _draw_side_panel(self, painter, x):
        panel_width = SIDE_PANEL - MARGIN
        painter.setPen(QPen(PANEL_BORDER, 1))
        painter.setBrush(QBrush(PANEL_BG))
        painter.drawRect(x, MARGIN, panel_width, BOARD_PX_HEIGHT)

        pad = 14
        y = MARGIN + pad
        painter.setPen(QPen(ACCENT_COLOR))
        painter.setFont(QFont("Arial", 15, QFont.Weight.Bold))
        painter.drawText(x + pad, y + 10, f"Score: {self.score}")
        painter.setFont(QFont("Arial", 11))
        painter.setPen(QPen(MUTED_COLOR))
        painter.drawText(x + pad, y + 34, f"High Score: {self.high_score}")
        painter.drawText(x + pad, y + 54, f"Level: {self.level}")
        painter.drawText(x + pad, y + 74, f"Lines: {self.lines_cleared}")

        painter.setPen(QPen(PANEL_BORDER, 1))
        painter.drawLine(x + pad, y + 92, x + panel_width - pad, y + 92)

        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        painter.drawText(x + pad, y + 112, "Next")
        self._draw_next_preview(painter, x + pad, y + 122)

        painter.setPen(QPen(MUTED_COLOR))
        painter.setFont(QFont("Arial", 10))
        controls = [
            "Left/Right: move", "Up: rotate", "Down: soft drop",
            "Space: hard drop", "P: pause",
        ]
        cy = MARGIN + BOARD_PX_HEIGHT - pad - len(controls) * 16
        for line in controls:
            painter.drawText(x + pad, cy, line)
            cy += 16

    def _draw_next_preview(self, painter, x, y):
        preview_cell = 18
        box_size = preview_cell * 4 + 6
        painter.setPen(QPen(PANEL_BORDER, 1))
        painter.setBrush(QBrush(QColor("#12121a")))
        painter.drawRect(x, y, box_size, box_size)

        color = PIECE_COLORS[self.next_type]
        cells = BASE_SHAPES[self.next_type]
        min_c = min(c for _, c in cells)
        min_r = min(r for r, _ in cells)
        max_c = max(c for _, c in cells)
        max_r = max(r for r, _ in cells)
        offset_x = x + (box_size - (max_c - min_c + 1) * preview_cell) // 2
        offset_y = y + (box_size - (max_r - min_r + 1) * preview_cell) // 2
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(QColor("#0c0c12"), 1))
        for r, c in cells:
            rect_x = offset_x + (c - min_c) * preview_cell
            rect_y = offset_y + (r - min_r) * preview_cell
            painter.drawRect(rect_x, rect_y, preview_cell - 2, preview_cell - 2)

    def _draw_overlay(self, painter, text):
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        color = ACCENT_COLOR if self.state == "paused" else QColor("#e5484d")
        painter.setPen(QPen(color))
        painter.setFont(QFont("Arial", 22, QFont.Weight.Bold))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
