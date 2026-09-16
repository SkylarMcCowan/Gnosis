"""Minimal synchronous event bus (design doc Section 35) - every
meaningful happening in the engine (a level-up, a death, a quest
completion, a fall from grace) is emitted as an Event so quests,
history, and the alignment/deity compliance engine (Phase 1.5) can react
without being wired directly into whatever triggered the event.
"""
import dataclasses


@dataclasses.dataclass
class Event:
    """Base class for every event type. Concrete events add their own
    fields; `type` is derived from the class name so subscribers can
    match on a string without importing every event class."""

    @property
    def type(self) -> str:
        return type(self).__name__


# --- Character events ---------------------------------------------------
@dataclasses.dataclass
class CharacterCreated(Event):
    character_id: str


@dataclasses.dataclass
class CharacterLeveled(Event):
    character_id: str
    new_level: int
    class_id: str


@dataclasses.dataclass
class CharacterDied(Event):
    character_id: str
    location_id: str | None = None


@dataclasses.dataclass
class CharacterResurrected(Event):
    character_id: str


# --- Item/economy events -------------------------------------------------
@dataclasses.dataclass
class ItemPurchased(Event):
    character_id: str
    item_id: str
    price: int


@dataclasses.dataclass
class ItemStolen(Event):
    character_id: str
    item_id: str
    victim_id: str | None = None


# --- Magic/combat events --------------------------------------------------
@dataclasses.dataclass
class SpellCast(Event):
    caster_id: str
    spell_id: str
    target_id: str | None = None


@dataclasses.dataclass
class CombatStarted(Event):
    encounter_id: str


@dataclasses.dataclass
class CombatEnded(Event):
    encounter_id: str
    victor: str | None = None


# --- Quest events ----------------------------------------------------------
@dataclasses.dataclass
class QuestStarted(Event):
    quest_id: str


@dataclasses.dataclass
class QuestCompleted(Event):
    quest_id: str


@dataclasses.dataclass
class QuestFailed(Event):
    quest_id: str
    reason: str | None = None


# --- World events ------------------------------------------------------------
@dataclasses.dataclass
class LocationDiscovered(Event):
    location_id: str


@dataclasses.dataclass
class NPCKilled(Event):
    npc_id: str
    killer_id: str | None = None


@dataclasses.dataclass
class FactionChanged(Event):
    faction_id: str
    reputation_delta: int


@dataclasses.dataclass
class PartyTravelStarted(Event):
    origin_id: str
    destination_id: str


@dataclasses.dataclass
class PartyArrived(Event):
    location_id: str


@dataclasses.dataclass
class RestStarted(Event):
    location_id: str | None = None


@dataclasses.dataclass
class RestCompleted(Event):
    location_id: str | None = None


# --- Alignment/deity events (Phase 1.5, gnosis_crawler_alignment.md) --------
@dataclasses.dataclass
class CommittedEvilAct(Event):
    """Nudges good_evil down (characters/alignment_tracker.py) and is
    itself an event_pattern trigger for the paladin's "willfully commits
    an evil act" clause - a single evil act can fall a paladin instantly,
    independent of whether their alignment vector has drifted out of the
    LG band yet."""
    character_id: str
    magnitude: int = 10
    description: str = ""


@dataclasses.dataclass
class CommittedGoodAct(Event):
    """Nudges good_evil up - the mirror of CommittedEvilAct, and what
    lets an evil-deity follower's alignment actually drift toward "doing
    good" over time (the scenario that prompted this whole subsystem)."""
    character_id: str
    magnitude: int = 10
    description: str = ""


@dataclasses.dataclass
class BrokeCodeOfConduct(Event):
    """A gross violation of a specific class's code of conduct (Section
    12's "grossly violates the code of conduct" clause for Paladin/
    Cleric/Druid) - distinct from alignment drift, and checked reactively
    against that one class's rules rather than the continuous
    alignment_deviation check."""
    character_id: str
    class_id: str
    description: str = ""


@dataclasses.dataclass
class ClassPowersRevoked(Event):
    character_id: str
    class_id: str
    reason: str


@dataclasses.dataclass
class ClassPowersRestored(Event):
    character_id: str
    class_id: str
    via: str = ""  # "atonement" | "realignment"


class EventBus:
    """Synchronous publish/subscribe. Handlers run inline, in
    registration order, on emit() - there is no async dispatch or
    queueing in this minimal implementation."""

    def __init__(self):
        self._subscribers: dict[str, list] = {}
        self._wildcard_subscribers: list = []

    def subscribe(self, event_type: str, handler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler) -> None:
        """`handler` runs on every event, of any type - for things that
        care about the whole stream (campaign/history.py's append-only
        log) rather than one specific type. Runs after any type-specific
        subscribers for the same emit() call, in registration order
        among other wildcard subscribers."""
        self._wildcard_subscribers.append(handler)

    def emit(self, event: Event) -> None:
        for handler in self._subscribers.get(event.type, []):
            handler(event)
        for handler in self._wildcard_subscribers:
            handler(event)
