"""Action menu - a list of concrete, ready-to-resolve ActionIntents built
directly from real campaign state, with no LLM guess involved in
constructing them. This is the "contain the logic" alternative to typing
freeform text for anything the game already knows how to enumerate: a
button's intent is already fully determined, so game_loop.process_menu_action()
can skip the intent parser (and its failure modes - misparsed targets, an
occasional spurious clarify) entirely for these.

Freeform text (intent_parser.py, still wired to the GUI's own input box)
remains available for anything not covered here - Section 31 is explicit
that a fixed menu must never be the *only* way to act, so this
supplements the parser rather than replacing it.
"""
import dataclasses

from ethereal_dnd.narrative.action_intent import ActionIntent
from ethereal_dnd.narrative.context_builder import build_context


@dataclasses.dataclass(frozen=True)
class MenuAction:
    label: str
    intent: ActionIntent


def available_actions(campaign) -> list[MenuAction]:
    """Every action currently offered as a button: look around, talk to
    or attack whoever's actually here (alive NPCs only), travel to
    whichever destinations actually have a route from here, and rest.
    Recomputed fresh each call - never cached - since it must reflect
    whatever just changed (a route just discovered, an NPC just killed)."""
    context = build_context(campaign)
    actions = [MenuAction("👀 Look Around", ActionIntent(action_type="look"))]

    living_npcs = [npc for npc in context["npcs_present"] if npc["alive"]]
    for npc in living_npcs:
        actions.append(MenuAction(
            f"💬 Talk to {npc['name']}", ActionIntent(action_type="talk", target_id=npc["id"]),
        ))

    for route in context["routes"]:
        actions.append(MenuAction(
            f"🚶 Travel to {route['destination_name']}",
            ActionIntent(action_type="travel", destination_id=route["destination_id"]),
        ))

    actions.append(MenuAction("🏕️ Rest", ActionIntent(action_type="rest")))

    for npc in living_npcs:
        actions.append(MenuAction(
            f"⚔️ Attack {npc['name']}", ActionIntent(action_type="attack", target_id=npc["id"]),
        ))

    return actions
