"""A mini murder-mystery logic-grid puzzle - the classic "zebra puzzle"
format (suspect x weapon x room, deduced from a set of true/false clues)
themed as a whodunit. Not a clone of any specific branded puzzle app; the
underlying logic-grid-deduction format itself is a long-established public
puzzle genre, not anyone's proprietary format.

Pure PyQt6, standard widgets (QGridLayout of QPushButton cells + QLabel
text) rather than QPainter - unlike games/zuma_endless.py and
games/solitaire.py, this is a text/logic puzzle with no continuous motion
or free-form dragging, so plain form widgets are the right tool, not a
hand-rolled canvas.
"""
import itertools
import json
import os
import random

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core import config as core_config

SUSPECT_POOL = [
    "Dr. Ivy Sable", "Colonel Rusk", "Madame Vex", "Chef Antoine",
    "Lady Priscilla Thorne", "Mr. Baxter Crane", "Sister Agnes", "Professor Lindqvist",
]
WEAPON_POOL = [
    "candlestick", "revolver", "dagger", "poison vial",
    "wrench", "rope", "letter opener", "fire poker",
]
ROOM_POOL = [
    "library", "conservatory", "billiard room", "kitchen",
    "study", "wine cellar", "greenhouse", "ballroom",
]
VICTIM_POOL = ["Lord Ashford", "the Countess", "Mr. Whitfield", "the ship's captain", "the old professor"]

CELL_SIZE = 34

# Same dark-purple palette as games/sudoku.py, games/solitaire.py and
# games/zuma_endless.py, expressed as plain hex strings here since this
# widget is styled entirely via setStyleSheet() rather than QPainter.
TEXT_COLOR = "#eaeaf2"
MUTED_COLOR = "#9494a6"
BORDER_COLOR = "#33333f"
PANEL_BG = "#1a1a24"
MARK_TRUE_BG = "#2f2a52"
MARK_TRUE_TEXT = "#9d85ff"
MARK_TRUE_BORDER = "#4a3f8f"
MARK_FALSE_BG = "#1a1a24"
MARK_FALSE_TEXT = "#5a5a6a"
MARK_FALSE_BORDER = "#2a2a36"
MARK_NONE_BG = "#1e1e28"
MARK_NONE_TEXT = "#cfcfe0"
SUCCESS_COLOR = "#3ecf8e"


# ----------------------------------------------------------------------
# Puzzle generation - pure logic, no Qt. A random full solution (two
# suspect<->weapon/room permutations plus a murderer) is picked first, then
# a pool of every true clue derivable from it is built, then clues are
# dropped one at a time (in random order) as long as the remaining set
# still pins down exactly one candidate solution out of all
# 4! * 4! * 4 = 2304 possibilities - same generate-then-prune-while-unique
# technique as games/sudoku.py's puzzle carving, applied to a discrete
# constraint-satisfaction puzzle instead of a grid of digits.
# ----------------------------------------------------------------------
def _occupant_of(candidate, room, suspects):
    for s in suspects:
        if candidate["room_of"][s] == room:
            return s
    return None


def _build_clue_pool(suspects, weapons, rooms, solution):
    weapon_of, room_of, murderer = solution["weapon_of"], solution["room_of"], solution["murderer"]
    pool = []

    for s in suspects:
        true_w = weapon_of[s]
        pool.append((f"{s} used the {true_w}.", lambda c, s=s, w=true_w: c["weapon_of"][s] == w))
        for w in weapons:
            if w != true_w:
                pool.append((f"{s} did not use the {w}.", lambda c, s=s, w=w: c["weapon_of"][s] != w))

    for s in suspects:
        true_r = room_of[s]
        pool.append((f"{s} was in the {true_r}.", lambda c, s=s, r=true_r: c["room_of"][s] == r))
        for r in rooms:
            if r != true_r:
                pool.append((f"{s} was not in the {r}.", lambda c, s=s, r=r: c["room_of"][s] != r))

    for r in rooms:
        occupant = next(s for s in suspects if room_of[s] == r)
        w = weapon_of[occupant]
        pool.append((
            f"Whoever was in the {r} used the {w}.",
            lambda c, r=r, w=w, suspects=suspects: c["weapon_of"][_occupant_of(c, r, suspects)] == w,
        ))
        wrong_w = random.choice([x for x in weapons if x != w])
        pool.append((
            f"Whoever was in the {r} did not use the {wrong_w}.",
            lambda c, r=r, w=wrong_w, suspects=suspects: c["weapon_of"][_occupant_of(c, r, suspects)] != w,
        ))

    for s in suspects:
        if s != murderer:
            pool.append((f"{s} has an alibi for the time of the murder.", lambda c, s=s: c["murderer"] != s))

    pool.append((
        f"The murderer used the {weapon_of[murderer]}.",
        lambda c: c["weapon_of"][c["murderer"]] == weapon_of[murderer],
    ))
    pool.append((
        f"The murder took place in the {room_of[murderer]}.",
        lambda c: c["room_of"][c["murderer"]] == room_of[murderer],
    ))
    return pool


