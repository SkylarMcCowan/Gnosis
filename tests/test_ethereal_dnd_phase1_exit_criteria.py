"""Phase 1 exit criteria (docs/gnosis_crawler_backlog.md): two characters
can fight a scripted combat encounter to a win/loss via the CLI, with
every roll logged in the Section 54 format, fully deterministic under a
fixed seed.
"""
from ethereal_dnd.cli import debug_cli

FIGHTER_SCORES = {"STR": 16, "DEX": 14, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8}
ROGUE_SCORES = {"STR": 11, "DEX": 15, "CON": 12, "INT": 10, "WIS": 9, "CHA": 8}


def _run_duel(seed):
    campaign = debug_cli.new_campaign(name="Test Duel", seed=seed)
    sky = debug_cli.create_test_character(
        "Sky", "fighter", FIGHTER_SCORES, race_id="human",
        weapon_id="longsword", armor_id="chain_shirt", max_hp=13,
    )
    goblin = debug_cli.create_test_character("Goblin", "rogue", ROGUE_SCORES, max_hp=6)
    transcript = debug_cli.run_scripted_duel(campaign, sky, goblin)
    winner_name = sky.name if sky.status == "alive" else goblin.name
    return transcript, winner_name


def test_scripted_duel_resolves_to_a_win_or_loss():
    transcript, winner_name = _run_duel(seed=123)
    assert "Winner:" in transcript
    assert winner_name in transcript


def test_scripted_duel_logs_every_roll_in_section_54_format():
    transcript, _ = _run_duel(seed=123)
    assert "d20 = " in transcript
    assert "Attack bonus = " in transcript
    assert "Attack total = " in transcript
    assert "RESULT: HIT" in transcript or "RESULT: MISS" in transcript


def test_scripted_duel_is_fully_deterministic_under_a_fixed_seed():
    transcript_a, winner_a = _run_duel(seed=123)
    transcript_b, winner_b = _run_duel(seed=123)
    assert transcript_a == transcript_b
    assert winner_a == winner_b


def test_scripted_duel_differs_under_a_different_seed():
    # Not a strict requirement, but a sanity check that the seed is
    # actually driving outcomes rather than everything being hardcoded.
    transcript_a, _ = _run_duel(seed=123)
    transcript_b, _ = _run_duel(seed=999)
    assert transcript_a != transcript_b
