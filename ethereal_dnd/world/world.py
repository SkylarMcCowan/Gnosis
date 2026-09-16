"""World (design doc Section 29) - a graph of Locations connected by
Routes, plus the NPCs living in them (Section 37). Real travel-time
computation lives in world/travel.py.
"""
import dataclasses

from ethereal_dnd.world.location import Location
from ethereal_dnd.world.npc import NPC
from ethereal_dnd.world.route import Route


@dataclasses.dataclass
class World:
    locations: dict[str, Location] = dataclasses.field(default_factory=dict)
    routes: list[Route] = dataclasses.field(default_factory=list)
    npcs: dict[str, NPC] = dataclasses.field(default_factory=dict)

    def add_location(self, location: Location) -> None:
        self.locations[location.id] = location

    def add_route(self, route: Route) -> None:
        self.routes.append(route)

    def routes_from(self, location_id: str) -> list[Route]:
        return [route for route in self.routes if route.origin_id == location_id]

    def add_npc(self, npc: NPC) -> None:
        self.npcs[npc.id] = npc
        location = self.locations[npc.location_id]
        if npc.id not in location.npc_ids:
            location.npc_ids.append(npc.id)

    def npcs_at(self, location_id: str) -> list[NPC]:
        return [npc for npc in self.npcs.values() if npc.location_id == location_id]
