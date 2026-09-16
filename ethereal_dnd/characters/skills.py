"""SkillDefinition (design doc Section 14) - the full standard SRD skill
list (docs/srd_reference/core/SkillsI.md, SkillsII.md), loaded into
skill_registry by load_skills() below.
"""
import dataclasses
import json
import os

from ethereal_dnd.core.registry import Registry

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "skills")


@dataclasses.dataclass
class SkillDefinition:
    id: str
    name: str
    # "STR" | "DEX" | "CON" | "INT" | "WIS" | "CHA" | None - Speak
    # Language is the one core skill with no ability check at all (ranks
    # alone determine languages known), so this must be optional.
    key_ability: str | None
    trained_only: bool = False
    armor_check_penalty: bool = False
    class_skill_by_class: list[str] = dataclasses.field(default_factory=list)


skill_registry = Registry("skill")


def load_skills(target_registry: Registry | None = None, data_dir: str | None = None) -> None:
    """Load every data/skills/*.json definition into `target_registry`
    (default: the module-level skill_registry). Idempotent: an id already
    present is left alone rather than raising, so this is safe to call
    more than once in the same process (e.g. once per test, once per
    campaign) without hitting Registry's duplicate-registration guard."""
    registry_to_use = target_registry if target_registry is not None else skill_registry
    directory = data_dir or _DATA_DIR
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(directory, filename), "r", encoding="utf-8") as f:
            data = json.load(f)
        if data["id"] in registry_to_use:
            continue
        registry_to_use.register(data["id"], SkillDefinition(**data))
