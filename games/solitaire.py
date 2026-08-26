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

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core import config as core_config

CARD_W, CARD_H = 72, 100
MARGIN = 24
COL_GAP = 14
TOP_Y = MARGIN
TABLEAU_Y = TOP_Y + CARD_H + 40
STACK_OFFSET_FACEDOWN = 7
STACK_OFFSET_FACEUP = 24

CANVAS_WIDTH = MARGIN * 2 + 7 * CARD_W + 6 * COL_GAP
CANVAS_HEIGHT = 680

SUITS = ("♠", "♥", "♦", "♣")
RED_SUITS = {"♥", "♦"}
RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")

BG_CANVAS = QColor("#12121a")
SLOT_OUTLINE = QColor("#33333f")
CARD_BACK = QColor("#7c5cff")
CARD_BACK_BORDER = QColor("#3a2f80")
CARD_FACE = QColor("#f2f0ea")
CARD_BORDER = QColor("#0c0c12")
RED_TEXT = QColor("#c8323a")
BLACK_TEXT = QColor("#1c1c26")
TEXT_COLOR = QColor("#eaeaf2")
MUTED_COLOR = QColor("#9494a6")
HIGHLIGHT = QColor("#f5c344")


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

    def _try_auto_move_to_foundation(self, card, source_col=None):
        for suit in SUITS:
            if self._can_place_on_foundation(card, suit):
                self._snapshot()
                self._remove_top_card(source_col)
                self.foundations[suit].append(card)
                self.moves += 1
                self.won = self._is_won()
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
        if self.won:
            return
        pos = event.position().toPoint()

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
        if self.won:
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
        if self.drag is not None:
            self.drag["pos"] = event.position().toPoint()
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
        self.update()

    def _remove_dragged(self, kind, col, count):
        if kind == "waste":
            del self.waste[-count:]
        else:
            del self.tableau[col][-count:]
            self._maybe_flip_top(col)

    def keyPressEvent(self, event):
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
        painter.fillRect(self.rect(), BG_CANVAS)

        self._draw_empty_slot(painter, self._stock_rect())
        self._draw_empty_slot(painter, self._waste_rect())
        for i in range(4):
            self._draw_empty_slot(painter, self._foundation_rect(i))
        for col in range(7):
            self._draw_empty_slot(painter, QRect(self._tableau_col_x(col), TABLEAU_Y, CARD_W, CARD_H))

        if self.stock:
            self._draw_card_back(painter, self._stock_rect())
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
            base = self.drag["pos"] - self.drag["offset"]
            for i, card in enumerate(self.drag["cards"]):
                rect = QRect(base.x(), base.y() + i * STACK_OFFSET_FACEUP, CARD_W, CARD_H)
                self._draw_card_face(painter, card, rect)

        self._draw_hud(painter)
        if self.won:
            self._draw_win(painter)
        painter.end()

    def _draw_empty_slot(self, painter, rect):
        painter.setPen(QPen(SLOT_OUTLINE, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 8, 8)

    def _draw_suit_hint(self, painter, suit, rect):
        painter.setPen(QPen(SLOT_OUTLINE, 1))
        painter.setFont(QFont("Arial", 22))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, suit)

    def _draw_card_back(self, painter, rect):
        painter.setPen(QPen(CARD_BACK_BORDER, 1.5))
        painter.setBrush(QBrush(CARD_BACK))
        painter.drawRoundedRect(rect, 6, 6)
        inner = rect.adjusted(8, 8, -8, -8)
        painter.setPen(QPen(CARD_BACK_BORDER, 1))
        painter.drawRoundedRect(inner, 4, 4)

    def _draw_card_face(self, painter, card, rect):
        painter.setPen(QPen(CARD_BORDER, 1.5))
        painter.setBrush(QBrush(CARD_FACE))
        painter.drawRoundedRect(rect, 6, 6)
        color = RED_TEXT if _is_red(card) else BLACK_TEXT
        painter.setPen(QPen(color))
        painter.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        painter.drawText(rect.adjusted(6, 4, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, card["rank"])
        painter.setFont(QFont("Arial", 26))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, card["suit"])

    def _draw_hud(self, painter):
        painter.setPen(QPen(MUTED_COLOR))
        painter.setFont(QFont("Arial", 11))
        painter.drawText(self.width() - 180, 24, f"Moves: {self.moves}")
        painter.drawText(self.width() - 180, 42, "Ctrl+Z undo, N new game")

    def _draw_win(self, painter):
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        painter.setPen(QPen(TEXT_COLOR))
        painter.setFont(QFont("Arial", 28, QFont.Weight.Bold))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"You Win!\nMoves: {self.moves}\nPress N for a new game")
