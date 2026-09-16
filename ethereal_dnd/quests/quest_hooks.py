"""Quest hooks (design doc Section 41) - the two reactions that
genuinely need to be event-driven rather than an explicit call from
gameplay code: an NPC required alive for a quest dying fails it, and a
location being discovered unlocks whatever quest needed that.

"NPC dies" is detected off the generic CharacterDied event (characters/
death.py emits that for every character, PC/NPC/monster alike) by
checking whether the dead character is registered in campaign.world.npcs
- there's no separate NPC-specific death event to subscribe to instead.
"""
from ethereal_dnd.quests.quest_manager import fail_quest, start_quest

_REQUIRE_ALIVE_PREFIX = "npc_alive:"
_REQUIRE_LOCATION_PREFIX = "location_discovered:"


def attach_quest_hooks(campaign) -> None:
    def on_character_died(event) -> None:
        if event.character_id not in campaign.world.npcs:
            return  # a PC or monster death, not an NPC - nothing to check
        requirement = f"{_REQUIRE_ALIVE_PREFIX}{event.character_id}"
        for quest_id, quest in list(campaign.state.quest_state.items()):
            if quest.state == "active" and requirement in quest.requirements:
                fail_quest(campaign, quest_id, f"{event.character_id} died")

    def on_location_discovered(event) -> None:
        requirement = f"{_REQUIRE_LOCATION_PREFIX}{event.location_id}"
        for quest_id, unlock_requirements in list(campaign.state.npc_state.get("locked_quests", {}).items()):
            if requirement in unlock_requirements and quest_id not in campaign.state.quest_state:
                start_quest(campaign, quest_id)

    campaign.events.subscribe("CharacterDied", on_character_died)
    campaign.events.subscribe("LocationDiscovered", on_location_discovered)


def register_locked_quest(campaign, quest_id: str, unlock_requirements: list[str]) -> None:
    """Register `quest_id` to auto-start once every requirement in
    `unlock_requirements` (currently only "location_discovered:<id>" is
    checked - see on_location_discovered() above) is met. Uses
    CampaignState.npc_state as a scratch bucket rather than adding a new
    Campaign-level field just for this - it's exactly the kind of
    "state that isn't already owned by World/Party/CampaignTime" bucket
    Section 42 describes that field for."""
    locked = campaign.state.npc_state.setdefault("locked_quests", {})
    locked[quest_id] = list(unlock_requirements)
