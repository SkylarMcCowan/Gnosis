"""Resurrection (design doc Section 23), sourced verbatim from the
*Raise Dead* spell (docs/srd_reference/extra/SpellsP-R.md): eligible if
dead no longer than one day per caster level; the raised character loses
a level (or 2 Constitution if they were only 1st level, and can't be
raised at all if that would drop Constitution to 0 or below); returns
with hit points equal to their (new, post-loss) Hit Dice count, not full
health; costs diamonds worth at least 5,000 gp - a real, large number
from the spell text, not an invented placeholder, so resurrection is
appropriately rare for a low-level party rather than a routine service.
"""
from ethereal_dnd.core.events import CharacterResurrected, EventBus
from ethereal_dnd.core.time import CampaignTime

RAISE_DEAD_MATERIAL_COMPONENT_GP = 5000
DEFAULT_TEMPLE_CASTER_LEVEL = 9  # minimum caster level able to cast a 5th-level spell at all


class ResurrectionError(ValueError):
    pass


def _days_dead(time_of_death: CampaignTime, current_time: CampaignTime) -> float:
    death_minutes = time_of_death.day * 24 * 60 + time_of_death.hour * 60 + time_of_death.minute
    now_minutes = current_time.day * 24 * 60 + current_time.hour * 60 + current_time.minute
    return (now_minutes - death_minutes) / (24 * 60)


def is_eligible(character, current_time: CampaignTime, caster_level: int = DEFAULT_TEMPLE_CASTER_LEVEL) -> bool:
    if character.status != "dead" or character.time_of_death is None:
        return False
    return _days_dead(character.time_of_death, current_time) <= caster_level


def resurrect(
    character,
    party,
    current_time: CampaignTime,
    events: EventBus,
    caster_level: int = DEFAULT_TEMPLE_CASTER_LEVEL,
    cost_gp: int = RAISE_DEAD_MATERIAL_COMPONENT_GP,
) -> None:
    """Raises `character`, deducting `cost_gp` split across the living
    party's gold (raises ResurrectionError, no state changed, if the
    party can't afford it or the timing/Constitution checks fail)."""
    if not is_eligible(character, current_time, caster_level):
        raise ResurrectionError(
            f"{character.name or character.id} has been dead too long to raise "
            f"(caster level {caster_level} allows up to {caster_level} day(s))"
        )

    # The dead character's own gold still counts - it's sitting in their
    # pack, not gone, and only their actions (not their belongings) are
    # unavailable while dead.
    payers = party.members
    available_gold = sum(member.gold for member in payers)
    if available_gold < cost_gp:
        raise ResurrectionError(
            f"The party has {available_gold} gp but raising {character.name or character.id} "
            f"costs {cost_gp} gp in diamonds"
        )

    if character.level <= 1:
        new_con = character.ability_scores.get("CON", 10) - 2
        if new_con <= 0:
            raise ResurrectionError(f"{character.name or character.id}'s Constitution can't survive the ordeal")
        character.ability_scores["CON"] = new_con
    else:
        heaviest = max(character.class_levels, key=lambda class_level: class_level.levels)
        heaviest.levels -= 1

    _deduct_gold(payers, cost_gp)

    character.status = "alive"
    character.damage = max(0, character.max_hp - character.level)  # "hit points equal to its current Hit Dice"
    character.time_of_death = None
    character.location_of_death = None
    events.emit(CharacterResurrected(character_id=character.id))


def _deduct_gold(living_members: list, amount: int) -> None:
    remaining = amount
    for member in living_members:
        taken = min(member.gold, remaining)
        member.gold -= taken
        remaining -= taken
        if remaining <= 0:
            break
