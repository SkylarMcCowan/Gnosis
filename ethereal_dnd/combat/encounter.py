"""Encounter (design doc Section 16) - the combat state shape. No
resolution logic yet (initiative/attack/damage math are later tickets) -
Phase 0 only fixes what an Encounter holds.
"""
import dataclasses

from ethereal_dnd.core.ids import new_id


@dataclasses.dataclass
class Encounter:
    id: str = dataclasses.field(default_factory=new_id)
    participant_ids: list[str] = dataclasses.field(default_factory=list)
    initiative_order: list[str] = dataclasses.field(default_factory=list)
    current_round: int = 0
    current_actor_index: int = 0
    battlefield: dict = dataclasses.field(default_factory=dict)
    positions: dict[str, tuple] = dataclasses.field(default_factory=dict)
    conditions: dict[str, list[str]] = dataclasses.field(default_factory=dict)
    combat_log: list[str] = dataclasses.field(default_factory=list)
