"""RaceDefinition (design doc Section 11) - the 7 starting races, sourced
verbatim from docs/srd_reference/core/Races.md, loaded into race_registry
by load_races() below.
"""
import dataclasses
import json
import os

from ethereal_dnd.core.registry import Registry

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "races")


@dataclasses.dataclass
class RaceDefinition:
    id: str
    name: str
    ability_modifiers: dict[str, int] = dataclasses.field(default_factory=dict)
    size: str = "Medium"
    speed: int = 30
    languages: list[str] = dataclasses.field(default_factory=list)
    racial_traits: list[str] = dataclasses.field(default_factory=list)
    favored_class: str | None = None
    special_abilities: list[str] = dataclasses.field(default_factory=list)


race_registry = Registry("race")


def load_races(target_registry: Registry | None = None, data_dir: str | None = None) -> None:
    """Load every data/races/*.json definition into `target_registry`
    (default: the module-level race_registry). Idempotent - see
    characters/skills.py's load_skills() for why."""
    registry_to_use = target_registry if target_registry is not None else race_registry
    directory = data_dir or _DATA_DIR
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(directory, filename), "r", encoding="utf-8") as f:
            data = json.load(f)
        if data["id"] in registry_to_use:
            continue
        registry_to_use.register(data["id"], RaceDefinition(**data))
