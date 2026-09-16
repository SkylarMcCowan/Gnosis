"""Conditions (design doc Section 19), sourced verbatim from
docs/srd_reference/core/AbilitiesandConditions.md. A composable model
instead of scattering `if character.is_stunned` checks everywhere -
Character.conditions stays a plain list of condition ids, and this
module holds what each one actually does.
"""
import dataclasses


@dataclasses.dataclass(frozen=True)
class ConditionEffect:
    id: str
    # Flat penalty to attack rolls, saves, skill checks, and ability
    # checks alike - Shaken and Frightened both use this same "-2 to
    # everything" shape per the sourced text.
    all_rolls_penalty: int = 0
    ac_penalty: int = 0
    loses_dex_to_ac: bool = False
    can_act: bool = True
    must_flee: bool = False


CONDITIONS = {
    "shaken": ConditionEffect(id="shaken", all_rolls_penalty=-2),
    "frightened": ConditionEffect(id="frightened", all_rolls_penalty=-2, must_flee=True),
    "stunned": ConditionEffect(id="stunned", ac_penalty=-2, loses_dex_to_ac=True, can_act=False),
    "unconscious": ConditionEffect(id="unconscious", can_act=False),
    # Prone's effects are directional (attacker vs. defender, melee vs.
    # ranged) so it doesn't fit this flat shape - see the dedicated
    # prone_*() functions below instead. It's still a real entry here so
    # add_condition()/remove_condition()/has_condition() work on it too.
    "prone": ConditionEffect(id="prone"),
}


def has_condition(character, condition_id: str) -> bool:
    return condition_id in character.conditions


def add_condition(character, condition_id: str) -> None:
    if condition_id not in CONDITIONS:
        raise ValueError(f"Unknown condition: {condition_id!r}")
    if condition_id not in character.conditions:
        character.conditions.append(condition_id)


def remove_condition(character, condition_id: str) -> None:
    if condition_id in character.conditions:
        character.conditions.remove(condition_id)


def all_rolls_penalty(character) -> int:
    """Sum of every active condition's flat penalty to attack rolls,
    saves, skill checks, and ability checks. Conditions stack per the
    SRD unless stated otherwise; Phase 1 doesn't yet model the small
    number of conditions that explicitly don't stack with each other."""
    return sum(CONDITIONS[c].all_rolls_penalty for c in character.conditions if c in CONDITIONS)


def ac_penalty(character) -> int:
    return sum(CONDITIONS[c].ac_penalty for c in character.conditions if c in CONDITIONS)


def loses_dex_to_ac(character) -> bool:
    return any(CONDITIONS[c].loses_dex_to_ac for c in character.conditions if c in CONDITIONS)


def can_act(character) -> bool:
    return all(CONDITIONS[c].can_act for c in character.conditions if c in CONDITIONS)


# Prone: "An attacker who is prone has a -4 penalty on melee attack
# rolls and cannot use a ranged weapon (except for a crossbow). A
# defender who is prone gains a +4 bonus to Armor Class against ranged
# attacks, but takes a -4 penalty to AC against melee attacks."
PRONE_ATTACKER_MELEE_PENALTY = -4
PRONE_DEFENDER_MELEE_AC_PENALTY = -4
PRONE_DEFENDER_RANGED_AC_BONUS = 4


def prone_attack_roll_modifier(attacker) -> int:
    return PRONE_ATTACKER_MELEE_PENALTY if has_condition(attacker, "prone") else 0


def prone_ac_modifier(defender, attack_is_ranged: bool) -> int:
    if not has_condition(defender, "prone"):
        return 0
    return PRONE_DEFENDER_RANGED_AC_BONUS if attack_is_ranged else PRONE_DEFENDER_MELEE_AC_PENALTY
