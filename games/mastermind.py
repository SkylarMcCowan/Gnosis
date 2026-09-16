"""Mastermind - guess the hidden color sequence within a limited number of
tries, using black/white peg feedback (right color & position / right
color, wrong position) after each guess. Pure PyQt6 (QPainter, mouse
events), no extra dependencies, turn-based like games/sudoku.py.
"""
import json
import os
import random
from collections import Counter

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core import config as core_config
from games.start_screen import consume_start_input, draw_start_screen

# (code_length, palette_size, max_guesses)
DIFFICULTIES = {
    "Standard": (4, 6, 10),
    "Hard": (5, 8, 12),
}

PALETTE = [
    QColor("#e5484d"), QColor("#4c8bf5"), QColor("#3ecf8e"), QColor("#f5c344"),
    QColor("#7c5cff"), QColor("#f5799d"), QColor("#f5924c"), QColor("#2ea8a8"),
]

PEG_RADIUS = 15
PEG_GAP = 38
ROW_HEIGHT = 38
FEEDBACK_DOT_RADIUS = 4
MARGIN = 20
FEEDBACK_AREA_WIDTH = 90
HEADER_HEIGHT = 34
# Palette row, then the button on its own row below - stacked rather than
# side by side, since a wide palette (Hard mode's 8 colors) would otherwise
# collide with or run past a button anchored to the right edge.
FOOTER_HEIGHT = 92

BG_CANVAS = QColor("#12121a")
ROW_BG_PAST = QColor("#1a1a24")
ROW_BG_ACTIVE = QColor("#20203a")
SLOT_EMPTY = QColor("#2a2a38")
SLOT_BORDER = QColor("#3e3e50")
TEXT_COLOR = QColor("#eaeaf2")
MUTED_COLOR = QColor("#9494a6")
ACCENT = QColor("#7c5cff")
BLACK_PEG = QColor("#eaeaf2")
WHITE_PEG = QColor("#6a6a80")


def _score_guess(secret, guess):
    """Standard Mastermind scoring: black pegs for exact color+position
    matches, white pegs for correct colors in the wrong position - each
    peg (secret or guess) can only ever contribute to one scored match,
    which is why the "rest" tally is built only from the non-black
    positions before counting color overlaps."""
    black = sum(1 for s, g in zip(secret, guess) if s == g)
    secret_rest = Counter(s for s, g in zip(secret, guess) if s != g)
    guess_rest = Counter(g for s, g in zip(secret, guess) if s != g)
    white = sum(min(secret_rest[color], count) for color, count in guess_rest.items())
    return black, white


class MastermindWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.best_guesses = self._load_best_guesses()
        self.started = False  # gated by a start screen - see games/start_screen.py
        self.difficulty = "Standard"
        self._new_game(self.difficulty)

    # ------------------------------------------------------------------
    # Game state
    # ------------------------------------------------------------------
    def _new_game(self, difficulty=None):
        if difficulty:
            self.difficulty = difficulty
        self.code_length, self.palette_size, self.max_guesses = DIFFICULTIES[self.difficulty]
        self.secret = [random.randrange(self.palette_size) for _ in range(self.code_length)]
        self.history = []  # list of (guess_list, black, white)
        self.current_guess = [None] * self.code_length
        self.selected_color = 0
        self.state = "playing"  # playing -> won/lost

        # Wide enough for whichever needs more room: the guess row (pegs +
        # feedback dots) or the palette swatches (up to 8 of them in Hard
        # mode) - otherwise the palette would run past the widget's edge.
        board_width = MARGIN * 2 + max(
            self.code_length * PEG_GAP + FEEDBACK_AREA_WIDTH,
            self.palette_size * PEG_GAP,
        )
        board_height = HEADER_HEIGHT + (self.max_guesses + 1) * ROW_HEIGHT + FOOTER_HEIGHT
        self.setFixedSize(board_width, board_height)
        self.update()

    def _submit_guess(self):
        if self.state != "playing" or any(slot is None for slot in self.current_guess):
            return
        guess = list(self.current_guess)
        black, white = _score_guess(self.secret, guess)
        self.history.append((guess, black, white))
        if black == self.code_length:
            self.state = "won"
            guesses_used = len(self.history)
            prev = self.best_guesses.get(self.difficulty)
            if prev is None or guesses_used < prev:
                self.best_guesses[self.difficulty] = guesses_used
            self.save_now()
        elif len(self.history) >= self.max_guesses:
            self.state = "lost"
        else:
            self.current_guess = [None] * self.code_length

    # ------------------------------------------------------------------
    # Persistence - only the fewest guesses needed to win, per difficulty.
    # A round is a short session, not a board worth mid-game resume.
    # ------------------------------------------------------------------
    def _save_path(self):
        return os.path.join(core_config.path("games"), "mastermind_save.json")

    def _load_best_guesses(self):
        try:
            with open(self._save_path(), "r", encoding="utf-8") as f:
                return json.load(f).get("best_guesses", {})
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def save_now(self):
        path = self._save_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"best_guesses": self.best_guesses}, f)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def _active_row_rect(self):
        y = HEADER_HEIGHT + len(self.history) * ROW_HEIGHT
        return QRect(0, y, self.width(), ROW_HEIGHT)

    def _palette_rect(self, index):
        x = MARGIN + index * PEG_GAP
        y = HEADER_HEIGHT + (self.max_guesses + 1) * ROW_HEIGHT + 8
        return QRect(x, y, PEG_GAP, 32)

    def _submit_button_rect(self):
        button_width = 100
        x = (self.width() - button_width) // 2
        y = HEADER_HEIGHT + (self.max_guesses + 1) * ROW_HEIGHT + 50
        return QRect(x, y, button_width, 30)

    def mousePressEvent(self, event):
        if consume_start_input(self):
            return
        pos = event.position().toPoint()

        if self.state != "playing":
            if self._submit_button_rect().contains(pos):
                self._new_game()
                self.update()
            return

        for i in range(self.palette_size):
            if self._palette_rect(i).contains(pos):
                self.selected_color = i
                self.update()
                return

        if self._submit_button_rect().contains(pos):
            self._submit_guess()
            self.update()
            return

        active_rect = self._active_row_rect()
        if active_rect.contains(pos):
            slot = (pos.x() - MARGIN) // PEG_GAP
            if 0 <= slot < self.code_length:
                if event.button() == Qt.MouseButton.RightButton:
                    self.current_guess[slot] = None
                else:
                    self.current_guess[slot] = self.selected_color
                self.update()

    def keyPressEvent(self, event):
        if consume_start_input(self):
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._submit_guess()
        elif event.key() == Qt.Key.Key_N:
            self._new_game()
        self.update()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), BG_CANVAS)

        self._draw_header(painter)
        self._draw_rows(painter)
        self._draw_footer(painter)

        if not self.started:
            draw_start_screen(painter, self.rect(), "Mastermind", [
                "Guess the hidden color sequence - duplicates allowed.",
                "Click a palette swatch, then click a slot in the active row to place it.",
                "Black pegs = right color & position, white pegs = right color, wrong spot.",
                "Click or press any key to begin.",
            ])
        elif self.state in ("won", "lost"):
            self._draw_result(painter)
        painter.end()

    def _draw_header(self, painter):
        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        painter.drawText(QRect(MARGIN, 0, self.width() - MARGIN * 2, HEADER_HEIGHT),
                          Qt.AlignmentFlag.AlignVCenter, f"Guess {len(self.history)}/{self.max_guesses}")
        best = self.best_guesses.get(self.difficulty)
        if best is not None:
            painter.setPen(QPen(MUTED_COLOR))
            painter.setFont(QFont("Arial", 10))
            painter.drawText(QRect(MARGIN, 0, self.width() - MARGIN * 2, HEADER_HEIGHT),
                              Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"Best: {best}")

    def _draw_peg(self, painter, cx, cy, color_index):
        painter.setPen(QPen(QColor("#0c0c12"), 1.5))
        if color_index is None:
            painter.setBrush(QBrush(SLOT_EMPTY))
        else:
            painter.setBrush(QBrush(PALETTE[color_index % len(PALETTE)]))
        painter.drawEllipse(int(cx - PEG_RADIUS), int(cy - PEG_RADIUS), PEG_RADIUS * 2, PEG_RADIUS * 2)

    def _draw_feedback(self, painter, x, y, black, white):
        dots_per_row = 4
        for i in range(black + white):
            dx = x + (i % dots_per_row) * (FEEDBACK_DOT_RADIUS * 2 + 4)
            dy = y + (i // dots_per_row) * (FEEDBACK_DOT_RADIUS * 2 + 4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(BLACK_PEG if i < black else WHITE_PEG))
            painter.drawEllipse(int(dx), int(dy), FEEDBACK_DOT_RADIUS * 2, FEEDBACK_DOT_RADIUS * 2)

    def _draw_rows(self, painter):
        for row_index in range(self.max_guesses):
            y = HEADER_HEIGHT + row_index * ROW_HEIGHT
            is_active = row_index == len(self.history) and self.state == "playing"
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(ROW_BG_ACTIVE if is_active else ROW_BG_PAST))
            painter.drawRect(0, y, self.width(), ROW_HEIGHT)

            if row_index < len(self.history):
                guess, black, white = self.history[row_index]
                for i, color_index in enumerate(guess):
                    self._draw_peg(painter, MARGIN + i * PEG_GAP + PEG_RADIUS, y + ROW_HEIGHT / 2, color_index)
                self._draw_feedback(painter, MARGIN + self.code_length * PEG_GAP + 10, y + 6, black, white)
            elif is_active:
                for i, color_index in enumerate(self.current_guess):
                    self._draw_peg(painter, MARGIN + i * PEG_GAP + PEG_RADIUS, y + ROW_HEIGHT / 2, color_index)
            else:
                for i in range(self.code_length):
                    self._draw_peg(painter, MARGIN + i * PEG_GAP + PEG_RADIUS, y + ROW_HEIGHT / 2, None)

    def _draw_footer(self, painter):
        for i in range(self.palette_size):
            rect = self._palette_rect(i)
            cx, cy = rect.center().x(), rect.center().y()
            self._draw_peg(painter, cx, cy, i)
            if i == self.selected_color and self.state == "playing":
                painter.setPen(QPen(ACCENT, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(int(cx - PEG_RADIUS - 3), int(cy - PEG_RADIUS - 3), (PEG_RADIUS + 3) * 2, (PEG_RADIUS + 3) * 2)

        button_rect = self._submit_button_rect()
        painter.setPen(QPen(ACCENT, 1.5))
        painter.setBrush(QBrush(QColor(124, 92, 255, 40)))
        painter.drawRoundedRect(button_rect, 6, 6)
        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        label = "New Game" if self.state != "playing" else "Submit"
        painter.drawText(button_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_result(self, painter):
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        title = "You cracked it!" if self.state == "won" else "Out of guesses"
        painter.drawText(QRect(0, self.height() // 2 - 70, self.width(), 40), Qt.AlignmentFlag.AlignCenter, title)

        secret_y = self.height() // 2 - 10
        total_width = self.code_length * PEG_GAP
        start_x = (self.width() - total_width) / 2 + PEG_RADIUS
        painter.setFont(QFont("Arial", 10))
        painter.drawText(QRect(0, secret_y - 18, self.width(), 16), Qt.AlignmentFlag.AlignCenter, "The code was:")
        for i, color_index in enumerate(self.secret):
            self._draw_peg(painter, start_x + i * PEG_GAP, secret_y, color_index)
