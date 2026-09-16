"""Ethereal DND - GUI panel for the Ethereal DND engine (ethereal_dnd/).

Qt layer only: every button here calls straight into
ethereal_dnd.cli.debug_cli's plain-Python functions (no Qt imports
there) - the same split worklog.py and hacker.py already use between
their storage/logic layer and their Widget's Qt layer.

One in-memory Campaign, no save/load button yet (GC-062 exists in the
engine - ethereal_dnd/campaign/save_manager.py - but isn't wired into
this panel yet), so closing the app discards the current campaign/
companions. Phase 0 proved the scaffolding boots; Phase 1 added real
ability/class/combat math (Scripted Duel); Phase 1.5 added the alignment/
deity compliance engine (Paladin Alignment Demo); Phase 2 added the
actual Ravenhollow world (Explore Ravenhollow); Phase 3 added the real
narrative pipeline (docs/gnosis_crawler_backlog.md).

The primary way to act is the action button grid, rebuilt after every
action from narrative/action_menu.py's available_actions() - each
button's ActionIntent is already fully determined by what's really here
(NPCs present, real routes), so clicking one skips the intent-parsing
model call entirely (narrative/game_loop.py's process_menu_action()):
only the narrator still calls a model, to describe an already-decided
result. The freeform text box underneath still exists for anything not
covered by a button (Section 31: a fixed menu must never be the *only*
way to act), going through the full intent-parser pipeline instead
(process_player_input()).

Both paths run on a background QThread (_NarrativeWorker, same one-
zero-arg-callable shape as webagent_gui.py's CycleWorker) since a real
model call can take a while - freezing the GUI thread for it would be a
much worse experience than the wait itself.
"""
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from ethereal_dnd.cli import debug_cli
from ethereal_dnd.core.dice import DiceExpressionError
from ethereal_dnd.world.travel import travel

_ACTION_GRID_COLUMNS = 3


class _NarrativeWorker(QThread):
    """Runs one zero-arg callable (a debug_cli.play()/dialogue() call) off
    the GUI thread - see webagent_gui.py's CycleWorker for the identical
    pattern; duplicated locally rather than imported from there to avoid
    a circular import (webagent_gui.py is what imports *this* module)."""
    result_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.result_ready.emit(self.fn())
        except Exception as exc:
            self.error_occurred.emit(str(exc))


_DUEL_FIGHTER_SCORES = {"STR": 16, "DEX": 14, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8}
_DUEL_ROGUE_SCORES = {"STR": 11, "DEX": 15, "CON": 12, "INT": 10, "WIS": 9, "CHA": 8}
_PALADIN_SCORES = {"STR": 16, "DEX": 12, "CON": 14, "INT": 10, "WIS": 12, "CHA": 16}
_ADVENTURER_SCORES = {"STR": 15, "DEX": 13, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8}


class EtherealDndWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.campaign = debug_cli.new_ravenhollow_campaign()
        self.paladin_companion = None  # created lazily by _run_alignment_demo()
        self.adventurer = None  # created lazily by _run_ravenhollow_demo()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        title = QLabel("🐉 Ethereal DND")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Real ability/class/combat/alignment/world rules math, now with a "
            "real Gnosis-backed narrator - type below and see what happens "
            "(see docs/gnosis_crawler_backlog.md)."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #797986; font-size: 11px;")
        layout.addWidget(subtitle)

        button_row = QHBoxLayout()
        new_campaign_button = QPushButton("🆕 New Campaign")
        new_campaign_button.clicked.connect(self._new_campaign)
        show_party_button = QPushButton("🧑‍🤝‍🧑 Show Party")
        show_party_button.clicked.connect(lambda: self._append(debug_cli.show_party(self.campaign)))
        show_location_button = QPushButton("📍 Show Location")
        show_location_button.clicked.connect(lambda: self._append(debug_cli.show_location(self.campaign)))
        show_time_button = QPushButton("🕒 Show Time")
        show_time_button.clicked.connect(lambda: self._append(debug_cli.show_time(self.campaign)))
        show_history_button = QPushButton("📖 Show History")
        show_history_button.clicked.connect(lambda: self._append(debug_cli.show_history(self.campaign)))
        for button in (
            new_campaign_button, show_party_button, show_location_button,
            show_time_button, show_history_button,
        ):
            button_row.addWidget(button)
        layout.addLayout(button_row)

        roll_row = QHBoxLayout()
        roll_row.addWidget(QLabel("Roll:"))
        self.roll_input = QLineEdit("1d20+3")
        roll_row.addWidget(self.roll_input)
        roll_button = QPushButton("🎲 Roll")
        roll_button.clicked.connect(self._roll)
        roll_row.addWidget(roll_button)
        duel_button = QPushButton("⚔️ Scripted Duel (Fighter vs. Rogue)")
        duel_button.setToolTip(
            "Runs Phase 1's exit-criteria duel: real ability scores, class "
            "progression, equipment, and combat math - deterministic under "
            "this campaign's seed."
        )
        duel_button.clicked.connect(self._run_duel)
        roll_row.addWidget(duel_button)
        alignment_button = QPushButton("⚖️ Paladin Alignment Demo")
        alignment_button.setToolTip(
            "Phase 1.5's exit criterion: a lawful good paladin companion "
            "commits a willful evil act and immediately loses their "
            "paladin powers - the alignment/deity compliance engine, "
            "with no LLM involved."
        )
        alignment_button.clicked.connect(self._run_alignment_demo)
        roll_row.addWidget(alignment_button)
        roll_row.addStretch()
        layout.addLayout(roll_row)

        world_row = QHBoxLayout()
        ravenhollow_button = QPushButton("🏘️ Explore Ravenhollow")
        ravenhollow_button.setToolTip(
            "Recruits an adventurer, talks to Old Mabel, accepts the Wolves of "
            "Blackwood quest, travels there (real travel time + a real random "
            "encounter roll), fights it out if it's combat, and reports the "
            "quest's outcome - Phase 2's exit-criteria loop end to end."
        )
        ravenhollow_button.clicked.connect(self._run_ravenhollow_demo)
        world_row.addWidget(ravenhollow_button)
        world_row.addStretch()
        layout.addLayout(world_row)

        actions_label = QLabel("What will you do?")
        actions_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(actions_label)
        self.action_grid = QGridLayout()
        layout.addLayout(self.action_grid)

        play_row = QHBoxLayout()
        play_row.addWidget(QLabel("What do you do?"))
        self.play_input = QLineEdit()
        self.play_input.setPlaceholderText("e.g. \"I talk to Old Mabel\" or \"I travel to Blackwood\"")
        self.play_input.returnPressed.connect(self._play)
        play_row.addWidget(self.play_input, 1)
        self.play_button = QPushButton("🗣️ Do it")
        self.play_button.setToolTip(
            "Phase 3's real pipeline: your text goes through the intent parser, "
            "the actual rules engine (real dice, real state changes), then the "
            "Gnosis-backed narrator describes only what really happened - a real "
            "model call, so this can take a little while."
        )
        self.play_button.clicked.connect(self._play)
        play_row.addWidget(self.play_button)
        layout.addLayout(play_row)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setFontFamily("Menlo, Consolas, monospace")
        layout.addWidget(self.output, 1)

        self.narrator = debug_cli.create_narrator()
        self._narrative_worker = None

        self._append(f"New campaign: {self.campaign.name} (seed={self.campaign.random_seed})")
        self._append(debug_cli.show_time(self.campaign))
        self._refresh_action_buttons()

    def _append(self, text: str) -> None:
        self.output.append(text)

    def _refresh_action_buttons(self) -> None:
        """Rebuilds the action grid from whatever's really available right
        now (debug_cli.list_actions() -> action_menu.available_actions()) -
        called after every action resolves, since a route just discovered
        or an NPC just killed changes what's on offer.

        One exception to "one button per MenuAction": travel offers one
        entry per real route, which gets noisy once a location has several
        - those are collapsed into a single "Travel" button that pops up a
        submenu of destinations instead, in whatever position the first
        travel entry would otherwise have landed."""
        while self.action_grid.count():
            item = self.action_grid.takeAt(0)
            item.widget().deleteLater()

        all_actions = debug_cli.list_actions(self.campaign)
        travel_options = [a for a in all_actions if a.intent.action_type == "travel"]
        travel_group_placed = False
        index = 0
        for menu_action in all_actions:
            if menu_action.intent.action_type == "travel":
                if travel_group_placed:
                    continue
                travel_group_placed = True
                button = QPushButton("🚶 Travel")
                button.setToolTip("Choose a destination to travel to.")
                button.clicked.connect(
                    lambda _checked=False, opts=travel_options, btn_ref=button: self._show_travel_menu(btn_ref, opts)
                )
            else:
                button = QPushButton(menu_action.label)
                button.clicked.connect(lambda _checked=False, a=menu_action: self._do_menu_action(a))
            self.action_grid.addWidget(button, index // _ACTION_GRID_COLUMNS, index % _ACTION_GRID_COLUMNS)
            index += 1

    def _show_travel_menu(self, button: QPushButton, travel_options: list) -> None:
        menu = QMenu(self)
        for menu_action in travel_options:
            destination_label = menu_action.label.removeprefix("🚶 Travel to ")
            entry = menu.addAction(destination_label)
            entry.triggered.connect(lambda _checked=False, a=menu_action: self._do_menu_action(a))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.play_input.setEnabled(enabled)
        self.play_button.setEnabled(enabled)
        for index in range(self.action_grid.count()):
            self.action_grid.itemAt(index).widget().setEnabled(enabled)

    def _do_menu_action(self, menu_action) -> None:
        if self._narrative_worker is not None:
            return
        self._append(f"> {menu_action.label}")
        self._set_controls_enabled(False)

        self._narrative_worker = _NarrativeWorker(
            lambda: debug_cli.do_action(self.campaign, self.narrator, menu_action)
        )
        self._narrative_worker.result_ready.connect(self._on_play_result)
        self._narrative_worker.error_occurred.connect(self._on_play_error)
        self._narrative_worker.start()

    def _new_campaign(self) -> None:
        self.campaign = debug_cli.new_ravenhollow_campaign()
        self.paladin_companion = None
        self.adventurer = None
        self.output.clear()
        self._append(f"New campaign: {self.campaign.name} (seed={self.campaign.random_seed})")
        self._refresh_action_buttons()

    def _roll(self) -> None:
        expr = self.roll_input.text().strip()
        if not expr:
            return
        try:
            self._append(debug_cli.roll_check(self.campaign, expr))
        except DiceExpressionError as exc:
            self._append(f"Error: {exc}")

    def _run_duel(self) -> None:
        sky = debug_cli.create_test_character(
            "Sky", "fighter", _DUEL_FIGHTER_SCORES, race_id="human",
            weapon_id="longsword", armor_id="chain_shirt", max_hp=13,
        )
        goblin = debug_cli.create_test_character("Goblin", "rogue", _DUEL_ROGUE_SCORES, max_hp=6)
        self._append(debug_cli.run_scripted_duel(self.campaign, sky, goblin))
        self._refresh_action_buttons()

    def _run_alignment_demo(self) -> None:
        if self.paladin_companion is None:
            self.paladin_companion = debug_cli.create_test_character(
                "Sky", "paladin", _PALADIN_SCORES, race_id="human", max_hp=13,
            )
            self.paladin_companion.alignment.law_chaos = 60
            self.paladin_companion.alignment.good_evil = 60
            self.campaign.party.add(self.paladin_companion)
            self._append(f"Recruited {self.paladin_companion.name} the Paladin into the party.")
        self._append(debug_cli.commit_evil_act(
            self.campaign, self.paladin_companion, description="executes a surrendered prisoner",
        ))
        self._refresh_action_buttons()

    def _run_ravenhollow_demo(self) -> None:
        if self.adventurer is None:
            self.adventurer = debug_cli.create_test_character(
                "Rowan", "fighter", _ADVENTURER_SCORES, race_id="human",
                weapon_id="longsword", armor_id="chain_shirt", max_hp=13,
            )
            self.campaign.party.add(self.adventurer)
            self._append(f"Recruited {self.adventurer.name} into the party.")

        self._append(debug_cli.show_location(self.campaign))
        self._append(debug_cli.talk_to(self.campaign, "mabel_innkeeper"))

        if "wolves_of_blackwood" not in self.campaign.state.quest_state:
            self._append(debug_cli.accept_quest(self.campaign, "wolves_of_blackwood"))

        result = travel(self.campaign, "blackwood")
        self._append(result["log"])
        if result["encounter"] and result["encounter"]["type"] == "combat":
            outcome = debug_cli.run_party_combat(self.campaign, [self.adventurer], result["encounter"]["monsters"])
            self._append(outcome["log"])
            if outcome["party_won"]:
                self._append(debug_cli.complete_quest_objective(self.campaign, "wolves_of_blackwood", 0))

        self._append(debug_cli.show_quests(self.campaign))
        self.campaign.current_location_id = "ravenhollow"
        self._refresh_action_buttons()

    def _play(self) -> None:
        text = self.play_input.text().strip()
        if not text or self._narrative_worker is not None:
            return
        self._append(f"> {text}")
        self.play_input.clear()
        self._set_controls_enabled(False)

        self._narrative_worker = _NarrativeWorker(lambda: debug_cli.play(self.campaign, self.narrator, text))
        self._narrative_worker.result_ready.connect(self._on_play_result)
        self._narrative_worker.error_occurred.connect(self._on_play_error)
        self._narrative_worker.start()

    def _on_play_result(self, narration: str) -> None:
        self._append(narration)
        self._reset_play_controls()

    def _on_play_error(self, message: str) -> None:
        self._append(f"Error: {message}")
        self._reset_play_controls()

    def _reset_play_controls(self) -> None:
        self._narrative_worker = None
        self._refresh_action_buttons()
        self._set_controls_enabled(True)
