"""Narrator interface (design doc Section 55) - the abstract boundary
between the rules engine and any LLM. The engine must run with zero
narrative involvement; NullNarrator proves that for Phase 0. Phase 3's
narrative/gnosis_narrator.py provides the real Gnosis-backed
implementation.
"""
from abc import ABC, abstractmethod


class Narrator(ABC):
    @abstractmethod
    def narrate_event(self, event) -> str: ...

    @abstractmethod
    def describe_location(self, location) -> str: ...

    @abstractmethod
    def respond_to_dialogue(self, character, npc, player_text: str) -> str: ...

    @abstractmethod
    def interpret_player_intent(self, player_text: str) -> dict: ...

    @abstractmethod
    def narrate_resolved_action(self, resolution: dict, context: dict) -> str:
        """Describe an already-resolved action_resolver.resolve_action()
        result (Phase 3) - the entry point narrative/game_loop.py's
        process_player_input() actually uses. Not in Section 55's
        original four methods (that section predates having a real
        resolved-action shape to narrate), added here once Phase 3 needed
        it so every Narrator implementation - not just GnosisNarrator -
        has to answer for it."""


class NullNarrator(Narrator):
    """Canned-string implementation with no LLM dependency - proves the
    engine runs standalone (Section 55/56)."""

    def narrate_event(self, event) -> str:
        return f"[{event.type}]"

    def describe_location(self, location) -> str:
        return location.description or location.name

    def respond_to_dialogue(self, character, npc, player_text: str) -> str:
        return "..."

    def interpret_player_intent(self, player_text: str) -> dict:
        return {"action": "unknown", "raw_text": player_text}

    def narrate_resolved_action(self, resolution: dict, context: dict) -> str:
        return resolution.get("log", "")
