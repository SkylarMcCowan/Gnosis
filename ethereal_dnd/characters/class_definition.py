"""ClassDefinition (design doc Section 12) - the 5 starting classes,
sourced verbatim from docs/srd_reference/core/ClassesI.md, ClassesII.md,
loaded into class_registry by load_classes() below. A Character's
class_levels is always a list of ClassLevel entries (see class_level.py),
never a single class/level pair, so multiclassing (Section 13) never
needs a data-model change later.
"""
import dataclasses
import json
import os

from ethereal_dnd.core.registry import Registry

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "classes")


@dataclasses.dataclass
class ClassDefinition:
    id: str
    name: str
    hit_die: int = 6
    base_attack_progression: str = "average"  # "good" | "average" | "poor"
    save_progression: dict[str, str] = dataclasses.field(default_factory=dict)  # fortitude/reflex/will -> "good"|"poor"
    class_skills: list[str] = dataclasses.field(default_factory=list)
    skill_points_per_level: int = 2
    weapon_proficiencies: list[str] = dataclasses.field(default_factory=list)
    armor_proficiencies: list[str] = dataclasses.field(default_factory=list)
    class_features: list[str] = dataclasses.field(default_factory=list)
    spellcasting: dict | None = None
    # List of ComplianceRule dicts (docs/gnosis_crawler_alignment.md §3) -
    # a list, not a single rule, because e.g. a paladin falls on *any* of
    # three independent triggers (ceasing to be LG, one willful evil act,
    # or a gross code violation) - see ethereal_dnd/divine/compliance.py
    # for how these are evaluated. Empty for classes with no restriction.
    alignment_restriction: list[dict] = dataclasses.field(default_factory=list)


class_registry = Registry("class")


def load_classes(target_registry: Registry | None = None, data_dir: str | None = None) -> None:
    """Load every data/classes/*.json definition into `target_registry`
    (default: the module-level class_registry). Idempotent - see
    characters/skills.py's load_skills() for why."""
    registry_to_use = target_registry if target_registry is not None else class_registry
    directory = data_dir or _DATA_DIR
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(directory, filename), "r", encoding="utf-8") as f:
            data = json.load(f)
        if data["id"] in registry_to_use:
            continue
        registry_to_use.register(data["id"], ClassDefinition(**data))
