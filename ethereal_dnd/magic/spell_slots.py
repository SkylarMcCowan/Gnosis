"""Spell slot table per class/level (design doc Section 12's
spellcasting tables, already stored per-class in
ethereal_dnd/data/classes/*.json's `spellcasting.spells_per_day`, sourced
verbatim from docs/srd_reference/core/ClassesI.md (Cleric),
ClassesII.md (Wizard)).
"""
from ethereal_dnd.characters.class_definition import class_registry


def spells_per_day(class_id: str, class_level: int) -> list[int]:
    """Index 0 = 0-level slots, index 1 = 1st-level slots, etc. - the
    same row shape as the sourced Cleric/Wizard tables (the "+1" domain
    spell slot the SRD adds to a cleric's non-0 levels is a deliberate
    simplification left out for now - Section 12's "Deity, Domains, and
    Domain Spells" system isn't modeled yet). Raises if the class
    doesn't cast spells or the level is out of the table's range."""
    class_def = class_registry.get(class_id)
    if class_def.spellcasting is None:
        raise ValueError(f"{class_def.name} does not cast spells")
    table = class_def.spellcasting["spells_per_day"]
    if not 1 <= class_level <= len(table):
        raise ValueError(f"{class_def.name} has no spells-per-day row for level {class_level}")
    return table[class_level - 1]


def spells_per_day_for(character, class_id: str) -> list[int]:
    """Same as spells_per_day(), but for a real Character: returns all
    zeros if the alignment/deity compliance engine has revoked this
    class's powers (Phase 1.5's actual ability gate - GC-047) instead of
    whatever the class's level-based table would otherwise grant."""
    class_level = next((cl.levels for cl in character.class_levels if cl.class_id == class_id), None)
    if class_level is None:
        raise ValueError(f"{character.name or character.id} has no levels in {class_id!r}")
    if not character.can_use_class_powers(class_id):
        table_length = len(spells_per_day(class_id, class_level))
        return [0] * table_length
    return spells_per_day(class_id, class_level)
