"""Route (design doc Section 27) - connects two Locations. Real
travel-time math is a later ticket; Phase 0 only fixes the shape.
"""
import dataclasses


@dataclasses.dataclass
class Route:
    origin_id: str
    destination_id: str
    distance_miles: float = 0.0
    terrain: str = "road"
    road_quality: str = "good"
    danger_level: int = 0
    base_travel_time_hours: float = 0.0
    discovered: bool = True
