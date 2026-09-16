"""Travel (design doc Section 27) - moving the party between Locations
along a Route, advancing the campaign clock by the route's real travel
time and rolling for a random encounter along the way (Section 28,
encounters/random_encounters.py).
"""
from ethereal_dnd.core.events import LocationDiscovered, PartyArrived, PartyTravelStarted
from ethereal_dnd.encounters.random_encounters import roll_encounter


class NoRouteError(ValueError):
    pass


def find_route(world, origin_id: str, destination_id: str):
    for route in world.routes_from(origin_id):
        if route.destination_id == destination_id:
            return route
    raise NoRouteError(f"No route from {origin_id!r} to {destination_id!r}")


def travel(campaign, destination_id: str) -> dict:
    """Move the party from campaign.current_location_id to
    destination_id. Returns {"log": str, "encounter": EncounterResult | None}
    - the caller (CLI/GUI) decides what to do with an encounter, this
    function only rolls whether one happens (encounters/random_encounters.py
    owns the actual roll)."""
    origin_id = campaign.current_location_id
    route = find_route(campaign.world, origin_id, destination_id)
    lines = [f"[TRAVEL] {campaign.world.locations[origin_id].name} -> {campaign.world.locations[destination_id].name}"]

    campaign.events.emit(PartyTravelStarted(origin_id=origin_id, destination_id=destination_id))
    campaign.current_time.advance(hours=route.base_travel_time_hours)
    lines.append(f"{route.base_travel_time_hours} hour(s) pass. {campaign.current_time}")

    destination = campaign.world.locations[destination_id]
    if not destination.discovered:
        destination.discovered = True
        campaign.events.emit(LocationDiscovered(location_id=destination_id))
        lines.append(f"Discovered: {destination.name}")

    campaign.current_location_id = destination_id
    campaign.events.emit(PartyArrived(location_id=destination_id))

    encounter = roll_encounter(route, campaign.rng())
    if encounter is not None:
        lines.append(encounter["log"])

    return {"log": "\n".join(lines), "encounter": encounter}
