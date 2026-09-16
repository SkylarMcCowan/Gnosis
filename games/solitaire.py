"""Klondike Solitaire. Pure PyQt6 (QPainter, mouse events), no extra
dependencies, no card images - suits are drawn as Unicode glyphs, same
"no external assets" style as games/zuma_endless.py.

Unlike Zuma, this is turn-based/drag-based rather than a continuous
simulation, so there's no QTimer game loop here - repaints are driven by
mouse events only.
"""
import copy
import json
import os
import random

from PyQt6.QtCore import QPoint, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import QWidget

from core import config as core_config
from games.start_screen import consume_start_input, draw_start_screen

CARD_W, CARD_H = 72, 100
MARGIN = 24
COL_GAP = 14
HEADER_H = 36
TOP_Y = MARGIN + HEADER_H
TABLEAU_Y = TOP_Y + CARD_H + 40
STACK_OFFSET_FACEDOWN = 7
STACK_OFFSET_FACEUP = 24

CANVAS_WIDTH = MARGIN * 2 + 7 * CARD_W + 6 * COL_GAP
CANVAS_HEIGHT = 680

SUITS = ("♠", "♥", "♦", "♣")
RED_SUITS = {"♥", "♦"}
RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")

BG_TOP = QColor("#171826")
BG_BOTTOM = QColor("#0c0c14")
FELT_LINE = QColor(255, 255, 255, 10)
SLOT_OUTLINE = QColor("#3d3d4d")
CARD_BACK_TOP = QColor("#8f6bff")
CARD_BACK_BOTTOM = QColor("#5c3fd6")
CARD_BACK_BORDER = QColor("#2c1f70")
CARD_BACK_PATTERN = QColor(255, 255, 255, 28)
CARD_FACE_TOP = QColor("#fffdf7")
CARD_FACE_BOTTOM = QColor("#eae6da")
CARD_BORDER = QColor("#0c0c12")
RED_TEXT = QColor("#c8323a")
BLACK_TEXT = QColor("#1c1c26")
TEXT_COLOR = QColor("#eaeaf2")
MUTED_COLOR = QColor("#9494a6")
HIGHLIGHT = QColor("#f5c344")
SHADOW_COLOR = QColor(0, 0, 0, 90)
HOVER_GLOW = QColor("#f5c344")
DROP_OK = QColor("#5ad18f")
DROP_BAD = QColor("#e05a5a")
HEADER_TITLE = QColor("#e8e2ff")
CHIP_BG = QColor(255, 255, 255, 16)
CHIP_BORDER = QColor(255, 255, 255, 28)
BUTTON_BG = QColor(124, 92, 255, 55)
BUTTON_BG_HOVER = QColor(124, 92, 255, 110)
BUTTON_BORDER = QColor("#7c5cff")


def _new_deck():
    deck = []
    for suit in SUITS:
        for value, rank in enumerate(RANKS, start=1):
            deck.append({"suit": suit, "rank": rank, "value": value, "face_up": False})
    random.shuffle(deck)
    return deck


def _is_red(card):
    return card["suit"] in RED_SUITS


class SolitaireWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(CANVAS_WIDTH, CANVAS_HEIGHT)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hover_pos = None
        saved = self._load_save()
        if saved:
            self._restore_from_save(saved)
        else:
            self._new_game()
        self.started = False  # gated by a start screen - see games/start_screen.py

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.save_now)
        self.autosave_timer.start(15_000)

    # ------------------------------------------------------------------
    # Game state
    # ------------------------------------------------------------------
    def _new_game(self):
        deck = _new_deck()
        self.tableau = [[] for _ in range(7)]
        for col in range(7):
            for i in range(col + 1):
                card = deck.pop()
                card["face_up"] = (i == col)
                self.tableau[col].append(card)
        self.stock = deck  # remaining 24 cards, face down
        self.waste = []
        self.foundations = {suit: [] for suit in SUITS}
        self.history = []
        self.moves = 0
        self.won = False
        self.drag = None  # {"cards": [...], "source": (...), "offset": QPoint, "pos": QPoint}
        self.stuck = not self._has_any_move()
        self.update()

    def _snapshot(self):
        self.history.append(copy.deepcopy({
            "tableau": self.tableau, "stock": self.stock, "waste": self.waste,
            "foundations": self.foundations, "moves": self.moves,
        }))
        if len(self.history) > 200:
            self.history.pop(0)

    def _undo(self):
        if not self.history:
            return
        state = self.history.pop()
        self.tableau = state["tableau"]
        self.stock = state["stock"]
        self.waste = state["waste"]
        self.foundations = state["foundations"]
        self.moves = state["moves"]
        self.won = False
        self.drag = None
        self.stuck = not self._has_any_move()
        self.update()

    # ------------------------------------------------------------------
    # Persistence - same lazy-mkdir-on-write-only pattern as
    # core/activity_log.py and core/subscriptions.py: a read must never
    # create the directory, only a write does. The undo history isn't
    # persisted (reset to empty on load) - a minor, acceptable loss
    # compared to the actual board state.
    # ------------------------------------------------------------------
    def _save_path(self):
        return os.path.join(core_config.path("games"), "solitaire_save.json")

    def _load_save(self):
        path = self._save_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _restore_from_save(self, data):
        try:
            self.tableau = data["tableau"]
            self.stock = data["stock"]
            self.waste = data["waste"]
            self.foundations = data["foundations"]
            self.moves = data.get("moves", 0)
            self.won = data.get("won", False)
        except KeyError:
            self._new_game()
            return
        self.history = []
        self.drag = None
        self.stuck = (not self.won) and not self._has_any_move()
        self.update()

    def save_now(self):
        """Called periodically (self.autosave_timer) and by the main
        window before it closes - see webagent_gui.py's closeEvent."""
        data = {
            "tableau": self.tableau, "stock": self.stock, "waste": self.waste,
            "foundations": self.foundations, "moves": self.moves, "won": self.won,
        }
        path = self._save_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass

    def _is_won(self):
        return all(len(pile) == 13 for pile in self.foundations.values())

    def _has_any_move(self):
        """Whether any legal move exists anywhere on the board.

        Stock recycling (see _draw_from_stock) exactly reverses back to the
        original draw order, so with no other move made the stock/waste
        cycle is deterministic and every card in it will eventually surface
        as the waste's top card. That means checking every stock/waste card
        against every foundation/tableau slot - not just the current waste
        top - correctly answers "is there a move available anywhere in the
        cycle," without having to simulate the draws themselves.
        """
        for col in range(7):
            pile = self.tableau[col]
            if pile and pile[-1]["face_up"]:
                for suit in SUITS:
                    if self._can_place_on_foundation(pile[-1], suit):
                        return True

        for col in range(7):
            pile = self.tableau[col]
            for card in pile:
                if not card["face_up"]:
                    continue
                for dest in range(7):
                    if dest != col and self._can_place_on_tableau(card, dest):
                        return True

        for card in self.stock + self.waste:
            for suit in SUITS:
                if self._can_place_on_foundation(card, suit):
                    return True
            for dest in range(7):
                if self._can_place_on_tableau(card, dest):
                    return True

        return False

    def _maybe_flip_top(self, col):
        pile = self.tableau[col]
        if pile and not pile[-1]["face_up"]:
            pile[-1]["face_up"] = True

    # ------------------------------------------------------------------
    # Move rules
    # ------------------------------------------------------------------
    def _can_place_on_tableau(self, card, col):
        pile = self.tableau[col]
        if not pile:
            return card["value"] == 13
        top = pile[-1]
        return top["face_up"] and _is_red(card) != _is_red(top) and card["value"] == top["value"] - 1

    def _can_place_on_foundation(self, card, suit):
        pile = self.foundations[suit]
        if card["suit"] != suit:
            return False
        if not pile:
            return card["value"] == 1
        return card["value"] == pile[-1]["value"] + 1

    # ------------------------------------------------------------------
    # Layout / hit testing
    # ------------------------------------------------------------------
    def _new_game_button_rect(self):
        header_rect = QRect(MARGIN, MARGIN - 6, self.width() - MARGIN * 2, HEADER_H)
        chip_w, button_w, gap = 92, 108, 8
        x = header_rect.right() - chip_w - gap - button_w
        return QRect(x, header_rect.y() + 2, button_w, HEADER_H - 8)

    def _stock_rect(self):
        return QRect(MARGIN, TOP_Y, CARD_W, CARD_H)

    def _waste_rect(self):
        return QRect(MARGIN + CARD_W + COL_GAP, TOP_Y, CARD_W, CARD_H)

    def _foundation_rect(self, index):
        x = MARGIN + (3 + index) * (CARD_W + COL_GAP)
        return QRect(x, TOP_Y, CARD_W, CARD_H)

    def _tableau_col_x(self, col):
        return MARGIN + col * (CARD_W + COL_GAP)

    def _tableau_card_rect(self, col, index):
        pile = self.tableau[col]
        y = TABLEAU_Y
        for i in range(index):
            y += STACK_OFFSET_FACEUP if pile[i]["face_up"] else STACK_OFFSET_FACEDOWN
        return QRect(self._tableau_col_x(col), y, CARD_W, CARD_H)

    def _tableau_hit(self, pos):
        """(col, index) of the topmost card under pos, searching from the
        top of the deepest-drawn column down - or None."""
        for col in range(6, -1, -1):
            pile = self.tableau[col]
            for index in range(len(pile) - 1, -1, -1):
                rect = self._tableau_card_rect(col, index)
                if rect.contains(pos):
                    return col, index
        return None

    def _foundation_suit_at(self, pos):
        for i, suit in enumerate(SUITS):
            if self._foundation_rect(i).contains(pos):
                return suit
        return None

    def _empty_tableau_col_at(self, pos):
        for col in range(7):
            if not self.tableau[col]:
                rect = QRect(self._tableau_col_x(col), TABLEAU_Y, CARD_W, CARD_H)
                if rect.contains(pos):
                    return col
        return None

    def _tableau_col_at_x(self, x):
        """Best-guess destination column for a drop x-coordinate that isn't
        exactly over a card rect (e.g. dropping below a short pile) -
        whichever column's x-span the point falls in."""
        for col in range(7):
            left = self._tableau_col_x(col)
            if left <= x < left + CARD_W + COL_GAP:
                return col
        return None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _draw_from_stock(self):
        self._snapshot()
        if self.stock:
            card = self.stock.pop()
            card["face_up"] = True
            self.waste.append(card)
        elif self.waste:
            self.stock = list(reversed(self.waste))
            for card in self.stock:
                card["face_up"] = False
            self.waste = []
        else:
            self.history.pop()
            return
        self.moves += 1
        self.stuck = not self._has_any_move()

    def _try_auto_move_to_foundation(self, card, source_col=None):
        for suit in SUITS:
            if self._can_place_on_foundation(card, suit):
                self._snapshot()
                self._remove_top_card(source_col)
                self.foundations[suit].append(card)
                self.moves += 1
                self.won = self._is_won()
                self.stuck = (not self.won) and not self._has_any_move()
                return True
        return False

    def _remove_top_card(self, source_col):
        """Pops the card this method's caller already matched against
        waste/tableau top, given where it came from (None means waste)."""
        if source_col is None:
            self.waste.pop()
        else:
            self.tableau[source_col].pop()
            self._maybe_flip_top(source_col)

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if consume_start_input(self):
            return
        pos = event.position().toPoint()

        if event.button() == Qt.MouseButton.LeftButton and self._new_game_button_rect().contains(pos):
            self._new_game()
            self.update()
            return

        if self.won or self.stuck:
            return

        if self._stock_rect().contains(pos):
            self._draw_from_stock()
            self.update()
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self.waste and self._waste_rect().contains(pos):
            card = self.waste[-1]
            self._start_drag([card], source=("waste", None), origin_rect=self._waste_rect(), pos=pos)
            return

        hit = self._tableau_hit(pos)
        if hit:
            col, index = hit
            pile = self.tableau[col]
            if pile[index]["face_up"]:
                cards = pile[index:]
                self._start_drag(cards, source=("tableau", col), origin_rect=self._tableau_card_rect(col, index), pos=pos)

    def mouseDoubleClickEvent(self, event):
        if not self.started:
            return
        if self.won or self.stuck:
            return
        pos = event.position().toPoint()
        if self.waste and self._waste_rect().contains(pos):
            self._try_auto_move_to_foundation(self.waste[-1], source_col=None)
            self.update()
            return
        hit = self._tableau_hit(pos)
        if hit:
            col, index = hit
            pile = self.tableau[col]
            if index == len(pile) - 1 and pile[index]["face_up"]:
                self._try_auto_move_to_foundation(pile[index], source_col=col)
                self.update()

    def _start_drag(self, cards, source, origin_rect, pos):
        self.drag = {
            "cards": cards,
            "source": source,
            "offset": pos - origin_rect.topLeft(),
            "pos": pos,
        }
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        self.hover_pos = pos
        if self.drag is not None:
            self.drag["pos"] = pos
        if self._new_game_button_rect().contains(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def mouseReleaseEvent(self, event):
        if self.drag is None:
            return
        drag = self.drag
        self.drag = None
        pos = event.position().toPoint()
        cards = drag["cards"]
        lead = cards[0]
        kind, col = drag["source"]

        moved = False
        foundation_suit = self._foundation_suit_at(pos)
        if foundation_suit is not None and len(cards) == 1 and self._can_place_on_foundation(lead, foundation_suit):
            self._snapshot()
            self._remove_dragged(kind, col, len(cards))
            self.foundations[foundation_suit].append(lead)
            moved = True
        else:
            dest_col = self._empty_tableau_col_at(pos)
            if dest_col is None:
                hit = self._tableau_hit(pos)
                dest_col = hit[0] if hit else self._tableau_col_at_x(pos.x())
            if dest_col is not None and dest_col != col and self._can_place_on_tableau(lead, dest_col):
                self._snapshot()
                self._remove_dragged(kind, col, len(cards))
                self.tableau[dest_col].extend(cards)
                moved = True

        if moved:
            self.moves += 1
            self.won = self._is_won()
            self.stuck = (not self.won) and not self._has_any_move()
        self.update()

    def _remove_dragged(self, kind, col, count):
        if kind == "waste":
            del self.waste[-count:]
        else:
            del self.tableau[col][-count:]
            self._maybe_flip_top(col)

    def leaveEvent(self, event):
        self.hover_pos = None
        self.update()

    def keyPressEvent(self, event):
        if consume_start_input(self):
            return
        if event.key() == Qt.Key.Key_Z and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._undo()
        elif event.key() == Qt.Key.Key_N:
            self._new_game()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_background(painter)
        self._draw_header(painter)

        self._draw_empty_slot(painter, self._stock_rect())
        self._draw_empty_slot(painter, self._waste_rect())
        for i in range(4):
            self._draw_empty_slot(painter, self._foundation_rect(i))
        for col in range(7):
            self._draw_empty_slot(painter, QRect(self._tableau_col_x(col), TABLEAU_Y, CARD_W, CARD_H))

        if self.stock:
            self._draw_card_back(painter, self._stock_rect())
            badge_w = 22
            badge = QRect(self._stock_rect().center().x() - badge_w // 2, self._stock_rect().bottom() - 16, badge_w, 14)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(0, 0, 0, 130)))
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(QPen(TEXT_COLOR))
            painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(len(self.stock)))
        elif self.waste:
            painter.setPen(QPen(SLOT_OUTLINE, 1.5))
            painter.setFont(QFont("Arial", 18))
            painter.drawText(self._stock_rect(), Qt.AlignmentFlag.AlignCenter, "↻")
        if self.waste and not (self.drag and self.drag["source"][0] == "waste"):
            self._draw_card_face(painter, self.waste[-1], self._waste_rect())

        for i, suit in enumerate(SUITS):
            pile = self.foundations[suit]
            if pile:
                self._draw_card_face(painter, pile[-1], self._foundation_rect(i))
            else:
                self._draw_suit_hint(painter, suit, self._foundation_rect(i))

        dragged_ids = {id(c) for c in self.drag["cards"]} if self.drag else set()
        for col in range(7):
            pile = self.tableau[col]
            for index, card in enumerate(pile):
                if id(card) in dragged_ids:
                    continue
                rect = self._tableau_card_rect(col, index)
                if card["face_up"]:
                    self._draw_card_face(painter, card, rect)
                else:
                    self._draw_card_back(painter, rect)

        if self.drag:
            target = self._drag_target(self.drag["pos"])
            if target:
                self._draw_drop_highlight(painter, *target)
        elif not self.won and not self.stuck:
            hover = self._hover_target()
            if hover:
                self._draw_hover_glow(painter, hover[1])

        if self.drag:
            base = self.drag["pos"] - self.drag["offset"]
            for i, card in enumerate(self.drag["cards"]):
                rect = QRect(base.x(), base.y() + i * STACK_OFFSET_FACEUP, CARD_W, CARD_H)
                self._draw_card_face(painter, card, rect)

        if not self.started:
            draw_start_screen(painter, self.rect(), "Solitaire", [
                "Klondike - drag cards between piles, double-click to send a card to its foundation.",
                "Ctrl+Z to undo, N for a new game.",
                "Click or press any key to begin.",
            ])
        elif self.won:
            self._draw_win(painter)
        elif self.stuck:
            self._draw_stuck(painter)
        painter.end()

    def _draw_background(self, painter):
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0, BG_TOP)
        grad.setColorAt(1, BG_BOTTOM)
        painter.fillRect(self.rect(), QBrush(grad))
        painter.setPen(QPen(FELT_LINE, 1))
        painter.drawLine(MARGIN, TOP_Y - 14, self.width() - MARGIN, TOP_Y - 14)

    def _draw_header(self, painter):
        header_rect = QRect(MARGIN, MARGIN - 6, self.width() - MARGIN * 2, HEADER_H)
        painter.setPen(QPen(HEADER_TITLE))
        painter.setFont(QFont("Arial", 15, QFont.Weight.Bold))
        painter.drawText(header_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "♠ Solitaire ♥")

        chip_w = 92
        chip_rect = QRect(header_rect.right() - chip_w, header_rect.y() + 2, chip_w, HEADER_H - 8)
        painter.setPen(QPen(CHIP_BORDER, 1))
        painter.setBrush(QBrush(CHIP_BG))
        painter.drawRoundedRect(chip_rect, 10, 10)
        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 11))
        painter.drawText(chip_rect, Qt.AlignmentFlag.AlignCenter, f"Moves: {self.moves}")

        button_rect = self._new_game_button_rect()
        is_hover = self.hover_pos is not None and button_rect.contains(self.hover_pos)
        painter.setPen(QPen(BUTTON_BORDER, 1.2))
        painter.setBrush(QBrush(BUTTON_BG_HOVER if is_hover else BUTTON_BG))
        painter.drawRoundedRect(button_rect, 10, 10)
        painter.setPen(QPen(HEADER_TITLE))
        painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        painter.drawText(button_rect, Qt.AlignmentFlag.AlignCenter, "New Game")

        hint_rect = QRect(header_rect.x() + 150, header_rect.y() + 2, button_rect.x() - 8 - (header_rect.x() + 150), HEADER_H - 8)
        painter.setPen(QPen(MUTED_COLOR))
        painter.setFont(QFont("Arial", 11))
        painter.drawText(hint_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "Ctrl+Z to undo")

    def _draw_empty_slot(self, painter, rect):
        painter.setPen(QPen(SLOT_OUTLINE, 1.5, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)

    def _draw_suit_hint(self, painter, suit, rect):
        color = RED_TEXT if suit in RED_SUITS else MUTED_COLOR
        muted = QColor(color)
        muted.setAlpha(90)
        painter.setPen(QPen(muted))
        painter.setFont(QFont("Arial", 22))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, suit)

    def _draw_card_shadow(self, painter, rect):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(SHADOW_COLOR))
        painter.drawRoundedRect(rect.translated(2, 3), 6, 6)

    def _draw_card_back(self, painter, rect):
        self._draw_card_shadow(painter, rect)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 6, 6)
        painter.save()
        painter.setClipPath(path)
        grad = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        grad.setColorAt(0, CARD_BACK_TOP)
        grad.setColorAt(1, CARD_BACK_BOTTOM)
        painter.fillRect(rect, QBrush(grad))
        painter.setPen(QPen(CARD_BACK_PATTERN, 1))
        step = 9
        x = rect.left() - rect.height()
        while x < rect.right():
            painter.drawLine(x, rect.bottom(), x + rect.height(), rect.top())
            x += step
        painter.restore()

        painter.setPen(QPen(CARD_BACK_BORDER, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 6, 6)
        inner = rect.adjusted(7, 7, -7, -7)
        painter.setPen(QPen(QColor(255, 255, 255, 55), 1))
        painter.drawRoundedRect(inner, 4, 4)

    def _draw_card_face(self, painter, card, rect):
        self._draw_card_shadow(painter, rect)
        grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        grad.setColorAt(0, CARD_FACE_TOP)
        grad.setColorAt(1, CARD_FACE_BOTTOM)
        painter.setPen(QPen(CARD_BORDER, 1.5))
        painter.setBrush(QBrush(grad))
        painter.drawRoundedRect(rect, 6, 6)

        color = RED_TEXT if _is_red(card) else BLACK_TEXT
        rank_font = QFont("Georgia", 12, QFont.Weight.Bold)
        suit_font = QFont("Arial", 10)

        painter.setPen(QPen(color))
        painter.setFont(rank_font)
        painter.drawText(rect.adjusted(6, 3, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, card["rank"])
        painter.setFont(suit_font)
        painter.drawText(rect.adjusted(6, 18, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, card["suit"])

        painter.save()
        painter.translate(rect.right(), rect.bottom())
        painter.rotate(180)
        mirrored = QRect(0, 0, rect.width(), rect.height())
        painter.setPen(QPen(color))
        painter.setFont(rank_font)
        painter.drawText(mirrored.adjusted(6, 3, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, card["rank"])
        painter.setFont(suit_font)
        painter.drawText(mirrored.adjusted(6, 18, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, card["suit"])
        painter.restore()

        watermark = QColor(color)
        watermark.setAlpha(26)
        painter.setPen(QPen(watermark))
        painter.setFont(QFont("Arial", 42))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, card["suit"])
        painter.setPen(QPen(color))
        painter.setFont(QFont("Arial", 22))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, card["suit"])

    def _tableau_col_rect(self, col):
        pile = self.tableau[col]
        bottom = self._tableau_card_rect(col, len(pile) - 1).bottom() if pile else TABLEAU_Y + CARD_H
        return QRect(self._tableau_col_x(col), TABLEAU_Y, CARD_W, bottom - TABLEAU_Y)

    def _hover_target(self):
        pos = self.hover_pos
        if pos is None:
            return None
        if self.waste and self._waste_rect().contains(pos):
            return "waste", self._waste_rect()
        hit = self._tableau_hit(pos)
        if hit:
            col, index = hit
            pile = self.tableau[col]
            if pile[index]["face_up"]:
                top_rect = self._tableau_card_rect(col, index)
                rect = QRect(top_rect.x(), top_rect.y(), CARD_W, self._tableau_col_rect(col).bottom() - top_rect.y())
                return "tableau", rect
        return None

    def _draw_hover_glow(self, painter, rect):
        painter.setPen(QPen(HOVER_GLOW, 2.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 9, 9)

    def _drag_target(self, pos):
        """During an active drag, the (rect, is_valid) drop zone under pos -
        or None if pos isn't over a plausible tableau/foundation target."""
        cards = self.drag["cards"]
        lead = cards[0]
        _kind, col = self.drag["source"]

        foundation_suit = self._foundation_suit_at(pos)
        if foundation_suit is not None:
            valid = len(cards) == 1 and self._can_place_on_foundation(lead, foundation_suit)
            return self._foundation_rect(SUITS.index(foundation_suit)), valid

        dest_col = self._empty_tableau_col_at(pos)
        if dest_col is None:
            hit = self._tableau_hit(pos)
            dest_col = hit[0] if hit else self._tableau_col_at_x(pos.x())
        if dest_col is not None and dest_col != col:
            return self._tableau_col_rect(dest_col), self._can_place_on_tableau(lead, dest_col)
        return None

    def _draw_drop_highlight(self, painter, rect, valid):
        painter.setPen(QPen(DROP_OK if valid else DROP_BAD, 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 10, 10)

    def _draw_win(self, painter):
        painter.fillRect(self.rect(), QColor(0, 0, 0, 170))
        panel_w, panel_h = 360, 220
        panel = QRect((self.width() - panel_w) // 2, (self.height() - panel_h) // 2, panel_w, panel_h)

        grad = QLinearGradient(panel.left(), panel.top(), panel.right(), panel.bottom())
        grad.setColorAt(0, QColor("#2a2140"))
        grad.setColorAt(1, QColor("#1a1628"))
        painter.setPen(QPen(HIGHLIGHT, 2))
        painter.setBrush(QBrush(grad))
        painter.drawRoundedRect(panel, 16, 16)

        painter.setPen(QPen(HIGHLIGHT))
        painter.setFont(QFont("Arial", 15))
        painter.drawText(QRect(panel.x(), panel.y() + 18, panel.width(), 30), Qt.AlignmentFlag.AlignCenter, "♠ ♥ ♦ ♣")

        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 26, QFont.Weight.Bold))
        painter.drawText(QRect(panel.x(), panel.y() + 52, panel.width(), 40), Qt.AlignmentFlag.AlignCenter, "You Win!")

        painter.setPen(QPen(MUTED_COLOR))
        painter.setFont(QFont("Arial", 13))
        painter.drawText(QRect(panel.x(), panel.y() + 104, panel.width(), 24), Qt.AlignmentFlag.AlignCenter, f"Completed in {self.moves} moves")
        painter.drawText(QRect(panel.x(), panel.y() + 144, panel.width(), 24), Qt.AlignmentFlag.AlignCenter, "Click New Game to play again")

    def _draw_stuck(self, painter):
        painter.fillRect(self.rect(), QColor(0, 0, 0, 170))
        panel_w, panel_h = 360, 200
        panel = QRect((self.width() - panel_w) // 2, (self.height() - panel_h) // 2, panel_w, panel_h)

        grad = QLinearGradient(panel.left(), panel.top(), panel.right(), panel.bottom())
        grad.setColorAt(0, QColor("#3a1f24"))
        grad.setColorAt(1, QColor("#221418"))
        painter.setPen(QPen(DROP_BAD, 2))
        painter.setBrush(QBrush(grad))
        painter.drawRoundedRect(panel, 16, 16)

        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        painter.drawText(QRect(panel.x(), panel.y() + 30, panel.width(), 40), Qt.AlignmentFlag.AlignCenter, "No Moves Left")

        painter.setPen(QPen(MUTED_COLOR))
        painter.setFont(QFont("Arial", 13))
        painter.drawText(QRect(panel.x(), panel.y() + 84, panel.width(), 24), Qt.AlignmentFlag.AlignCenter, f"Stuck after {self.moves} moves")
        painter.drawText(QRect(panel.x(), panel.y() + 118, panel.width(), 24), Qt.AlignmentFlag.AlignCenter, "Ctrl+Z to undo or New Game to restart")
