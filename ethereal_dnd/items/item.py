"""ItemDefinition / ItemInstance split (design doc Section 8) - a
definition is "what a longsword is," an instance is "this particular +1
longsword this character is carrying." Weapon and armor data (sourced
from docs/srd_reference/core/Equipment.md) loads into item_registry via
load_items() below.
"""
import dataclasses
import json
import os

from ethereal_dnd.core.ids import new_id
from ethereal_dnd.core.registry import Registry

_WEAPONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "weapons")
_ARMOR_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "armor")


@dataclasses.dataclass
class ItemDefinition:
    id: str
    name: str
    weight: float = 0.0
    value_gp: int = 0
    properties: dict = dataclasses.field(default_factory=dict)
    requirements: list[str] = dataclasses.field(default_factory=list)
    effects: list[str] = dataclasses.field(default_factory=list)
    equipment_slot: str | None = None
    rarity: str = "mundane"


@dataclasses.dataclass
class ItemInstance:
    id: str = dataclasses.field(default_factory=new_id)
    definition_id: str = ""
    quantity: int = 1


item_registry = Registry("item")


def _load_dir(directory: str, target_registry: Registry) -> None:
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(directory, filename), "r", encoding="utf-8") as f:
            data = json.load(f)
        if data["id"] in target_registry:
            continue
        target_registry.register(data["id"], ItemDefinition(**data))


def load_items(target_registry: Registry | None = None) -> None:
    """Load every data/weapons/*.json and data/armor/*.json definition
    into `target_registry` (default: the module-level item_registry).
    Idempotent - see characters/skills.py's load_skills() for why."""
    registry_to_use = target_registry if target_registry is not None else item_registry
    _load_dir(_WEAPONS_DIR, registry_to_use)
    _load_dir(_ARMOR_DIR, registry_to_use)
