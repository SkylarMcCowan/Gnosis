"""Shared "press to begin" start-screen gate for the QPainter-based games
(games/zuma_endless.py, solitaire.py, sudoku.py, tetris.py, hangman.py) -
each one still loads (and restores any saved progress) fully during
__init__ as before, but game clocks stay frozen and input is inert until
the player deliberately starts, instead of the board being live the
instant the Games tab is opened. games/mystery.py uses ordinary layout
widgets rather than a QPainter canvas, so it gates via widget visibility
instead of this module (see its own start-overlay code).
"""
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPen

OVERLAY_BG = QColor(0, 0, 0, 165)
TITLE_COLOR = QColor("#eaeaf2")
SUBTITLE_COLOR = QColor("#9494a6")
PROMPT_COLOR = QColor("#7c5cff")


def consume_start_input(widget):
    """Call at the very top of a gated widget's mousePressEvent and
    keyPressEvent. The first input after load only dismisses the start
    screen - this returns True in that case, and the caller should return
    immediately without acting on the event. Once the game is running it
    returns False so the event falls through to normal handling."""
    if widget.started:
        return False
    widget.started = True
    widget.update()
    return True


def draw_start_screen(painter, rect, title, lines):
    """Dims the frozen board and shows a title plus a few description
    lines - the last of which is treated as the call-to-action ("Click or
    press ... to begin") and drawn in the accent color for emphasis."""
    painter.fillRect(rect, OVERLAY_BG)
    painter.setPen(QPen(TITLE_COLOR))
    painter.setFont(QFont("Arial", 26, QFont.Weight.Bold))
    title_rect = QRect(rect.x(), rect.y() + rect.height() // 2 - 30 - 12 * len(lines), rect.width(), 44)
    painter.drawText(title_rect, Qt.AlignmentFlag.AlignCenter, title)

    painter.setFont(QFont("Arial", 12))
    y = title_rect.bottom() + 14
    for i, line in enumerate(lines):
        painter.setPen(QPen(PROMPT_COLOR if i == len(lines) - 1 else SUBTITLE_COLOR))
        painter.drawText(QRect(rect.x(), y, rect.width(), 22), Qt.AlignmentFlag.AlignCenter, line)
        y += 24
