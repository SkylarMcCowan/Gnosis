"""Tests for Sprint 2.2/2.3: travel (real time cost, discovery) and
random encounters (weighted, non-combat outcomes included).
"""
import pytest

from ethereal_dnd.cli import debug_cli
from ethereal_dnd.encounters.encounter_tables import eligible_entries
from ethereal_dnd.encounters.monster_factory import spawn_monster
from ethereal_dnd.encounters.random_encounters import roll_encounter
from ethereal_dnd.world.travel import NoRouteError, find_route, travel


def _campaign(seed=1):
    return debug_cli.new_ravenhollow_campaign(seed=seed)


def test_travel_advances_time_by_the_routes_travel_time():
    campaign = _campaign()
    assert (campaign.current_time.hour, campaign.current_time.minute) == (6, 0)
    travel(campaign, "farmstead")  # farmstead route is 1.5 hours
    assert (campaign.current_time.hour, campaign.current_time.minute) == (7, 30)


def test_travel_updates_current_location():
    campaign = _campaign()
    travel(campaign, "blackwood")
    assert campaign.current_location_id == "blackwood"


def test_travel_discovers_the_destination_once():
    campaign = _campaign()
    assert campaign.world.locations["blackwood"].discovered is False
    result = travel(campaign, "blackwood")
    assert campaign.world.locations["blackwood"].discovered is True
    assert "Discovered" in result["log"]

    campaign.current_location_id = "ravenhollow"
    result_again = travel(campaign, "blackwood")
    assert "Discovered" not in result_again["log"]


def test_find_route_raises_for_a_nonexistent_route():
    campaign = _campaign()
    with pytest.raises(NoRouteError):
        find_route(campaign.world, "blackwood", "farmstead")


def test_travel_result_shape():
    campaign = _campaign()
    result = travel(campaign, "abandoned_mine")
    assert "log" in result and "encounter" in result
    if result["encounter"] is not None:
        assert result["encounter"]["type"] in ("combat", "traveler", "discovery")


def test_encounter_tables_exist_for_every_terrain_used_by_a_route():
    campaign = _campaign()
    for route in campaign.world.routes:
        entries = eligible_entries(route.terrain, route.danger_level)
        assert entries, f"no eligible encounter entries for terrain {route.terrain!r}"


def test_roll_encounter_is_deterministic_under_a_fixed_seed():
    campaign_a = _campaign(seed=42)
    campaign_b = _campaign(seed=42)
    route_a = campaign_a.world.routes_from("ravenhollow")[0]
    route_b = campaign_b.world.routes_from("ravenhollow")[0]
    result_a = roll_encounter(route_a, campaign_a.rng())
    result_b = roll_encounter(route_b, campaign_b.rng())
    assert result_a == result_b


def test_plains_route_never_rolls_combat():
    campaign = _campaign()
    route = next(r for r in campaign.world.routes if r.terrain == "plains")
    for seed in range(50):
        outcome = roll_encounter(route, debug_cli.new_campaign(seed=seed).rng())
        assert outcome is None or outcome["type"] != "combat"


def test_combat_encounter_spawns_real_fightable_monsters():
    campaign = _campaign()
    forest_route = next(r for r in campaign.world.routes if r.terrain == "forest")
    for seed in range(50):
        outcome = roll_encounter(forest_route, debug_cli.new_campaign(seed=seed).rng())
        if outcome and outcome["type"] == "combat":
            assert outcome["monsters"]
            for monster in outcome["monsters"]:
                assert monster.armor_class() >= 10
                assert monster.max_hp > 0
            return
    pytest.fail("never rolled a combat encounter in 50 seeds - table weighting may be broken")


def test_spawn_monster_wolf_matches_sourced_stat_block():
    wolf = spawn_monster("wolf")
    assert wolf.armor_class() == 14
    assert wolf.base_attack_bonus() == 1
    assert (wolf.fortitude_save(), wolf.reflex_save(), wolf.will_save()) == (5, 5, 1)
    assert wolf.max_hp == 13
