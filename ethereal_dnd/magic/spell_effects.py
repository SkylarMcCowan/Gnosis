"""Composable spell-effect primitives (design doc Section 20) - many
spells share the same underlying mechanic (a damage roll, a heal, a
numeric buff), so effects compose from these rather than each spell
hardcoding its own resolution logic.
"""
import dataclasses

from ethereal_dnd.core.dice import roll_detailed

# How a scaling value (e.g. "number of missiles") grows with caster
# level, keyed by name so spell data (JSON) can reference a formula
# without embedding a Python callable. Add an entry here whenever a new
# spell needs a new scaling shape - this is the one place that kind of
# rule lives, not scattered per-spell.
INSTANCE_COUNT_FORMULAS = {
    # Magic Missile: 1 missile at 1st level, +1 every two caster levels,
    # capped at 5 (docs/srd_reference/extra/SpellsM-O.md).
    "magic_missile": lambda caster_level: min(5, 1 + (caster_level - 1) // 2),
    "fixed_one": lambda caster_level: 1,
}


@dataclasses.dataclass(frozen=True)
class DamageEffect:
    dice: str
    damage_type: str
    instance_count_formula: str = "fixed_one"

    def apply(self, rng_service, caster_level: int) -> dict:
        count = INSTANCE_COUNT_FORMULAS[self.instance_count_formula](caster_level)
        instances = [roll_detailed(self.dice, rng_service=rng_service) for _ in range(count)]
        total = sum(instance["total"] for instance in instances)
        return {"type": "damage", "damage_type": self.damage_type, "instances": instances, "total": total}


@dataclasses.dataclass(frozen=True)
class HealingEffect:
    dice: str
    per_caster_level_bonus: int = 0
    per_caster_level_cap: int | None = None

    def apply(self, rng_service, caster_level: int) -> dict:
        detail = roll_detailed(self.dice, rng_service=rng_service)
        level_bonus = caster_level * self.per_caster_level_bonus
        if self.per_caster_level_cap is not None:
            level_bonus = min(level_bonus, self.per_caster_level_cap)
        detail["modifier"] += level_bonus
        detail["total"] = sum(detail["kept"]) + detail["modifier"]
        return {"type": "healing", "detail": detail, "total": detail["total"]}


@dataclasses.dataclass(frozen=True)
class BuffEffect:
    bonus: int
    bonus_type: str
    applies_to: list  # e.g. ["attack_rolls", "fear_saves"]
    duration_rounds_per_level: int | None = None

    def apply(self, caster_level: int) -> dict:
        duration = (
            self.duration_rounds_per_level * caster_level
            if self.duration_rounds_per_level is not None
            else None
        )
        return {
            "type": "buff", "bonus": self.bonus, "bonus_type": self.bonus_type,
            "applies_to": self.applies_to, "duration_rounds": duration,
        }


@dataclasses.dataclass(frozen=True)
class ConditionEffect:
    condition_id: str
    duration_rounds: int | None = None

    def apply(self) -> dict:
        return {"type": "condition", "condition_id": self.condition_id, "duration_rounds": self.duration_rounds}


@dataclasses.dataclass(frozen=True)
class UtilityEffect:
    """Catch-all for spells with no numeric mechanical output (Detect
    Magic and similar divination/utility spells). Not one of Section
    20's four named examples - added because the starting spell list
    includes exactly this kind of spell and it doesn't fit
    Damage/Healing/Buff/Condition."""
    description: str

    def apply(self) -> dict:
        return {"type": "utility", "description": self.description}


_EFFECT_CLASSES = {
    "damage": DamageEffect,
    "healing": HealingEffect,
    "buff": BuffEffect,
    "condition": ConditionEffect,
    "utility": UtilityEffect,
}


def build_effect(effect_type: str, params: dict):
    """Construct the right Effect primitive from a SpellDefinition's
    effect_type/effect_params (as loaded from data/spells/*.json)."""
    try:
        effect_class = _EFFECT_CLASSES[effect_type]
    except KeyError:
        raise ValueError(f"Unknown spell effect type: {effect_type!r}") from None
    return effect_class(**params)
