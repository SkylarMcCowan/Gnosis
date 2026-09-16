"""Tests for Sprint 2.1/2.2: the Ravenhollow NPC/location/route content
and its loader (world/campaign_content.py).
"""
from ethereal_dnd.cli import debug_cli
from ethereal_dnd.world.campaign_content import load_ashes_of_ravenhollow
from ethereal_dnd.world.npc import build_npc


def _campaign():
    return debug_cli.new_ravenhollow_campaign(seed=1)


def test_load_ashes_of_ravenhollow_populates_locations_routes_and_npcs():
    campaign = _campaign()
    assert set(campaign.world.locations) == {
        "ravenhollow", "blackwood", "old_ruins", "abandoned_mine", "farmstead",
    }
    assert len(campaign.world.routes) == 8
    assert set(campaign.world.npcs) == {
        "mayor_voss", "mabel_innkeeper", "boran_blacksmith", "sister_wren", "tam_trader",
    }


def test_load_is_idempotent():
    campaign = _campaign()
    load_ashes_of_ravenhollow(campaign)
    load_ashes_of_ravenhollow(campaign)
    assert len(campaign.world.locations) == 5
    assert len(campaign.world.npcs) == 5


def test_only_ravenhollow_starts_discovered():
    campaign = _campaign()
    for location_id, location in campaign.world.locations.items():
        assert location.discovered == (location_id == "ravenhollow")


def test_current_location_defaults_to_ravenhollow():
    campaign = _campaign()
    assert campaign.current_location_id == "ravenhollow"


def test_npcs_are_registered_at_their_location():
    campaign = _campaign()
    names = {npc.name for npc in campaign.world.npcs_at("ravenhollow")}
    assert names == {"Mayor Alden Voss", "Old Mabel", "Boran Ironhand", "Sister Wren", "Tam the Trader"}
    ravenhollow = campaign.world.locations["ravenhollow"]
    assert set(ravenhollow.npc_ids) == set(campaign.world.npcs)


def test_every_npc_has_real_combat_stats():
    campaign = _campaign()
    for npc in campaign.world.npcs.values():
        assert npc.character.max_hp > 0
        assert npc.character.armor_class() >= 10
        assert npc.character.level > 0


def test_sister_wren_is_a_cleric_of_aurelia():
    campaign = _campaign()
    wren = campaign.world.npcs["sister_wren"]
    assert wren.character.deity_id == "aurelia"
    assert wren.character.class_levels[0].class_id == "cleric"


def test_rumors_reference_only_real_quest_ids():
    campaign = _campaign()
    valid_quest_ids = {"missing_miners", "wolves_of_blackwood", None}
    for npc in campaign.world.npcs.values():
        for rumor in npc.rumors:
            assert rumor["quest_id"] in valid_quest_ids


def test_build_npc_computes_average_hp_from_class_and_con():
    npc = build_npc(
        npc_id="test_npc", name="Test", role="tester", location_id="ravenhollow",
        npc_class="commoner", npc_level=1, ability_scores={"CON": 14},
    )
    # Commoner hit die 4, CON 14 -> +2 modifier, 1st level max: 4 + 2 = 6
    assert npc.character.max_hp == 6
    assert npc.alive is True
