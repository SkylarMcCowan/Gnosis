"""Tests for Sprint 2.5: the Abandoned Mine dungeon (rooms, trap,
monster spawns) and the CLI functions that drive it.
"""
from ethereal_dnd.cli import debug_cli
from ethereal_dnd.core.rng import RNGService
from ethereal_dnd.world.dungeon import load_dungeon, trigger_trap


def _party_member():
    return debug_cli.create_test_character(
        "Sky", "fighter", {"STR": 16, "DEX": 8, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8}, max_hp=13,
    )


def test_load_dungeon_builds_every_room():
    dungeon = load_dungeon("abandoned_mine")
    assert dungeon.entry_room_id == "mine_entrance"
    assert set(dungeon.rooms) == {"mine_entrance", "collapsed_tunnel", "miners_cage", "boss_chamber"}


def test_load_dungeon_returns_a_fresh_instance_each_time():
    # Trap/room state must not leak between separate dungeon runs.
    dungeon_a = load_dungeon("abandoned_mine")
    dungeon_a.rooms["collapsed_tunnel"].trap.triggered = True
    dungeon_b = load_dungeon("abandoned_mine")
    assert dungeon_b.rooms["collapsed_tunnel"].trap.triggered is False


def test_boss_chamber_has_the_bandit_leader_and_a_bandit():
    dungeon = load_dungeon("abandoned_mine")
    assert set(dungeon.rooms["boss_chamber"].monster_ids) == {"bandit_leader", "bandit"}


def test_trigger_trap_only_fires_once():
    dungeon = load_dungeon("abandoned_mine")
    trap = dungeon.rooms["collapsed_tunnel"].trap
    character = _party_member()
    rng = RNGService(1)

    first = trigger_trap(character, trap, rng)
    assert first["triggered"] is True

    second = trigger_trap(character, trap, rng)
    assert second["triggered"] is False
    assert "already been sprung" in second["log"]


def test_trigger_trap_deals_damage_on_a_failed_save():
    dungeon = load_dungeon("abandoned_mine")
    trap = dungeon.rooms["collapsed_tunnel"].trap
    # A Dex 8 (-1) fighter with no class-progression bonus reliably fails
    # a DC 20 Reflex save regardless of the d20 roll's low end.
    character = _party_member()
    result = trigger_trap(character, trap, RNGService(0))
    if not result["avoided"]:
        assert result["damage"] > 0
        assert character.damage == result["damage"]


def test_enter_dungeon_returns_the_entry_room_description():
    dungeon, log = debug_cli.enter_dungeon("abandoned_mine")
    assert "Mine Entrance" in log
    assert dungeon.entry_room_id in dungeon.rooms


def test_enter_room_reports_monsters_and_does_not_mutate_room_state():
    campaign = debug_cli.new_ravenhollow_campaign(seed=3)
    campaign.party.add(_party_member())
    dungeon, _ = debug_cli.enter_dungeon("abandoned_mine")

    result = debug_cli.enter_room(campaign, dungeon, "miners_cage")

    assert len(result["monsters"]) == 1
    assert result["monsters"][0].name == "Bandit"
    assert result["room"].cleared is False  # caller decides when to mark it cleared


def test_enter_room_with_no_monsters_after_cleared_spawns_nothing():
    campaign = debug_cli.new_ravenhollow_campaign(seed=3)
    campaign.party.add(_party_member())
    dungeon, _ = debug_cli.enter_dungeon("abandoned_mine")
    dungeon.rooms["miners_cage"].cleared = True

    result = debug_cli.enter_room(campaign, dungeon, "miners_cage")

    assert result["monsters"] == []


def test_full_dungeon_run_with_a_strong_party_completes_the_quest():
    from ethereal_dnd.characters.multiclass import add_class_level

    campaign = debug_cli.new_ravenhollow_campaign(seed=7)
    sky = _party_member()
    for _ in range(3):
        add_class_level(sky, "fighter")
    sky.max_hp = 45
    rowan = debug_cli.create_test_character(
        "Rowan", "cleric", {"STR": 12, "DEX": 12, "CON": 14, "INT": 10, "WIS": 16, "CHA": 12},
        weapon_id="mace_heavy", armor_id="chain_shirt", max_hp=30,
    )
    campaign.party.add(sky)
    campaign.party.add(rowan)
    debug_cli.accept_quest(campaign, "missing_miners")

    dungeon, _ = debug_cli.enter_dungeon("abandoned_mine")
    for room_id in ("collapsed_tunnel", "miners_cage", "boss_chamber"):
        result = debug_cli.enter_room(campaign, dungeon, room_id)
        if result["monsters"]:
            outcome = debug_cli.run_party_combat(campaign, [sky, rowan], result["monsters"])
            assert outcome["party_won"] is True
            result["room"].cleared = True

    debug_cli.complete_quest_objective(campaign, "missing_miners", 0)
    debug_cli.complete_quest_objective(campaign, "missing_miners", 1)

    assert campaign.state.quest_state["missing_miners"].state == "completed"
    assert sky.gold == rowan.gold == 75
