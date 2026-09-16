"""Real Narrator implementation (design doc Section 55/56), wired to
Gnosis's existing model integration (core.models.chat) rather than a new
LLM client. Produces description/dialogue/consequence narration strictly
from rules-engine results handed to it - it is never asked to decide
whether something happened, only to describe what already did (Section
2.1: the AI never overrides mechanics).
"""
from core.models import MODELS, chat as model_chat

from ethereal_dnd.narrative.narrator import Narrator

_NARRATE_EVENT_SYSTEM_PROMPT = """You are the narrator for a D&D 3.5-inspired game. You will be given \
a real mechanical result that already happened - a resolved action, in structured form - plus the \
current scene's context. Describe it vividly in 1-3 sentences, in the second person ("you"). \
Do NOT invent any mechanical fact (damage numbers, success/failure, whether someone died, \
what an NPC says) beyond what is given to you. If the result says the action failed or is \
unsupported, describe that honestly rather than making something else succeed instead."""

_DESCRIBE_LOCATION_SYSTEM_PROMPT = """You are the narrator for a D&D 3.5-inspired game. Describe the \
given location vividly in 2-4 sentences, in the second person ("you"). Use only the facts given - \
don't invent NPCs, items, or events that aren't in the provided description."""

_RESPOND_TO_DIALOGUE_SYSTEM_PROMPT = """You are voicing one NPC in a D&D 3.5-inspired game, given their \
name, role, and personality. Stay fully in character, respond to what the player said in 1-3 \
sentences, and only reveal information explicitly listed as things this NPC knows (their rumors) - \
never invent new quest hooks, lore, or promises on the NPC's behalf."""


def _default_chat_fn(messages: list) -> str:
    # See narrative/intent_parser.py's _default_chat_fn for why this is
    # MODELS["main"] rather than MODELS["fast"] (yi:6b) - the same
    # live-tested finding applies here (narration doesn't go through
    # agent_dialogue's clarify path today, but there's no reason to use
    # a model documented as prone to that quirk when a better option is
    # already available and already warm from intent parsing).
    response = model_chat(MODELS["main"], messages)
    return response.get("message", {}).get("content", "")


class GnosisNarrator(Narrator):
    def __init__(self, chat_fn=None):
        self._chat_fn = chat_fn or _default_chat_fn

    def narrate_event(self, event) -> str:
        from ethereal_dnd.campaign.history import format_event

        return self._chat_fn([
            {"role": "system", "content": _NARRATE_EVENT_SYSTEM_PROMPT},
            {"role": "user", "content": f"What happened: {format_event(event)}"},
        ]).strip()

    def describe_location(self, location) -> str:
        return self._chat_fn([
            {"role": "system", "content": _DESCRIBE_LOCATION_SYSTEM_PROMPT},
            {"role": "user", "content": f"Location: {location.name}\nFacts: {location.description}"},
        ]).strip()

    def respond_to_dialogue(self, character, npc, player_text: str) -> str:
        return self._chat_fn([
            {"role": "system", "content": _RESPOND_TO_DIALOGUE_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"You are {npc.name}, a {npc.role}. Personality: {npc.character.personality}\n"
                f"Things you know (rumors): {[r['text'] for r in npc.rumors]}\n"
                f"The player says: \"{player_text}\""
            )},
        ]).strip()

    def narrate_resolved_action(self, resolution: dict, context: dict) -> str:
        """The actual entry point Phase 3's game loop uses: describe an
        action_resolver.resolve_action() result given the current scene
        context from context_builder.build_context()."""
        return self._chat_fn([
            {"role": "system", "content": _NARRATE_EVENT_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Scene: {context['location']['name']}, {context['current_time']}\n"
                f"Resolved action ({resolution['kind']}, resolved={resolution['resolved']}): "
                f"{resolution['log']}"
            )},
        ]).strip()

    def interpret_player_intent(self, player_text: str) -> dict:
        """Deliberately not implemented here - intent parsing is a
        distinct, earlier pipeline stage (narrative/intent_parser.py's
        parse_intent()), not the narrator's job. Section 55 lists this as
        one of the four Narrator methods, but Section 34's own pipeline
        diagram puts intent parsing *before* the rules engine runs and
        narration *after* - conflating them in one class would blur that
        boundary. Kept as a required abstract method for interface
        compatibility; call parse_intent() directly instead."""
        raise NotImplementedError("Use narrative.intent_parser.parse_intent() instead.")
