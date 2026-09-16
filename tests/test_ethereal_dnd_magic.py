"""Tests for Sprint 1.5's spell-effect framework and starting spell list.
"""
import pytest

from ethereal_dnd.characters.class_definition import load_classes
from ethereal_dnd.core.rng import RNGService
from ethereal_dnd.magic import spell_effects
from ethereal_dnd.magic.spell import load_spells, spell_registry
from ethereal_dnd.magic.spell_slots import spells_per_day

load_classes()
load_spells()


@pytest.mark.parametrize(
    "caster_level,expected_missiles",
    [(1, 1), (2, 1), (3, 2), (5, 3), (7, 4), (9, 5), (15, 5)],
)
def test_magic_missile_scales_with_caster_level(caster_level, expected_missiles):
    effect = spell_registry.get("magic_missile").build_effect()
    result = effect.apply(RNGService(1), caster_level=caster_level)
    assert len(result["instances"]) == expected_missiles
    assert result["damage_type"] == "force"


def test_cure_light_wounds_caps_bonus_at_five():
    effect = spell_registry.get("cure_light_wounds").build_effect()
    low_level = effect.apply(RNGService(1), caster_level=2)
    high_level = effect.apply(RNGService(1), caster_level=10)
    assert low_level["detail"]["modifier"] == 2
    assert high_level["detail"]["modifier"] == 5  # capped, not 10


def test_bless_grants_morale_bonus_with_level_scaled_duration():
    effect = spell_registry.get("bless").build_effect()
    result = effect.apply(caster_level=3)
    assert result["bonus"] == 1
    assert result["bonus_type"] == "morale"
    assert "attack_rolls" in result["applies_to"]
    assert result["duration_rounds"] == 30  # 1 min/level = 10 rounds/level * 3


def test_detect_magic_is_a_utility_effect_with_no_numeric_output():
    effect = spell_registry.get("detect_magic").build_effect()
    result = effect.apply()
    assert result["type"] == "utility"
    assert "description" in result


def test_build_effect_rejects_unknown_effect_type():
    with pytest.raises(ValueError):
        spell_effects.build_effect("teleport", {})


def test_cleric_spells_per_day_matches_sourced_table():
    assert spells_per_day("cleric", 1) == [3, 1]
    assert spells_per_day("cleric", 20) == [6, 5, 5, 5, 5, 5, 4, 4, 4, 4]


def test_spells_per_day_rejects_nonspellcasting_class():
    with pytest.raises(ValueError):
        spells_per_day("barbarian", 1)


def test_spells_per_day_rejects_out_of_range_level():
    with pytest.raises(ValueError):
        spells_per_day("wizard", 21)
