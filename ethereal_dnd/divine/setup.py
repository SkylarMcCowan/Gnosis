"""Wires the alignment tracker (characters/alignment_tracker.py) and the
compliance evaluator (divine/compliance.py) onto a Campaign's event bus,
in the order that makes "player action -> alignment moves -> contracts
re-checked" actually happen within a single emit() call - EventBus runs
subscribers in registration order, so the tracker (which moves the
AlignmentVector) is registered before anything that reads the *new*
value.
"""
from ethereal_dnd.characters.alignment_tracker import attach_alignment_tracker
from ethereal_dnd.core.events import ClassPowersRestored, ClassPowersRevoked
from ethereal_dnd.divine import compliance


def _find_member(party, character_id: str):
    for member in party.members:
        if member.id == character_id:
            return member
    raise KeyError(f"No party member with id {character_id!r}")


def _emit_changes(events, character, changes: list[dict]) -> None:
    for change in changes:
        if change["kind"] == "violated":
            events.emit(ClassPowersRevoked(
                character_id=character.id, class_id=change["class_id"], reason=change["reason"],
            ))
        else:
            events.emit(ClassPowersRestored(
                character_id=character.id, class_id=change["class_id"], via="realignment",
            ))


def attach_alignment_and_compliance(campaign) -> None:
    """Call once per Campaign (e.g. right after creating it). Subscribes
    both halves of the pipeline to campaign.events, scoped to
    campaign.party."""
    attach_alignment_tracker(campaign.events, campaign.party)

    def on_alignment_moving_event(event_name: str):
        def handler(event) -> None:
            character = _find_member(campaign.party, event.character_id)
            changes = compliance.evaluate_event(character, event_name, campaign_time=campaign.current_time)
            changes += compliance.evaluate_character(character, campaign_time=campaign.current_time)
            _emit_changes(campaign.events, character, changes)
        return handler

    def on_code_of_conduct_broken(event) -> None:
        character = _find_member(campaign.party, event.character_id)
        changes = compliance.evaluate_event(
            character, "BrokeCodeOfConduct", event_class_id=event.class_id, campaign_time=campaign.current_time,
        )
        _emit_changes(campaign.events, character, changes)

    campaign.events.subscribe("CommittedEvilAct", on_alignment_moving_event("CommittedEvilAct"))
    campaign.events.subscribe("CommittedGoodAct", on_alignment_moving_event("CommittedGoodAct"))
    campaign.events.subscribe("BrokeCodeOfConduct", on_code_of_conduct_broken)
