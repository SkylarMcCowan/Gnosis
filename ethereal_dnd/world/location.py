"""Location (design doc Section 30) - a stateful, interactive place. What
actually happens on a "talk"/"rest"/"trade" interaction is Phase 2
content; Phase 0 only fixes the shape (and the discovered/locked state
from Section 29).
"""
import dataclasses


@dataclasses.dataclass
class Location:
    id: str
    name: str
    description: str = ""
    npc_ids: list[str] = dataclasses.field(default_factory=list)
    discovered: bool = True
    locked: bool = False
