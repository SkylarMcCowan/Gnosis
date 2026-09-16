"""NPC (design doc Section 37) - wraps a Character (for stats, since
NPCs use the same class/ability/combat math as PCs - built from NPC
classes per docs/srd_reference/extra/NPCClasses.md, not player classes)
with the extra fields Section 37 wants that Character doesn't have:
role, location, faction, schedule, goals, and the rumors it can share.
"""
import dataclasses

from ethereal_dnd.characters.character import Character
from ethereal_dnd.characters.hit_points import average_max_hp
from ethereal_dnd.characters.multiclass import add_class_level


@dataclasses.dataclass
class NPC:
    character: Character
    role: str
    location_id: str
    faction_id: str | None = None
    schedule: dict = dataclasses.field(default_factory=dict)
    goals: list[str] = dataclasses.field(default_factory=list)
    rumors: list[dict] = dataclasses.field(default_factory=list)  # [{"text": str, "quest_id": str | None}]
    stock: list[str] = dataclasses.field(default_factory=list)  # ItemDefinition ids this NPC sells - empty means "not a shop"

    @property
    def id(self) -> str:
        return self.character.id

    @property
    def name(self) -> str:
        return self.character.name

    @property
    def alive(self) -> bool:
        return self.character.status == "alive"


def build_npc(
    npc_id: str,
    name: str,
    role: str,
    location_id: str,
    npc_class: str,
    npc_level: int,
    ability_scores: dict[str, int],
    personality: str = "",
    faction_id: str | None = None,
    goals: list[str] | None = None,
    rumors: list[dict] | None = None,
    deity_id: str | None = None,
    stock: list[str] | None = None,
) -> NPC:
    """Build an NPC's backing Character from an NPC class + level (average
    HP, per characters/hit_points.py, not rolled - see that module's
    docstring for why)."""
    from ethereal_dnd.characters.class_definition import class_registry

    class_def = class_registry.get(npc_class)
    con_modifier = (ability_scores.get("CON", 10) - 10) // 2
    character = Character(
        id=npc_id,
        name=name,
        ability_scores=dict(ability_scores),
        personality=personality,
        deity_id=deity_id,
        max_hp=average_max_hp(class_def.hit_die, npc_level, con_modifier),
    )
    for _ in range(npc_level):
        add_class_level(character, npc_class)
    return NPC(
        character=character,
        role=role,
        location_id=location_id,
        faction_id=faction_id,
        goals=list(goals or []),
        rumors=list(rumors or []),
        stock=list(stock or []),
    )
