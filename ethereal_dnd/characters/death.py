"""Death (design doc Section 23) - HP dropping to (or below) 0 marks a
Character dead and records when/where. Resurrection eligibility needs
Phase 2's world/quest systems and isn't handled here - death is
permanent until then.
"""
from ethereal_dnd.characters.character import Character
from ethereal_dnd.core.events import CharacterDied, EventBus
from ethereal_dnd.core.time import CampaignTime

DEATH_HP_THRESHOLD = 0


def apply_damage(
    character: Character,
    amount: int,
    campaign_time: CampaignTime,
    events: EventBus,
    location_id: str | None = None,
) -> None:
    """Apply `amount` damage to `character`, killing them (and emitting
    CharacterDied) if it brings current HP to or below the death
    threshold. A no-op death-wise if the character is already dead -
    damage can still be applied to a corpse without re-triggering the
    event."""
    character.damage += amount
    current_hp = character.max_hp - character.damage
    if current_hp <= DEATH_HP_THRESHOLD and character.status == "alive":
        character.die(campaign_time, location_id)
        events.emit(CharacterDied(character_id=character.id, location_id=location_id))
