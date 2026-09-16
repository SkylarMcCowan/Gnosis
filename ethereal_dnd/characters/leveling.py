"""Experience and leveling (design doc Section 21). The level->cumulative
XP formula (500 * n * (n-1), reproducing the standard 0/1000/3000/6000/
10000/.../190000 progression for levels 1-20) is the universally-cited
3.5 character advancement table, but - like abilities.py's point-buy
costs - it isn't part of the core SRD's declared Open Game Content
(docs/srd_reference has no "character advancement" chapter), so treat it
the same way: cross-checked against the well-known published values
rather than pulled from our local corpus, and worth re-verifying via
docs/srd_reference/SOURCING_GUIDE.md if a discrepancy ever turns up.
"""
from ethereal_dnd.characters.character import Character
from ethereal_dnd.characters.multiclass import add_class_level
from ethereal_dnd.core.events import CharacterLeveled, EventBus


def xp_required_for_level(level: int) -> int:
    if level < 1:
        raise ValueError(f"Level must be at least 1, got {level}")
    return 500 * level * (level - 1)


def level_for_xp(experience: int) -> int:
    """The highest character level `experience` qualifies for."""
    level = 1
    while experience >= xp_required_for_level(level + 1):
        level += 1
    return level


def award_experience(character: Character, amount: int, class_id: str, events: EventBus) -> None:
    """Award `amount` XP to `character`. If it crosses a level threshold,
    add a level in `class_id` (the caller's choice of which class levels
    up - multiclassing is a player decision, not something this function
    infers) and emit CharacterLeveled once per level gained."""
    level_before = level_for_xp(character.experience)
    character.experience += amount
    level_after = level_for_xp(character.experience)

    for _ in range(level_after - level_before):
        add_class_level(character, class_id)
        events.emit(CharacterLeveled(character_id=character.id, new_level=character.level, class_id=class_id))
