"""Base attack bonus and saving throw progression formulas (design doc
Section 12). These are the standard mechanical formulas behind every
class's BAB/save table (cross-checked against the actual tables sourced
in docs/srd_reference/core/ClassesI.md and ClassesII.md - e.g. Cleric's
"good" Fortitude/Will and "average" BAB columns match these formulas
exactly at every level).
"""

_BAB_PROGRESSION = {
    "good": lambda level: level,
    "average": lambda level: (level * 3) // 4,
    "poor": lambda level: level // 2,
}

_SAVE_PROGRESSION = {
    "good": lambda level: 2 + level // 2,
    "poor": lambda level: level // 3,
}


def base_attack_bonus_for(progression: str, levels: int) -> int:
    try:
        formula = _BAB_PROGRESSION[progression]
    except KeyError:
        raise ValueError(f"Unknown base attack progression: {progression!r}") from None
    return formula(levels)


def save_bonus_for(progression: str, levels: int) -> int:
    try:
        formula = _SAVE_PROGRESSION[progression]
    except KeyError:
        raise ValueError(f"Unknown save progression: {progression!r}") from None
    return formula(levels)
