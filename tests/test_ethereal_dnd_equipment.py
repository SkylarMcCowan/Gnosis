"""Tests for Sprint 1.4's encumbrance table (design doc Section 22),
sourced verbatim from docs/srd_reference/extra/CarryingandExploration.md.
"""
import pytest

from ethereal_dnd.items import encumbrance


@pytest.mark.parametrize(
    "strength_score,expected",
    [
        (10, (33, 66, 100)),
        (18, (100, 200, 300)),
        (20, (133, 266, 400)),
        (29, (466, 933, 1400)),
    ],
)
def test_carrying_capacity_matches_sourced_table(strength_score, expected):
    assert encumbrance.carrying_capacity(strength_score) == expected


def test_carrying_capacity_tremendous_strength_extension():
    # STR 39 shares the ones digit of STR 29 (row 466/933/1400), one full
    # "ten points above" step -> x4.
    light, medium, heavy = encumbrance.carrying_capacity(39)
    assert (light, medium, heavy) == (466 * 4, 933 * 4, 1400 * 4)


def test_carrying_capacity_rejects_nonpositive_strength():
    with pytest.raises(ValueError):
        encumbrance.carrying_capacity(0)


@pytest.mark.parametrize(
    "total_weight,expected_category",
    [(30, "light"), (66, "medium"), (100, "heavy"), (101, "overloaded")],
)
def test_load_category_for_strength_10(total_weight, expected_category):
    assert encumbrance.load_category(10, total_weight) == expected_category
