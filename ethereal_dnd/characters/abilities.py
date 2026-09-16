"""Ability scores (design doc Section 10) - the six abilities, the shared
modifier formula every other system consumes, and the two standard
generation methods.
"""
from ethereal_dnd.core.dice import roll
from ethereal_dnd.core.rng import RNGService

ABILITY_NAMES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")

# The 3.5 DMG's 25-point buy variant (cumulative cost from a base of 8).
# Not part of the core SRD's declared Open Game Content - it isn't in
# docs/srd_reference - so unlike the class/skill/race data elsewhere in
# this sprint, this table is cross-checked against secondary sources
# rather than pulled from our local corpus. Flag for re-verification if
# ever sourced directly (docs/srd_reference/SOURCING_GUIDE.md).
_POINT_BUY_COST = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 6, 15: 8, 16: 10, 17: 13, 18: 16}
DEFAULT_POINT_BUY_BUDGET = 25


def ability_modifier(score: int) -> int:
    return (score - 10) // 2


def roll_ability_scores(rng_service: RNGService) -> dict[str, int]:
    """4d6-drop-lowest (Section 10) - one roll per ability, in order."""
    return {ability: roll("4d6kh3", rng_service=rng_service) for ability in ABILITY_NAMES}


class PointBuyError(ValueError):
    pass


def point_buy_cost(scores: dict[str, int]) -> int:
    """Total point cost of a set of ability scores under the 25-point buy
    variant. Raises PointBuyError for any score outside the buyable 8-18
    range - there's no defined cost above/below that band."""
    total = 0
    for ability, score in scores.items():
        if score not in _POINT_BUY_COST:
            raise PointBuyError(f"{ability}={score} is outside the point-buy range (8-18)")
        total += _POINT_BUY_COST[score]
    return total


def validate_point_buy(scores: dict[str, int], budget: int = DEFAULT_POINT_BUY_BUDGET) -> None:
    """Raises PointBuyError if `scores` costs more than `budget` points."""
    cost = point_buy_cost(scores)
    if cost > budget:
        raise PointBuyError(f"Ability scores cost {cost} points, exceeding the {budget}-point budget")
