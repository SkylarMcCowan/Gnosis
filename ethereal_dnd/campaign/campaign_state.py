"""CampaignState (design doc Section 42) - the mutable state buckets that
aren't already owned by World/Party/CampaignTime: quest progress,
NPC-specific runtime data, and faction reputation. Empty containers until
Phase 2 (quests, NPC/faction depth) actually populates them.
"""
import dataclasses


@dataclasses.dataclass
class CampaignState:
    quest_state: dict = dataclasses.field(default_factory=dict)
    npc_state: dict = dataclasses.field(default_factory=dict)
    faction_state: dict = dataclasses.field(default_factory=dict)