def _all_candidates(suspects, weapons, rooms):
    candidates = []
    for wperm in itertools.permutations(weapons):
        weapon_of = dict(zip(suspects, wperm))
        for rperm in itertools.permutations(rooms):
            room_of = dict(zip(suspects, rperm))
            for murderer in suspects:
                candidates.append({"weapon_of": weapon_of, "room_of": room_of, "murderer": murderer})
    return candidates


def generate_case():
    suspects = random.sample(SUSPECT_POOL, 4)
    weapons = random.sample(WEAPON_POOL, 4)
    rooms = random.sample(ROOM_POOL, 4)
    victim = random.choice(VICTIM_POOL)

    weapon_perm = weapons[:]
    random.shuffle(weapon_perm)
    room_perm = rooms[:]
    random.shuffle(room_perm)
    weapon_of = dict(zip(suspects, weapon_perm))
    room_of = dict(zip(suspects, room_perm))
    murderer = random.choice(suspects)
    solution = {"weapon_of": weapon_of, "room_of": room_of, "murderer": murderer}

    all_candidates = _all_candidates(suspects, weapons, rooms)
    pool = _build_clue_pool(suspects, weapons, rooms, solution)

    def _filtered(indices):
        remaining = all_candidates
        for i in indices:
            predicate = pool[i][1]
            remaining = [c for c in remaining if predicate(c)]
            if len(remaining) == 1:
                return remaining
        return remaining

    kept = list(range(len(pool)))
    order = kept[:]
    random.shuffle(order)
    for i in order:
        trial = [j for j in kept if j != i]
        if len(_filtered(trial)) == 1:
            kept = trial

    clue_texts = [pool[i][0] for i in kept]
    random.shuffle(clue_texts)
    return {
        "victim": victim, "suspects": suspects, "weapons": weapons, "rooms": rooms,
        "solution": solution, "clues": clue_texts,
    }


