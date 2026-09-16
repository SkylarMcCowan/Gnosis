"""Atonement / restoration (alignment doc §5). "realignment"-restoration
classes (monk, barbarian) auto-clear inside divine/compliance.py's
evaluate_character() the moment the trigger stops being violated - no
ritual needed, per the SRD's lighter treatment of those two. This module
is for the other kind: "atonement"-restoration classes (paladin, cleric,
druid), which stay revoked even after the alignment vector drifts back,
until something explicit (the atonement spell, a quest) restores them.
"""
from ethereal_dnd.core.events import ClassPowersRestored, EventBus


class NotFallenError(ValueError):
    """restore_class_powers() was called for a class this character
    isn't actually fallen from - almost certainly a caller bug (e.g.
    granting atonement twice), not a state worth silently accepting."""


def restore_class_powers(character, class_id: str, events: EventBus) -> None:
    """Explicitly restore a class's powers after an in-world atonement
    action (the caller is responsible for actually gating this on that -
    a completed atonement ritual, a quest flag - this function only does
    the state mutation once that's already decided)."""
    standing = character.divine_standing
    if class_id not in standing.powers_revoked and class_id not in standing.advancement_blocked_for:
        raise NotFallenError(f"{character.name or character.id} is not fallen for {class_id!r}")

    if class_id in standing.powers_revoked:
        standing.powers_revoked.remove(class_id)
    if class_id in standing.advancement_blocked_for:
        standing.advancement_blocked_for.remove(class_id)
    if not standing.powers_revoked and not standing.advancement_blocked_for:
        standing.fallen = False
        standing.fallen_reason = None
        standing.fallen_at = None

    events.emit(ClassPowersRestored(character_id=character.id, class_id=class_id, via="atonement"))
