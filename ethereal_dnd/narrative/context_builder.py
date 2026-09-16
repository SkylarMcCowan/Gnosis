"""Narrative context builder (design doc Section 34/45) - assembles the
bounded context handed to both the intent parser (so it can resolve "the
blacksmith" to a real NPC id) and the narrator (so it can describe what
just happened without inventing anything). Recent history is summarized
(the last few entries), never the whole log - Section 45 is explicit
that passing the entire history to a model is the wrong approach.
"""
DEFAULT_HISTORY_WINDOW = 8


def build_context(campaign, history_window: int = DEFAULT_HISTORY_WINDOW) -> dict:
    location = campaign.world.locations[campaign.current_location_id]
    npcs_here = campaign.world.npcs_at(location.id)
    routes = campaign.world.routes_from(location.id)

    return {
        "current_time": str(campaign.current_time),
        "location": {
            "id": location.id,
            "name": location.name,
            "description": location.description,
        },
        "npcs_present": [
            {"id": npc.id, "name": npc.name, "role": npc.role, "alive": npc.alive}
            for npc in npcs_here
        ],
        "routes": [
            {"destination_id": route.destination_id, "destination_name": campaign.world.locations[route.destination_id].name}
            for route in routes
        ],
        "party": [_character_summary(member) for member in campaign.party.members],
        "active_quests": [
            {"id": quest.id, "title": quest.title, "objectives": [o["description"] for o in quest.objectives if not o["done"]]}
            for quest in campaign.state.quest_state.values()
            if quest.state == "active"
        ],
        "recent_history": campaign.history[-history_window:],
    }


def describe_location_text(context: dict) -> str:
    """Plain-text summary of context["location"]/["npcs_present"]/
    ["routes"] - shared by debug_cli.show_location() and
    action_resolver.py's "look" handler so there's exactly one place
    that formats "what's here" from a context dict, not two drifting
    copies of the same three lines."""
    location = context["location"]
    lines = [f"{location['name']}: {location['description']}"]
    alive_npcs = [npc for npc in context["npcs_present"] if npc["alive"]]
    if alive_npcs:
        lines.append("People here: " + ", ".join(f"{npc['name']} ({npc['role']})" for npc in alive_npcs))
    if context["routes"]:
        lines.append("Routes: " + ", ".join(route["destination_name"] for route in context["routes"]))
    return "\n".join(lines)


def _character_summary(character) -> dict:
    return {
        "id": character.id,
        "name": character.name,
        "status": character.status,
        "hp": f"{character.max_hp - character.damage}/{character.max_hp}",
        "conditions": list(character.conditions),
    }
