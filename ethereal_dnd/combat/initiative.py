"""Initiative (design doc Section 17) - roll + deterministic tie-break.
"""
from ethereal_dnd.core.dice import roll


def roll_initiative(participants, rng_service) -> list[str]:
    """`participants`: iterable of Character-like objects exposing `.id`
    and `.initiative()`. Returns participant ids ordered highest total
    first. Ties break first on the initiative *modifier* (not specified
    by the SRD, but "deterministic" is the actual Section 17
    requirement, and this is the standard real-table convention), then
    on id, so the ordering is fully deterministic even when modifiers
    also tie."""
    rolled = []
    for participant in participants:
        modifier = participant.initiative()
        total = roll("1d20", rng_service=rng_service) + modifier
        rolled.append((total, modifier, participant.id))
    rolled.sort(key=lambda entry: (-entry[0], -entry[1], entry[2]))
    return [entry[2] for entry in rolled]
