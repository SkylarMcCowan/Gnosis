"""Campaign (design doc Section 42) - wires together World, Party,
CampaignTime, a random seed (Section 43 - deterministic RNG for the whole
run), and CampaignState into the one object save/load will eventually
(de)serialize as a whole.
"""
import dataclasses

from ethereal_dnd.campaign.campaign_state import CampaignState
from ethereal_dnd.characters.party import Party
from ethereal_dnd.core.events import EventBus
from ethereal_dnd.core.ids import new_id
from ethereal_dnd.core.rng import RNGService
from ethereal_dnd.core.time import CampaignTime
from ethereal_dnd.world.world import World


@dataclasses.dataclass
class Campaign:
    id: str = dataclasses.field(default_factory=new_id)
    name: str = ""
    world: World = dataclasses.field(default_factory=World)
    party: Party = dataclasses.field(default_factory=Party)
    current_time: CampaignTime = dataclasses.field(default_factory=CampaignTime)
    current_location_id: str | None = None
    state: CampaignState = dataclasses.field(default_factory=CampaignState)
    random_seed: int | None = None
    # Append-only event history (Section 45) - populated by
    # campaign/history.py's attach_history_log(), not by Campaign itself.
    history: list[str] = dataclasses.field(default_factory=list)

    def __post_init__(self):
        # Deliberately not declared dataclass fields (no type annotations
        # above) - to_dict()/asdict() never sees or tries to serialize
        # live RNG/subscriber state this way. Save/load reconstructs the
        # RNG from random_seed alone; the event bus starts fresh (nothing
        # about *subscriptions* is meant to survive a save/load anyway -
        # whatever re-subscribes after loading does so the same way it
        # did on a fresh campaign).
        self._rng = RNGService(self.random_seed)
        self.events = EventBus()

    def rng(self) -> RNGService:
        """The campaign's single seeded RNG stream (Section 43) - every
        roll in this campaign goes through this same instance, so a
        fixed seed reproduces the whole run, not just the first roll."""
        return self._rng
