"""Tests for ethereal_dnd's ability score math and generation methods
(Sprint 1.1, ticket GC-023).
"""
import pytest

from ethereal_dnd.characters import abilities
from ethereal_dnd.core.rng import RNGService


@pytest.mark.parametrize(
    "score,expected_modifier",
    [(1, -5), (8, -1), (9, -1), (10, 0), (11, 0), (12, 1), (18, 4), (20, 5)],
)
def test_ability_modifier(score, expected_modifier):
    assert abilities.ability_modifier(score) == expected_modifier


def test_roll_ability_scores_is_deterministic_and_in_range():
    scores_a = abilities.roll_ability_scores(RNGService(1))
    scores_b = abilities.roll_ability_scores(RNGService(1))
    assert scores_a == scores_b
    assert set(scores_a) == set(abilities.ABILITY_NAMES)
    assert all(3 <= score <= 18 for score in scores_a.values())


def test_point_buy_cost_matches_known_totals():
    # All 8s costs nothing; the standard array should cost the standard budget.
    assert abilities.point_buy_cost({"STR": 8, "DEX": 8}) == 0
    assert abilities.point_buy_cost({"STR": 18}) == 16
    assert abilities.point_buy_cost({"STR": 15, "DEX": 14, "CON": 13, "INT": 12, "WIS": 10, "CHA": 8}) == 25


def test_point_buy_cost_rejects_out_of_range_score():
    with pytest.raises(abilities.PointBuyError):
        abilities.point_buy_cost({"STR": 19})


def test_validate_point_buy_raises_over_budget():
    with pytest.raises(abilities.PointBuyError):
        abilities.validate_point_buy({"STR": 18, "DEX": 18}, budget=25)


def test_validate_point_buy_accepts_within_budget():
    abilities.validate_point_buy({"STR": 15, "DEX": 14, "CON": 13, "INT": 12, "WIS": 10, "CHA": 8})
