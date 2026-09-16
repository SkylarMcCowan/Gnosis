"""Relationship tracking (design doc Section 38) - a simple numeric
score per other character id, stored on Character.relationships (already
part of the Phase 0 shape). The fuller approve/disapprove/leave/betray
behaviors are Phase 10 ("Companion relationships") content; this is the
minimal foundation Phase 3's dialogue needs to mean anything at all.
"""


def adjust_relationship(character, other_id: str, delta: float) -> float:
    character.relationships[other_id] = character.relationships.get(other_id, 0.0) + delta
    return character.relationships[other_id]


def get_relationship(character, other_id: str) -> float:
    return character.relationships.get(other_id, 0.0)
