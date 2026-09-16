"""Intent parser (design doc Section 32/34) - freeform player text ->
structured ActionIntent, via the existing Gnosis model integration
(core.models.chat + agent_dialogue.call_agent_json's JSON-decision
plumbing) rather than a new LLM client. This is the one place in the
crawler an LLM call happens *before* the rules engine runs - the
parser's only job is figuring out what the player is trying to do, never
whether it succeeds.
"""
import json

import agent_dialogue
from core.models import MODELS, chat as model_chat

from ethereal_dnd.narrative.action_intent import KNOWN_ACTION_TYPES, ActionIntent

_SYSTEM_PROMPT_TEMPLATE = """You are the intent-parsing layer for a D&D 3.5-inspired game engine. \
Your only job is to turn the player's freeform message into a structured JSON action - \
you never decide whether it succeeds, what it costs, or any other mechanical outcome. \
That's the rules engine's job, not yours.

Respond with EXACTLY one JSON object, nothing else - no markdown fences, no commentary:
{{
  "action_type": one of {action_types},
  "actor_id": "player" (always this fixed value for now - the parser doesn't yet resolve which \
party member specifically),
  "target_id": the id of an NPC (from "NPCs present" below) this action targets, or null,
  "skill_id": for action_type "skill_check" only - one of {skill_ids}, or null otherwise,
  "spell_id": for action_type "cast_spell" only - the spell's id, or null otherwise,
  "destination_id": for action_type "travel" only - one of {location_ids}, or null otherwise,
  "duration_hours": for action_type "wait" only - a number of hours, or null otherwise,
  "description": a short (under 15 words) paraphrase of what the player is attempting
}}

Use "look" for the player observing their surroundings, checking who's nearby, or asking what's \
here - anything that's really "describe the current scene," not a specific check or action.

Use "unsupported" for anything that isn't clearly one of the other action types (burning down \
a building, seducing a guard, anything with no real mechanical handling yet) - that is a \
correct, expected answer, not a failure to understand the player.

Current situation:
{context_summary}
"""


def _default_chat_fn(messages: list) -> str:
    # Deliberately not MODELS["fast"] (yi:6b), despite that being the
    # model core/models.py's own comment recommends for "internal
    # JSON-decision plumbing" generally - live-tested here, yi:6b asked a
    # spurious clarifying question ("by title or by id?") for as simple
    # a prompt as "I talk to Old Mabel.", triggering agent_dialogue's
    # clarify round-trip for something that was never actually ambiguous.
    # MODELS["main"] (qwen3.5:4b) handled the same prompts correctly with
    # no clarify triggered - the better fit for a narrative game loop,
    # where interrupting the player with a confused question is worse
    # than just picking the obvious interpretation.
    response = model_chat(MODELS["main"], messages)
    return response.get("message", {}).get("content", "")


def _context_summary(context: dict) -> str:
    lines = [
        f"Location: {context['location']['name']} - {context['location']['description']}",
        f"Time: {context['current_time']}",
    ]
    if context["npcs_present"]:
        lines.append("NPCs present: " + ", ".join(
            f"{npc['name']} (id: {npc['id']})" for npc in context["npcs_present"] if npc["alive"]
        ))
    if context["routes"]:
        lines.append("Reachable locations: " + ", ".join(
            f"{route['destination_name']} (id: {route['destination_id']})" for route in context["routes"]
        ))
    return "\n".join(lines)


def build_system_prompt(context: dict, skill_ids: list[str], location_ids: list[str]) -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(
        action_types=json.dumps(list(KNOWN_ACTION_TYPES)),
        skill_ids=json.dumps(skill_ids),
        location_ids=json.dumps(location_ids),
        context_summary=_context_summary(context),
    )


def parse_intent(player_text: str, context: dict, chat_fn=None) -> ActionIntent:
    """Parse `player_text` into an ActionIntent, given the bounded
    `context` from context_builder.build_context(). Falls back to
    action_type "unsupported" (never raises, never guesses a mechanical
    outcome) if the model's response can't be parsed at all."""
    from ethereal_dnd.characters.skills import skill_registry

    skill_ids = [skill.id for skill in skill_registry.all()]
    location_ids = [route["destination_id"] for route in context["routes"]]
    system_prompt = build_system_prompt(context, skill_ids, location_ids)

    result = agent_dialogue.call_agent_json(
        chat_fn or _default_chat_fn,
        system_prompt,
        extra_messages=[{"role": "user", "content": player_text}],
    )

    if not isinstance(result, dict) or result.get("action_type") not in KNOWN_ACTION_TYPES:
        return ActionIntent(
            action_type="unsupported",
            description="Could not understand the request.",
            raw_text=player_text,
        )

    return ActionIntent(
        action_type=result["action_type"],
        actor_id=result.get("actor_id") or "player",
        target_id=result.get("target_id"),
        skill_id=result.get("skill_id"),
        spell_id=result.get("spell_id"),
        destination_id=result.get("destination_id"),
        duration_hours=result.get("duration_hours"),
        description=result.get("description", ""),
        raw_text=player_text,
    )
