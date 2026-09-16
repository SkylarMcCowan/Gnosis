"""Tests for ethereal_dnd's Phase 0 core infra (dice, registry,
serialization, time) - ticket GC-022. Pure Python, no Qt.
"""
import dataclasses

import pytest

from ethereal_dnd.core import dice, registry, rng, serialization, time as campaign_time


def test_dice_roll_is_deterministic_under_a_fixed_seed():
    rolls_a = [dice.roll("1d20+3", rng_service=rng.seeded(1234)) for _ in range(20)]
    rolls_b = [dice.roll("1d20+3", rng_service=rng.seeded(1234)) for _ in range(20)]
    assert rolls_a[0] == rolls_b[0]


def test_dice_roll_replays_identically_from_the_same_service_instance():
    service_a = rng.seeded(99)
    service_b = rng.seeded(99)
    sequence_a = [dice.roll("1d20", rng_service=service_a) for _ in range(10)]
    sequence_b = [dice.roll("1d20", rng_service=service_b) for _ in range(10)]
    assert sequence_a == sequence_b


def test_dice_roll_applies_modifier():
    assert dice.roll("1d1+5", rng_service=rng.seeded(1)) == 6  # 1d1 always rolls 1


def test_dice_roll_keep_highest_stays_in_range():
    result = dice.roll("4d6kh3", rng_service=rng.seeded(1))
    assert 3 <= result <= 18


def test_dice_roll_detailed_reports_rolls_and_total():
    detail = dice.roll_detailed("2d6+1", rng_service=rng.seeded(1))
    assert len(detail["rolls"]) == 2
    assert detail["total"] == sum(detail["kept"]) + detail["modifier"]
    assert detail["modifier"] == 1


def test_dice_roll_rejects_invalid_expression():
    with pytest.raises(dice.DiceExpressionError):
        dice.roll("not a dice expression")


def test_registry_register_get_and_all():
    reg = registry.Registry("widget")
    reg.register("a", {"name": "Widget A"})
    reg.register("b", {"name": "Widget B"})
    assert reg.get("a") == {"name": "Widget A"}
    assert len(reg.all()) == 2
    assert "a" in reg
    assert len(reg) == 2


def test_registry_rejects_duplicate_registration():
    reg = registry.Registry("widget")
    reg.register("a", object())
    with pytest.raises(registry.DuplicateRegistrationError):
        reg.register("a", object())


def test_registry_get_missing_raises_key_error():
    reg = registry.Registry("widget")
    with pytest.raises(KeyError):
        reg.get("missing")


@dataclasses.dataclass
class _Sample:
    name: str
    value: int = 0


def test_serialization_round_trip():
    original = _Sample(name="test", value=42)
    restored = serialization.from_dict(_Sample, serialization.to_dict(original))
    assert restored == original


def test_serialization_rejects_unknown_fields():
    with pytest.raises(ValueError):
        serialization.from_dict(_Sample, {"name": "x", "bogus": 1})


def test_serialization_requires_a_dataclass_instance():
    with pytest.raises(TypeError):
        serialization.to_dict({"not": "a dataclass"})


def test_campaign_time_advance_rolls_over_hours_and_days():
    campaign_clock = campaign_time.CampaignTime(day=1, hour=23, minute=45)
    campaign_clock.advance(minutes=30)
    assert (campaign_clock.day, campaign_clock.hour, campaign_clock.minute) == (2, 0, 15)


def test_campaign_time_advance_accepts_fractional_hours():
    campaign_clock = campaign_time.CampaignTime(day=1, hour=6, minute=0)
    campaign_clock.advance(hours=1.5)
    assert (campaign_clock.hour, campaign_clock.minute) == (7, 30)


@pytest.mark.parametrize(
    "hour,expected_period",
    [(2, "Midnight"), (6, "Dawn"), (9, "Morning"), (14, "Afternoon"), (18, "Evening"), (22, "Night")],
)
def test_campaign_time_period_boundaries(hour, expected_period):
    assert campaign_time.CampaignTime(hour=hour).period == expected_period
