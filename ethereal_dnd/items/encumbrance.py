"""Carrying capacity and encumbrance (design doc Section 22), sourced
verbatim from docs/srd_reference/extra/CarryingandExploration.md's
"Table: Carrying Capacity" for Strength scores 1-29. Above 29, that same
table documents a "Tremendous Strength" extension: find the score
20-29 sharing the target's ones digit, then multiply that row by 4 for
every ten points the target's Strength is above it.
"""

# STR score -> (light_max_lb, medium_max_lb, heavy_max_lb)
_CARRYING_CAPACITY = {
    1: (3, 6, 10), 2: (6, 13, 20), 3: (10, 20, 30), 4: (13, 26, 40),
    5: (16, 33, 50), 6: (20, 40, 60), 7: (23, 46, 70), 8: (26, 53, 80),
    9: (30, 60, 90), 10: (33, 66, 100), 11: (38, 76, 115), 12: (43, 86, 130),
    13: (50, 100, 150), 14: (58, 116, 175), 15: (66, 133, 200), 16: (76, 153, 230),
    17: (86, 173, 260), 18: (100, 200, 300), 19: (116, 233, 350), 20: (133, 266, 400),
    21: (153, 306, 460), 22: (173, 346, 520), 23: (200, 400, 600), 24: (233, 466, 700),
    25: (266, 533, 800), 26: (306, 613, 920), 27: (346, 693, 1040), 28: (400, 800, 1200),
    29: (466, 933, 1400),
}


def carrying_capacity(strength_score: int) -> tuple[float, float, float]:
    """(light_max, medium_max, heavy_max) load in pounds for a Medium
    biped of this Strength score."""
    if strength_score in _CARRYING_CAPACITY:
        return _CARRYING_CAPACITY[strength_score]
    if strength_score < 1:
        raise ValueError(f"Strength score must be at least 1, got {strength_score}")

    # Tremendous Strength (scores above 29): the reference row is
    # whichever of 20-29 shares the target's ones digit, then the row's
    # values are multiplied by 4 for every ten points above that row.
    ones_digit = strength_score % 10
    reference_score = 20 + ones_digit
    tens_above = (strength_score - reference_score) // 10
    light, medium, heavy = _CARRYING_CAPACITY[reference_score]
    multiplier = 4 ** tens_above
    return (light * multiplier, medium * multiplier, heavy * multiplier)


def load_category(strength_score: int, total_weight: float) -> str:
    """"light" | "medium" | "heavy" | "overloaded" for `total_weight`
    pounds of gear carried by a character with `strength_score`."""
    light_max, medium_max, heavy_max = carrying_capacity(strength_score)
    if total_weight <= light_max:
        return "light"
    if total_weight <= medium_max:
        return "medium"
    if total_weight <= heavy_max:
        return "heavy"
    return "overloaded"
