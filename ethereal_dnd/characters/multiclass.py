"""Multiclass level-up helpers (design doc Section 13) - Phase 0 only
stubs the entry point; a later ticket fills in the actual BAB/save
recomputation that should happen alongside this.
"""
from ethereal_dnd.characters.character import Character
from ethereal_dnd.characters.class_level import ClassLevel


def add_class_level(character: Character, class_id: str) -> None:
    """Add one level in `class_id` to `character`, creating a new
    ClassLevel entry if this is the character's first level in that
    class, or incrementing the existing one otherwise."""
    for class_level in character.class_levels:
        if class_level.class_id == class_id:
            class_level.levels += 1
            return
    character.class_levels.append(ClassLevel(class_id=class_id, levels=1))
