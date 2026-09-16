"""Behavior-vector update hooks (design doc Section 39; alignment doc
§3-4): CommittedGoodAct/CommittedEvilAct events nudge a character's
AlignmentVector.good_evil axis. This is the "player action -> alignment
moves" half of the pipeline; docs/gnosis_crawler_alignment.md §4's
ComplianceEvaluator (ethereal_dnd/divine/) is the "does the new alignment
violate a contract" half, and must run *after* this on the same events -
see divine/setup.py for the subscription ordering that guarantees that.
"""
from ethereal_dnd.characters.party import Party
from ethereal_dnd.core.events import CommittedEvilAct, CommittedGoodAct, EventBus

# Alignment axes are bounded to +/-100 (design doc Section 39) - a
# single act shouldn't be able to overshoot that range regardless of
# accumulated magnitude.
AXIS_MIN = -100.0
AXIS_MAX = 100.0


def _find_member(party: Party, character_id: str):
    for member in party.members:
        if member.id == character_id:
            return member
    raise KeyError(f"No party member with id {character_id!r}")


def _clamp(value: float) -> float:
    return max(AXIS_MIN, min(AXIS_MAX, value))


def attach_alignment_tracker(events: EventBus, party: Party) -> None:
    """Subscribe good_evil-axis updates to `events` for every character
    currently in `party`. Party membership is captured by reference (via
    `_find_member` looking the character up by id each time), so members
    added to the party later are still tracked."""

    def on_evil_act(event: CommittedEvilAct) -> None:
        character = _find_member(party, event.character_id)
        character.alignment.good_evil = _clamp(character.alignment.good_evil - event.magnitude)

    def on_good_act(event: CommittedGoodAct) -> None:
        character = _find_member(party, event.character_id)
        character.alignment.good_evil = _clamp(character.alignment.good_evil + event.magnitude)

    events.subscribe("CommittedEvilAct", on_evil_act)
    events.subscribe("CommittedGoodAct", on_good_act)
