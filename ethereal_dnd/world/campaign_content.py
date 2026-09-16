"""The Ashes of Ravenhollow (design doc Section 46) - loads the starting
campaign's locations, routes, and NPCs from ethereal_dnd/data/{locations,
world,npcs}/ into a Campaign's World. One function, called once per
campaign, the same "load at startup" idiom as the class/race/skill/item/
spell/deity loaders (debug_cli.bootstrap_data()) - except this builds
live World/NPC instances rather than populating a shared registry, since
a location or NPC is per-campaign state (Section 8), not shared content
like a class or race.
"""
import json
import os

from ethereal_dnd.world.location import Location
from ethereal_dnd.world.npc import build_npc
from ethereal_dnd.world.route import Route

_LOCATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "locations")
_NPCS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "npcs")
_ROUTES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "world", "routes.json")


def load_ashes_of_ravenhollow(campaign) -> None:
    """Populate `campaign.world` with every location/route/NPC in the
    starting campaign. Idempotent by location/NPC id - see
    characters/skills.py's load_skills() for the general pattern this
    follows, adapted for live instances instead of a shared registry."""
    world = campaign.world

    for filename in sorted(os.listdir(_LOCATIONS_DIR)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(_LOCATIONS_DIR, filename), "r", encoding="utf-8") as f:
            data = json.load(f)
        if data["id"] in world.locations:
            continue
        world.add_location(Location(**data))

    with open(_ROUTES_FILE, "r", encoding="utf-8") as f:
        route_dicts = json.load(f)
    existing_routes = {(r.origin_id, r.destination_id) for r in world.routes}
    for route_data in route_dicts:
        key = (route_data["origin_id"], route_data["destination_id"])
        if key in existing_routes:
            continue
        world.add_route(Route(**route_data))

    for filename in sorted(os.listdir(_NPCS_DIR)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(_NPCS_DIR, filename), "r", encoding="utf-8") as f:
            data = json.load(f)
        if data["id"] in world.npcs:
            continue
        npc = build_npc(
            npc_id=data["id"], name=data["name"], role=data["role"],
            location_id=data["location_id"], npc_class=data["npc_class"],
            npc_level=data["npc_level"], ability_scores=data["ability_scores"],
            personality=data.get("personality", ""), faction_id=data.get("faction_id"),
            goals=data.get("goals"), rumors=data.get("rumors"), deity_id=data.get("deity_id"),
            stock=data.get("stock"),
        )
        world.add_npc(npc)

    if campaign.current_location_id is None:
        campaign.current_location_id = "ravenhollow"
