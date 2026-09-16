"""SpellDefinition (design doc Section 20) - the starting spell list
(Magic Missile, Cure Light Wounds, Bless, Detect Magic), sourced verbatim
from docs/srd_reference/extra/Spells*.md, loaded into spell_registry by
load_spells() below.
"""
import dataclasses
import json
import os

from ethereal_dnd.core.registry import Registry
from ethereal_dnd.magic.spell_effects import build_effect

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "spells")


@dataclasses.dataclass
class SpellDefinition:
    id: str
    name: str
    school: str
    levels: dict[str, int]  # class_id -> spell level, e.g. {"wizard": 1}
    casting_time: str
    range: str
    target: str | None
    duration: str
    saving_throw: str
    spell_resistance: str
    components: list[str]
    effect_type: str  # "damage" | "healing" | "buff" | "condition" | "utility"
    effect_params: dict = dataclasses.field(default_factory=dict)

    def build_effect(self):
        return build_effect(self.effect_type, self.effect_params)


spell_registry = Registry("spell")


def load_spells(target_registry: Registry | None = None, data_dir: str | None = None) -> None:
    """Load every data/spells/*.json definition into `target_registry`
    (default: the module-level spell_registry). Idempotent - see
    characters/skills.py's load_skills() for why."""
    registry_to_use = target_registry if target_registry is not None else spell_registry
    directory = data_dir or _DATA_DIR
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(directory, filename), "r", encoding="utf-8") as f:
            data = json.load(f)
        if data["id"] in registry_to_use:
            continue
        registry_to_use.register(data["id"], SpellDefinition(**data))
