"""Campaign history (design doc Section 45) - an append-only, human-
readable, day/time-stamped log of everything that happens, built from
every event on the campaign's bus (core/events.py's EventBus.subscribe_all()).
No LLM summarization here - Section 45 explicitly defers that to Phase 3;
this raw log is what a future narrative context builder summarizes
instead of passing whole to a model.
"""
from ethereal_dnd.core.events import EventBus

_FORMATTERS = {
    "CharacterCreated": lambda e: f"{e.character_id} was created.",
    "CharacterLeveled": lambda e: f"{e.character_id} reached level {e.new_level} in {e.class_id}.",
    "CharacterDied": lambda e: f"{e.character_id} died" + (f" at {e.location_id}." if e.location_id else "."),
    "CharacterResurrected": lambda e: f"{e.character_id} was returned to life.",
    "ItemPurchased": lambda e: f"{e.character_id} bought {e.item_id} for {e.price} gp.",
    "ItemStolen": lambda e: f"{e.character_id} stole {e.item_id}.",
    "SpellCast": lambda e: f"{e.caster_id} cast {e.spell_id}" + (f" on {e.target_id}." if e.target_id else "."),
    "CombatStarted": lambda e: f"Combat began (encounter {e.encounter_id}).",
    "CombatEnded": lambda e: "Combat ended" + (f", {e.victor} was victorious." if e.victor else "."),
    "QuestStarted": lambda e: f"Quest started: {e.quest_id}.",
    "QuestCompleted": lambda e: f"Quest completed: {e.quest_id}.",
    "QuestFailed": lambda e: f"Quest failed: {e.quest_id} ({e.reason}).",
    "LocationDiscovered": lambda e: f"Discovered {e.location_id}.",
    "NPCKilled": lambda e: f"{e.npc_id} was killed.",
    "FactionChanged": lambda e: f"{e.faction_id} reputation changed by {e.reputation_delta:+d}.",
    "PartyTravelStarted": lambda e: f"The party set out from {e.origin_id} toward {e.destination_id}.",
    "PartyArrived": lambda e: f"The party arrived at {e.location_id}.",
    "RestStarted": lambda e: "The party made camp to rest.",
    "RestCompleted": lambda e: "The party finished resting.",
    "CommittedEvilAct": lambda e: f"{e.character_id} committed an evil act: {e.description}".rstrip(": "),
    "CommittedGoodAct": lambda e: f"{e.character_id} performed a good act: {e.description}".rstrip(": "),
    "BrokeCodeOfConduct": lambda e: f"{e.character_id} grossly violated the {e.class_id} code of conduct.",
    "ClassPowersRevoked": lambda e: f"{e.character_id} lost the use of their {e.class_id} powers: {e.reason}",
    "ClassPowersRestored": lambda e: f"{e.character_id} regained their {e.class_id} powers (via {e.via}).",
}


def format_event(event) -> str:
    formatter = _FORMATTERS.get(event.type)
    return formatter(event) if formatter is not None else f"{event.type} occurred."


def attach_history_log(campaign) -> None:
    def on_any_event(event) -> None:
        timestamp = campaign.current_time
        campaign.history.append(
            f"Day {timestamp.day}, {timestamp.hour:02d}:{timestamp.minute:02d} - {format_event(event)}"
        )

    campaign.events.subscribe_all(on_any_event)