# ----------------------------------------------------------------------
# Widget
# ----------------------------------------------------------------------
class MysteryWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._outer_layout = QVBoxLayout(self)
        self._outer_layout.setSpacing(10)

        self.game_content = QWidget()
        self._content_layout = QVBoxLayout(self.game_content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(10)

        self.intro_label = QLabel()
        self.intro_label.setWordWrap(True)
        self.intro_label.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {TEXT_COLOR};")
        self._content_layout.addWidget(self.intro_label)

        self.clues_label = QLabel()
        self.clues_label.setWordWrap(True)
        self.clues_label.setStyleSheet(
            f"color: {MARK_NONE_TEXT}; background-color: {PANEL_BG}; border: 1px solid {BORDER_COLOR}; "
            f"border-radius: 6px; padding: 8px;"
        )
        self._content_layout.addWidget(self.clues_label)

        self.grid_container = QWidget()
        self.grid_container.setStyleSheet(
            f"background-color: {PANEL_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 6px;"
        )
        self._content_layout.addWidget(self.grid_container)

        self._guilty_row_layout = QHBoxLayout()
        self._guilty_row_layout.addWidget(QLabel("Who is guilty?"))
        self.guilty_container = QWidget()
        self._guilty_row_layout.addWidget(self.guilty_container)
        self._guilty_row_layout.addStretch()
        self._content_layout.addLayout(self._guilty_row_layout)

        button_row = QHBoxLayout()
        check_button = QPushButton("Check Solution")
        check_button.clicked.connect(self._check_solution)
        button_row.addWidget(check_button)
        new_case_button = QPushButton("New Case")
        new_case_button.clicked.connect(self._new_case)
        button_row.addWidget(new_case_button)
        button_row.addStretch()
        self._content_layout.addLayout(button_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self._content_layout.addWidget(self.status_label)

        self._outer_layout.addWidget(self.game_content)

        saved = self._load_save()
        if saved:
            self._restore_from_save(saved)
        else:
            self._new_case()

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.save_now)
        self.autosave_timer.start(15_000)

        # Start-screen gate - the case is already generated above (so a
        # save is loaded/persisted exactly as before) but stays hidden
        # behind a "Begin Case" prompt until the player dismisses it,
        # instead of the puzzle just being live the moment this tab opens.
        self.started = False
        self.game_content.setVisible(False)
        self.start_overlay = self._build_start_overlay()
        self._outer_layout.addWidget(self.start_overlay)

    def _build_start_overlay(self):
        overlay = QWidget()
        layout = QVBoxLayout(overlay)
        layout.setContentsMargins(24, 48, 24, 48)
        layout.setSpacing(10)

        title = QLabel("🔎 Mystery")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"font-weight: bold; font-size: 22px; color: {TEXT_COLOR};")
        layout.addWidget(title)

        subtitle = QLabel("A logic-grid whodunit - deduce the suspect, weapon, and room from the clues.")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {MUTED_COLOR};")
        layout.addWidget(subtitle)

        begin_button = QPushButton("Begin Case")
        begin_button.clicked.connect(self._begin)
        layout.addWidget(begin_button, 0, Qt.AlignmentFlag.AlignCenter)
        return overlay

    def _begin(self):
        self.started = True
        self.start_overlay.setVisible(False)
        self.game_content.setVisible(True)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def _new_case(self):
        self.case = generate_case()
        self.won = False
        self.status_label.setText("")
        self._refresh_status_style()
        suspects, weapons, rooms = self.case["suspects"], self.case["weapons"], self.case["rooms"]
        self.weapon_marks = {(s, w): None for s in suspects for w in weapons}
        self.room_marks = {(s, r): None for s in suspects for r in rooms}
        self.guilty_marks = {s: None for s in suspects}
        self.weapon_buttons = {}
        self.room_buttons = {}
        self.guilty_buttons = {}

        self.intro_label.setText(
            f"{self.case['victim']} was murdered. One of the four suspects below did it, with one of the "
            f"weapons, in one of the rooms. Use the clues to work out who, with what, and where."
        )
        self.clues_label.setText("\n".join(f"• {c}" for c in self.case["clues"]))
        self._rebuild_grid()
        self._rebuild_guilty_row()
        self.save_now()

    # ------------------------------------------------------------------
    # Persistence - same lazy-mkdir-on-write-only pattern as
    # core/activity_log.py and core/subscriptions.py: a read must never
    # create the directory, only a write does. weapon_marks/room_marks are
    # keyed by (suspect, name) tuples in memory, which JSON can't use as
    # object keys, so they're stored as [suspect, name, mark] triples.
    # ------------------------------------------------------------------
    def _save_path(self):
        return os.path.join(core_config.path("games"), "mystery_save.json")

    def _load_save(self):
        path = self._save_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _restore_from_save(self, data):
        try:
            self.case = data["case"]
            self.won = data.get("won", False)
            self.weapon_marks = {(s, w): mark for s, w, mark in data["weapon_marks"]}
            self.room_marks = {(s, r): mark for s, r, mark in data["room_marks"]}
            self.guilty_marks = {s: mark for s, mark in data["guilty_marks"]}
        except (KeyError, ValueError):
            self._new_case()
            return
        self.weapon_buttons = {}
        self.room_buttons = {}
        self.guilty_buttons = {}
        self.status_label.setText(data.get("status_text", ""))
        self._refresh_status_style()
        self.intro_label.setText(
            f"{self.case['victim']} was murdered. One of the four suspects below did it, with one of the "
            f"weapons, in one of the rooms. Use the clues to work out who, with what, and where."
        )
        self.clues_label.setText("\n".join(f"• {c}" for c in self.case["clues"]))
        self._rebuild_grid()
        self._rebuild_guilty_row()

    def save_now(self):
        """Called periodically (self.autosave_timer) and by the main
        window before it closes - see webagent_gui.py's closeEvent."""
        if not hasattr(self, "case"):
            return
        data = {
            "case": self.case, "won": self.won, "status_text": self.status_label.text(),
            "weapon_marks": [[s, w, mark] for (s, w), mark in self.weapon_marks.items()],
            "room_marks": [[s, r, mark] for (s, r), mark in self.room_marks.items()],
            "guilty_marks": [[s, mark] for s, mark in self.guilty_marks.items()],
        }
        path = self._save_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass

    def _rebuild_grid(self):
        old = self.grid_container
        self.grid_container = QWidget()
        self.grid_container.setStyleSheet(
            f"background-color: {PANEL_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 6px;"
        )
        self._content_layout.replaceWidget(old, self.grid_container)
        old.deleteLater()

        grid = QGridLayout(self.grid_container)
        grid.setSpacing(4)
        grid.setContentsMargins(8, 8, 8, 8)
        suspects, weapons, rooms = self.case["suspects"], self.case["weapons"], self.case["rooms"]

        grid.addWidget(self._header_label("Weapon"), 0, 1, 1, len(weapons), Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self._header_label("Room"), 0, 1 + len(weapons), 1, len(rooms), Qt.AlignmentFlag.AlignCenter)

        for j, w in enumerate(weapons):
            grid.addWidget(self._cell_name_label(w), 1, 1 + j)
        for j, r in enumerate(rooms):
            grid.addWidget(self._cell_name_label(r), 1, 1 + len(weapons) + j)

        for i, s in enumerate(suspects):
            grid.addWidget(QLabel(s), 2 + i, 0)
            for j, w in enumerate(weapons):
                btn = self._make_cell_button(lambda checked=False, s=s, w=w: self._toggle_weapon(s, w))
                self.weapon_buttons[(s, w)] = btn
                grid.addWidget(btn, 2 + i, 1 + j)
            for j, r in enumerate(rooms):
                btn = self._make_cell_button(lambda checked=False, s=s, r=r: self._toggle_room(s, r))
                self.room_buttons[(s, r)] = btn
                grid.addWidget(btn, 2 + i, 1 + len(weapons) + j)

        self._refresh_grid_buttons()

    def _rebuild_guilty_row(self):
        old = self.guilty_container
        self.guilty_container = QWidget()
        self._guilty_row_layout.replaceWidget(old, self.guilty_container)
        old.deleteLater()

        row = QHBoxLayout(self.guilty_container)
        row.setSpacing(4)
        for s in self.case["suspects"]:
            btn = QPushButton(s)
            btn.clicked.connect(lambda checked=False, s=s: self._toggle_guilty(s))
            self.guilty_buttons[s] = btn
            row.addWidget(btn)
        self._refresh_guilty_buttons()

    def _header_label(self, text):
        label = QLabel(text)
        label.setStyleSheet(f"font-weight: bold; color: {MUTED_COLOR};")
        return label

    def _cell_name_label(self, text):
        label = QLabel(text)
        label.setFixedWidth(CELL_SIZE + 10)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"font-size: 9px; color: {MARK_NONE_TEXT};")
        return label

    def _make_cell_button(self, handler):
        btn = QPushButton("")
        btn.setFixedSize(CELL_SIZE, CELL_SIZE)
        btn.clicked.connect(handler)
        return btn

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------
    def _cycle(self, current):
        return {None: True, True: False, False: None}[current]

    def _toggle_weapon(self, suspect, weapon):
        if self.won:
            return
        nxt = self._cycle(self.weapon_marks[(suspect, weapon)])
        self.weapon_marks[(suspect, weapon)] = nxt
        if nxt is True:
            for w2 in self.case["weapons"]:
                if w2 != weapon:
                    self.weapon_marks[(suspect, w2)] = False
            for s2 in self.case["suspects"]:
                if s2 != suspect:
                    self.weapon_marks[(s2, weapon)] = False
        self._refresh_grid_buttons()

    def _toggle_room(self, suspect, room):
        if self.won:
            return
        nxt = self._cycle(self.room_marks[(suspect, room)])
        self.room_marks[(suspect, room)] = nxt
        if nxt is True:
            for r2 in self.case["rooms"]:
                if r2 != room:
                    self.room_marks[(suspect, r2)] = False
            for s2 in self.case["suspects"]:
                if s2 != suspect:
                    self.room_marks[(s2, room)] = False
        self._refresh_grid_buttons()

    def _toggle_guilty(self, suspect):
        if self.won:
            return
        nxt = self._cycle(self.guilty_marks[suspect])
        self.guilty_marks[suspect] = nxt
        if nxt is True:
            for s2 in self.case["suspects"]:
                if s2 != suspect:
                    self.guilty_marks[s2] = False
        self._refresh_guilty_buttons()

    def _refresh_grid_buttons(self):
        for key, btn in self.weapon_buttons.items():
            self._style_cell(btn, self.weapon_marks[key])
        for key, btn in self.room_buttons.items():
            self._style_cell(btn, self.room_marks[key])

    def _refresh_guilty_buttons(self):
        for s, btn in self.guilty_buttons.items():
            btn.setStyleSheet(self._mark_stylesheet(self.guilty_marks[s]))

    def _mark_stylesheet(self, mark):
        if mark is True:
            return (
                f"background-color:{MARK_TRUE_BG}; color:{MARK_TRUE_TEXT}; font-weight:bold; "
                f"border:1px solid {MARK_TRUE_BORDER}; border-radius:4px;"
            )
        if mark is False:
            return (
                f"background-color:{MARK_FALSE_BG}; color:{MARK_FALSE_TEXT}; "
                f"border:1px solid {MARK_FALSE_BORDER}; border-radius:4px;"
            )
        return f"background-color:{MARK_NONE_BG}; color:{MARK_NONE_TEXT}; border:1px solid {BORDER_COLOR}; border-radius:4px;"

    def _style_cell(self, btn, mark):
        btn.setText({True: "✓", False: "✗", None: ""}[mark])
        btn.setStyleSheet(self._mark_stylesheet(mark))

    # ------------------------------------------------------------------
    # Solution checking
    # ------------------------------------------------------------------
    def _marked_weapon(self, suspect):
        return next((w for w in self.case["weapons"] if self.weapon_marks[(suspect, w)] is True), None)

    def _marked_room(self, suspect):
        return next((r for r in self.case["rooms"] if self.room_marks[(suspect, r)] is True), None)

    def _marked_guilty(self):
        return next((s for s in self.case["suspects"] if self.guilty_marks[s] is True), None)

    def _check_solution(self):
        solution = self.case["solution"]
        suspects = self.case["suspects"]
        weapon_correct = sum(1 for s in suspects if self._marked_weapon(s) == solution["weapon_of"][s])
        room_correct = sum(1 for s in suspects if self._marked_room(s) == solution["room_of"][s])
        guilty_correct = 1 if self._marked_guilty() == solution["murderer"] else 0
        total = weapon_correct + room_correct + guilty_correct

        if total == len(suspects) * 2 + 1:
            self.won = True
            murderer = solution["murderer"]
            self.status_label.setText(
                f"Case solved! {murderer} murdered {self.case['victim']} with the "
                f"{solution['weapon_of'][murderer]} in the {solution['room_of'][murderer]}."
            )
        else:
            self.status_label.setText(f"Not quite - {total}/{len(suspects) * 2 + 1} correct. Keep deducing.")
        self._refresh_status_style()

    def _refresh_status_style(self):
        if self.won:
            self.status_label.setStyleSheet(f"color: {SUCCESS_COLOR}; font-weight: bold;")
        else:
            self.status_label.setStyleSheet(f"color: {MUTED_COLOR};")
