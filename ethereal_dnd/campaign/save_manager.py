"""Save/load (design doc Section 44): the whole Campaign object graph to
`saves/<campaign_id>/campaign.json`. Serializing is one line -
`dataclasses.asdict()` recurses through every nested dataclass, list, and
dict automatically, whatever the nesting depth - but there's no stdlib
inverse, so loading needs an explicit reconstruction function per
dataclass that has a *dataclass-typed* field (a flat dataclass can just
go through core/serialization.py's generic from_dict()).

Known limitation, inherited from campaign/campaign.py's own design (see
its __post_init__ comment): the campaign's RNG stream is *not* persisted,
only its `random_seed` - loading a save re-seeds a fresh RNGService from
that same seed, so the sequence of future rolls restarts from the
beginning of that seed rather than continuing from wherever the live
session's stream had gotten to. This makes "save, roll some dice, load,
roll again" reproduce the *original* post-load rolls, not a continuation
- an accepted simplification, not an oversight, but a real one worth
knowing about before relying on this for anything roll-sensitive right
after a load.
"""
import dataclasses
import json
import os

from ethereal_dnd.campaign.campaign import Campaign
from ethereal_dnd.campaign.campaign_state import CampaignState
from ethereal_dnd.characters.alignment import AlignmentVector
from ethereal_dnd.characters.character import Character
from ethereal_dnd.characters.class_level import ClassLevel
from ethereal_dnd.characters.party import Party
from ethereal_dnd.core.time import CampaignTime
from ethereal_dnd.divine.standing import CharacterDivineStanding
from ethereal_dnd.items.inventory import Inventory
from ethereal_dnd.items.item import ItemInstance
from ethereal_dnd.quests.quest import Quest
from ethereal_dnd.world.location import Location
from ethereal_dnd.world.npc import NPC
from ethereal_dnd.world.route import Route
from ethereal_dnd.world.world import World

_SAVES_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "saves")


def _campaign_time_from_dict(data: dict | None) -> CampaignTime | None:
    return CampaignTime(**data) if data is not None else None


def _divine_standing_from_dict(data: dict) -> CharacterDivineStanding:
    data = dict(data)
    data["fallen_at"] = _campaign_time_from_dict(data["fallen_at"])
    return CharacterDivineStanding(**data)


def _character_from_dict(data: dict) -> Character:
    data = dict(data)
    data["alignment"] = AlignmentVector(**data["alignment"])
    data["class_levels"] = [ClassLevel(**cl) for cl in data["class_levels"]]
    data["inventory"] = Inventory(
        items=[ItemInstance(**item) for item in data["inventory"]["items"]],
        gold=data["inventory"]["gold"],
    )
    data["divine_standing"] = _divine_standing_from_dict(data["divine_standing"])
    data["time_of_death"] = _campaign_time_from_dict(data["time_of_death"])
    return Character(**data)


def _npc_from_dict(data: dict) -> NPC:
    data = dict(data)
    data["character"] = _character_from_dict(data["character"])
    return NPC(**data)


def _world_from_dict(data: dict) -> World:
    return World(
        locations={loc_id: Location(**loc) for loc_id, loc in data["locations"].items()},
        routes=[Route(**route) for route in data["routes"]],
        npcs={npc_id: _npc_from_dict(npc) for npc_id, npc in data["npcs"].items()},
    )


def _party_from_dict(data: dict) -> Party:
    return Party(members=[_character_from_dict(member) for member in data["members"]])


def _campaign_state_from_dict(data: dict) -> CampaignState:
    return CampaignState(
        quest_state={quest_id: Quest(**quest) for quest_id, quest in data["quest_state"].items()},
        npc_state=data["npc_state"],
        faction_state=data["faction_state"],
    )


def campaign_to_dict(campaign: Campaign) -> dict:
    return dataclasses.asdict(campaign)


def campaign_from_dict(data: dict) -> Campaign:
    return Campaign(
        id=data["id"],
        name=data["name"],
        world=_world_from_dict(data["world"]),
        party=_party_from_dict(data["party"]),
        current_time=CampaignTime(**data["current_time"]),
        current_location_id=data["current_location_id"],
        state=_campaign_state_from_dict(data["state"]),
        random_seed=data["random_seed"],
        history=list(data.get("history", [])),
    )


def save_campaign(campaign: Campaign, saves_root: str | None = None) -> str:
    """Writes saves/<campaign.id>/campaign.json. Returns the path
    written to."""
    root = saves_root or _SAVES_ROOT
    campaign_dir = os.path.join(root, campaign.id)
    os.makedirs(campaign_dir, exist_ok=True)
    path = os.path.join(campaign_dir, "campaign.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(campaign_to_dict(campaign), f, indent=2)
    return path


def load_campaign(campaign_id: str, saves_root: str | None = None) -> Campaign:
    root = saves_root or _SAVES_ROOT
    path = os.path.join(root, campaign_id, "campaign.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return campaign_from_dict(data)
