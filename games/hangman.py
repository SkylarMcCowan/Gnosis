"""Hangman. Pure PyQt6 (QPainter, key events), no extra dependencies - same
"self-contained, no external assets" style as games/sudoku.py.

Turn-based like Sudoku (no QTimer game loop for gameplay itself): a word is
picked once per "New Game" from a chosen category, then play is just
guessing letters. A separate lightweight timer drives short-lived visual
effects (a shake + flash on a wrong guess) without needing a real game loop.
"""
import json
import os
import random

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core import config as core_config
from games.audio import SoundPlayer

CANVAS_WIDTH = 560
CANVAS_HEIGHT = 420
MAX_WRONG = 6

BG_CANVAS = QColor("#12121a")
PANEL_BG = QColor("#181822")
PANEL_BORDER = QColor("#2a2a38")
GALLOWS_COLOR = QColor("#6a6a80")
FIGURE_COLOR = QColor("#e5484d")
TEXT_COLOR = QColor("#eaeaf2")
ACCENT_COLOR = QColor("#7c5cff")
MUTED_COLOR = QColor("#9494a6")
CORRECT_COLOR = QColor("#3ecf8e")
WRONG_COLOR = QColor("#e5484d")

TILE_SIZE = 34
TILE_GAP = 6
TILE_Y = 300

SHAKE_MAX_FRAMES = 12
FLASH_MAX_FRAMES = 12

CATEGORIES = {
    "Animals": [
        "ELEPHANT", "GIRAFFE", "PENGUIN", "DOLPHIN", "KANGAROO", "OCTOPUS",
        "CHEETAH", "FLAMINGO", "RACCOON", "PLATYPUS", "SQUIRREL", "PEACOCK",
        "HEDGEHOG", "MEERKAT", "WALRUS", "OTTER", "IGUANA", "GAZELLE",
    ],
    "Countries": [
        "CANADA", "BRAZIL", "JAPAN", "EGYPT", "NORWAY", "MEXICO",
        "THAILAND", "PORTUGAL", "ARGENTINA", "VIETNAM", "MOROCCO", "ICELAND",
        "COLOMBIA", "GREECE", "FINLAND", "INDONESIA", "KENYA", "CROATIA",
    ],
    "Food": [
        "SPAGHETTI", "AVOCADO", "PANCAKE", "BURRITO", "PRETZEL", "LASAGNA",
        "SANDWICH", "BROCCOLI", "PINEAPPLE", "OMELETTE", "CASSEROLE",
        "DUMPLING", "MERINGUE", "WAFFLE", "HUMMUS", "RISOTTO",
    ],
    "Technology": [
        "KEYBOARD", "ALGORITHM", "BLUETOOTH", "PROCESSOR", "DATABASE",
        "FIREWALL", "SOFTWARE", "NETWORK", "COMPILER", "ENCRYPTION",
        "BANDWIDTH", "PROTOCOL", "INTERFACE", "MICROCHIP",
    ],
    "Movies": [
        "GLADIATOR", "INCEPTION", "TITANIC", "AVATAR", "JAWS", "GOODFELLAS",
        "CASABLANCA", "PSYCHO", "AMADEUS", "ROCKY", "ALIEN", "FROZEN",
    ],
}
ALPHABET = [chr(ord("A") + i) for i in range(26)]


def _random_word(category):
    if category == "Random":
        pool = [w for words in CATEGORIES.values() for w in words]
    else:
        pool = CATEGORIES.get(category, CATEGORIES["Animals"])
    return random.choice(pool)


class HangmanWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(CANVAS_WIDTH, CANVAS_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.category = "Random"
        self.sounds = SoundPlayer()
        self.shake_frames = 0
        self.wrong_flash_frames = 0
        self.correct_flash_frames = 0
        saved = self._load_save()
        if saved:
            self._restore_from_save(saved)
        else:
            self._new_game()

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.save_now)
        self.autosave_timer.start(15_000)

        self.effect_timer = QTimer(self)
        self.effect_timer.timeout.connect(self._tick_effects)
        self.effect_timer.start(16)

    # ------------------------------------------------------------------
    # Game state
    # ------------------------------------------------------------------
    def _new_game(self, category=None):
        if category is not None:
            self.category = category
        self.word = _random_word(self.category)
        self.guessed = set()
        self.wrong_count = 0
        self.solved = False
        self.failed = False
        self.shake_frames = 0
        self.wrong_flash_frames = 0
        self.correct_flash_frames = 0
        self.update()
        self.save_now()

    def _guess(self, letter):
        if self.solved or self.failed or letter in self.guessed:
            return
        self.guessed.add(letter)
        if letter in self.word:
            self.correct_flash_frames = FLASH_MAX_FRAMES
            self.sounds.play("hangman_correct")
            if all(ch in self.guessed for ch in self.word):
                self.solved = True
                self.sounds.play("hangman_win")
        else:
            self.wrong_count += 1
            self.shake_frames = SHAKE_MAX_FRAMES
            self.wrong_flash_frames = FLASH_MAX_FRAMES
            self.sounds.play("hangman_wrong")
            if self.wrong_count >= MAX_WRONG:
                self.failed = True
                self.sounds.play("hangman_lose")
        if self.solved or self.failed:
            self.save_now()
        self.update()

    def _tick_effects(self):
        if self.shake_frames <= 0 and self.wrong_flash_frames <= 0 and self.correct_flash_frames <= 0:
            return
        self.shake_frames = max(0, self.shake_frames - 1)
        self.wrong_flash_frames = max(0, self.wrong_flash_frames - 1)
        self.correct_flash_frames = max(0, self.correct_flash_frames - 1)
        self.update()

    # ------------------------------------------------------------------
    # Persistence - same lazy-mkdir-on-write-only pattern as
    # core/activity_log.py and core/subscriptions.py: a read must never
    # create the directory, only a write does.
    # ------------------------------------------------------------------
    def _save_path(self):
        return os.path.join(core_config.path("games"), "hangman_save.json")

    def _load_save(self):
        path = self._save_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _restore_from_save(self, data):
        try:
            self.category = data.get("category", "Random")
            self.word = data["word"]
            self.guessed = set(data["guessed"])
            self.wrong_count = data.get("wrong_count", 0)
            self.solved = data.get("solved", False)
            self.failed = data.get("failed", False)
        except KeyError:
            self._new_game()

    def save_now(self):
        """Called periodically (self.autosave_timer) and by the main
        window before it closes - see webagent_gui.py's closeEvent."""
        if not hasattr(self, "word"):
            return
        data = {
            "category": self.category, "word": self.word, "guessed": sorted(self.guessed),
            "wrong_count": self.wrong_count, "solved": self.solved, "failed": self.failed,
        }
        path = self._save_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if self.solved or self.failed:
            self._new_game()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_N and (self.solved or self.failed):
            self._new_game()
            return
        text = event.text().upper()
        if len(text) == 1 and text in ALPHABET:
            self._guess(text)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), BG_CANVAS)

        shake_dx = 0
        if self.shake_frames > 0:
            amplitude = int(7 * self.shake_frames / SHAKE_MAX_FRAMES)
            shake_dx = amplitude if self.shake_frames % 2 == 0 else -amplitude

        painter.save()
        painter.translate(shake_dx, 0)
        self._draw_gallows(painter)
        painter.restore()

        self._draw_word_tiles(painter, shake_dx)
        self._draw_alphabet(painter)
        self._draw_hud(painter)
        if self.solved:
            self._draw_overlay(painter, CORRECT_COLOR, "You got it!")
        elif self.failed:
            self._draw_overlay(painter, WRONG_COLOR, f"Game Over\nThe word was: {self.word}")
        painter.end()

    def _draw_gallows(self, painter):
        pen = QPen(GALLOWS_COLOR, 4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(30, 340, 170, 340)   # base
        painter.drawLine(70, 340, 70, 30)     # pole
        painter.drawLine(66, 30, 190, 30)     # beam
        painter.drawLine(190, 30, 190, 60)    # rope

        figure_pen = QPen(FIGURE_COLOR, 5)
        figure_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(figure_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        w = self.wrong_count
        if w >= 1:
            painter.drawEllipse(170, 60, 40, 40)  # head
        if w >= 2:
            painter.drawLine(190, 100, 190, 190)  # body
        if w >= 3:
            painter.drawLine(190, 120, 160, 160)  # left arm
        if w >= 4:
            painter.drawLine(190, 120, 220, 160)  # right arm
        if w >= 5:
            painter.drawLine(190, 190, 165, 240)  # left leg
        if w >= 6:
            painter.drawLine(190, 190, 215, 240)  # right leg

    def _draw_word_tiles(self, painter, shake_dx):
        n = len(self.word)
        total_width = n * TILE_SIZE + (n - 1) * TILE_GAP
        start_x = (CANVAS_WIDTH - total_width) // 2 + shake_dx

        flash_color = None
        if self.wrong_flash_frames > 0:
            alpha = int(120 * self.wrong_flash_frames / FLASH_MAX_FRAMES)
            flash_color = QColor(WRONG_COLOR.red(), WRONG_COLOR.green(), WRONG_COLOR.blue(), alpha)
        elif self.correct_flash_frames > 0:
            alpha = int(120 * self.correct_flash_frames / FLASH_MAX_FRAMES)
            flash_color = QColor(CORRECT_COLOR.red(), CORRECT_COLOR.green(), CORRECT_COLOR.blue(), alpha)

        painter.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        for i, ch in enumerate(self.word):
            x = start_x + i * (TILE_SIZE + TILE_GAP)
            revealed = ch in self.guessed or self.failed
            painter.setPen(QPen(PANEL_BORDER, 1))
            painter.setBrush(QBrush(PANEL_BG if not revealed else QColor("#20202e")))
            painter.drawRoundedRect(x, TILE_Y, TILE_SIZE, TILE_SIZE, 6, 6)
            if flash_color is not None:
                painter.setBrush(QBrush(flash_color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(x, TILE_Y, TILE_SIZE, TILE_SIZE, 6, 6)
            if revealed:
                painter.setPen(QPen(TEXT_COLOR))
                painter.drawText(x, TILE_Y, TILE_SIZE, TILE_SIZE, Qt.AlignmentFlag.AlignCenter, ch)

    def _draw_alphabet(self, painter):
        badge = 20
        gap = 3
        cols = 13
        start_x = (CANVAS_WIDTH - cols * (badge + gap)) // 2
        y0 = 355
        painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        for i, letter in enumerate(ALPHABET):
            col, row = i % cols, i // cols
            x = start_x + col * (badge + gap)
            y = y0 + row * (badge + gap)
            if letter not in self.guessed:
                border, fill = MUTED_COLOR, None
            elif letter in self.word:
                border, fill = CORRECT_COLOR, QColor(62, 207, 142, 60)
            else:
                border, fill = WRONG_COLOR, QColor(229, 72, 77, 60)
            painter.setPen(QPen(border, 1))
            painter.setBrush(QBrush(fill) if fill else Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(x, y, badge, badge, 4, 4)
            painter.setPen(QPen(border))
            painter.drawText(x, y, badge, badge, Qt.AlignmentFlag.AlignCenter, letter)

    def _draw_hud(self, painter):
        painter.setPen(QPen(ACCENT_COLOR))
        painter.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        painter.drawText(260, 32, f"Category: {self.category}")
        painter.setFont(QFont("Arial", 11))
        painter.setPen(QPen(WRONG_COLOR if self.wrong_count else MUTED_COLOR))
        painter.drawText(260, 54, f"Wrong: {self.wrong_count}/{MAX_WRONG}")
        painter.setPen(QPen(MUTED_COLOR))
        painter.drawText(260, 76, "Type a letter to guess")

    def _draw_overlay(self, painter, color, text):
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        painter.setPen(QPen(color))
        painter.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text + "\nClick or N for a new word")
