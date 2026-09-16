"""Rest (design doc Section 24), sourced verbatim from
docs/srd_reference/core/CombatI.md's "Healing" section: "with a full
night's rest (8 hours of sleep or more), you recover 1 hit point per
character level," doubled for a full day-and-night of complete bed rest.

The random-encounter/NPC-movement hooks Section 24 mentions are
deliberately empty here - Phase 2's world/quest systems fill them in
once they exist to hook into.
"""
from ethereal_dnd.core.events import EventBus, RestCompleted, RestStarted
from ethereal_dnd.core.time import CampaignTime

FULL_NIGHT_HOURS = 8
COMPLETE_BED_REST_HOURS = 24

# Called after every rest completes, in registration order, with the
# resting party's members - Phase 2 hooks random encounters, NPC
# movement, etc. onto this instead of this module knowing about them.
post_rest_hooks: list = []


def rest(party, campaign_time: CampaignTime, events: EventBus, complete_bed_rest: bool = False, location_id: str | None = None) -> None:
    events.emit(RestStarted(location_id=location_id))

    hp_per_level = 2 if complete_bed_rest else 1
    hours = COMPLETE_BED_REST_HOURS if complete_bed_rest else FULL_NIGHT_HOURS
    for character in party.living_members():
        character.damage = max(0, character.damage - hp_per_level * character.level)
        # Every Phase 1 condition (shaken/frightened/stunned/unconscious/
        # prone) is round-scoped in real play and would already have
        # ended long before an 8-hour rest finishes - clearing them here
        # is a stand-in for tracking each one's actual duration, which
        # needs the round/duration-tracking a later ticket adds.
        character.conditions.clear()

    campaign_time.advance(hours=hours)
    events.emit(RestCompleted(location_id=location_id))

    for hook in post_rest_hooks:
        hook(party, campaign_time)
