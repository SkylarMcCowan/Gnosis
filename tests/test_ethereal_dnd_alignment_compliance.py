"""Tests for Phase 1.5's alignment & deity compliance engine (ticket
GC-049): the four scenarios the backlog specifies, plus coverage of the
supporting pieces (deity data, the tracker, atonement).
"""
import pytest

from ethereal_dnd.characters.character import Character
from ethereal_dnd.characters.class_definition import class_registry, load_classes
from ethereal_dnd.characters.multiclass import add_class_level
from ethereal_dnd.core.events import CommittedEvilAct, CommittedGoodAct
from ethereal_dnd.core.registry import Registry
from ethereal_dnd.core.time import CampaignTime
from ethereal_dnd.divine import compliance
from ethereal_dnd.divine.atonement import NotFallenError, restore_class_powers
from ethereal_dnd.divine.deity import decode_alignment_code, load_deities
from ethereal_dnd.divine.setup import attach_alignment_and_compliance
from ethereal_dnd.magic.spell_slots import spells_per_day_for
from ethereal_dnd.cli import debug_cli

load_classes()


def _campaign_with(*characters):
    campaign = debug_cli.new_campaign(name="Test", seed=1)
    for character in characters:
        campaign.party.add(character)
    return campaign


def _paladin(**alignment):
    character = Character(
        name="Sky",
        ability_scores={"STR": 16, "DEX": 12, "CON": 14, "INT": 10, "WIS": 12, "CHA": 16},
        max_hp=13,
    )
    add_class_level(character, "paladin")
    character.alignment.law_chaos = alignment.get("law_chaos", 60)
    character.alignment.good_evil = alignment.get("good_evil", 60)
    return character


def _cleric_of(deity_id, **alignment):
    character = Character(
        name="Vex",
        ability_scores={"STR": 10, "DEX": 12, "CON": 12, "INT": 10, "WIS": 16, "CHA": 14},
        max_hp=8,
        deity_id=deity_id,
    )
    add_class_level(character, "cleric")
    character.alignment.law_chaos = alignment.get("law_chaos", 0)
    character.alignment.good_evil = alignment.get("good_evil", 0)
    return character


def _monk(**alignment):
    character = Character(
        name="Zen",
        ability_scores={"STR": 12, "DEX": 16, "CON": 14, "INT": 10, "WIS": 14, "CHA": 8},
        max_hp=8,
    )
    add_class_level(character, "monk")
    character.alignment.law_chaos = alignment.get("law_chaos", 60)
    return character


def _barbarian(**alignment):
    character = Character(
        name="Grond",
        ability_scores={"STR": 18, "DEX": 12, "CON": 16, "INT": 8, "WIS": 10, "CHA": 8},
        max_hp=15,
    )
    add_class_level(character, "barbarian")
    character.alignment.law_chaos = alignment.get("law_chaos", -60)
    return character


# --- (a) LG paladin who commits a scripted evil act loses powers immediately --

def test_paladin_falls_instantly_on_a_willful_evil_act():
    paladin = _paladin()
    campaign = _campaign_with(paladin)
    revoked = []
    campaign.events.subscribe("ClassPowersRevoked", lambda e: revoked.append(e))

    assert paladin.can_use_class_powers("paladin") is True
    campaign.events.emit(CommittedEvilAct(character_id=paladin.id, description="executed a prisoner"))

    assert paladin.divine_standing.fallen is True
    assert paladin.can_use_class_powers("paladin") is False
    assert len(revoked) == 1
    assert revoked[0].class_id == "paladin"


def test_paladin_falls_on_alignment_drift_even_without_a_scripted_event():
    paladin = _paladin()
    campaign = _campaign_with(paladin)

    # Grind good_evil down via ordinary CommittedEvilAct events rather
    # than a single scripted one - the *drift itself* should also cross
    # the exact_alignment("LG") requirement, independent of the
    # paladin's own dedicated CommittedEvilAct rule.
    for _ in range(6):
        campaign.events.emit(CommittedEvilAct(character_id=paladin.id, magnitude=15, description="petty cruelty"))

    assert paladin.alignment.good_evil_label() != "good"
    assert paladin.divine_standing.fallen is True


def test_paladin_keeps_proficiencies_language_in_on_violation_effect():
    paladin = _paladin()
    campaign = _campaign_with(paladin)
    campaign.events.emit(CommittedEvilAct(character_id=paladin.id, description="murder"))
    rules = class_registry.get("paladin").alignment_restriction
    rule = next(r for r in rules if r["id"] == "paladin_willful_evil_act")
    assert set(rule["on_violation"]["keeps"]) == {"weapon_proficiency", "armor_proficiency", "shield_proficiency"}


# --- (b) cleric one step off their deity keeps powers, two steps off loses them ---
#
# Compliance is checked reactively (alignment doc §4: "on every event
# that could move the alignment vector... not on a timer"), so a
# character constructed with a pre-set alignment and simply added to the
# party is never automatically checked - these tests call
# compliance.evaluate_character() directly to simulate "the game just
# decided to check this companion's standing" (e.g. after loading a save
# or recruiting them), the same way the monk/barbarian tests below do.

def test_cleric_one_step_off_deity_keeps_powers():
    load_deities()
    # Aurelia is LG; Neutral Good is one step off (good_evil axis only).
    cleric = _cleric_of("aurelia", law_chaos=0, good_evil=60)
    campaign = _campaign_with(cleric)
    compliance.evaluate_character(cleric, campaign_time=campaign.current_time)
    assert cleric.divine_standing.fallen is False
    assert cleric.can_use_class_powers("cleric") is True


def test_cleric_two_steps_off_deity_loses_powers():
    load_deities()
    # Aurelia is LG; Chaotic Evil deviates on both axes at once.
    cleric = _cleric_of("aurelia", law_chaos=-60, good_evil=-60)
    campaign = _campaign_with(cleric)
    compliance.evaluate_character(cleric, campaign_time=campaign.current_time)
    assert cleric.divine_standing.fallen is True
    assert cleric.can_use_class_powers("cleric") is False


def test_cleric_neutrality_clause_blocks_true_neutral_under_nontrue_neutral_deity():
    load_deities()
    # Aurelia is LG (not neutral) - a True Neutral cleric of hers violates
    # the specific "may not be neutral unless deity is also neutral"
    # clause even though naive one-step-per-axis math wouldn't catch it.
    cleric = _cleric_of("aurelia", law_chaos=0, good_evil=0)
    campaign = _campaign_with(cleric)
    compliance.evaluate_character(cleric, campaign_time=campaign.current_time)
    assert cleric.divine_standing.fallen is True


def test_true_neutral_cleric_of_true_neutral_deity_is_fine():
    load_deities()
    cleric = _cleric_of("sylvanis", law_chaos=0, good_evil=0)  # Sylvanis is N
    campaign = _campaign_with(cleric)
    compliance.evaluate_character(cleric, campaign_time=campaign.current_time)
    assert cleric.divine_standing.fallen is False


def test_the_original_scenario_evil_deity_cleric_drifting_good_loses_power():
    load_deities()
    cleric = _cleric_of("mordrekar", law_chaos=0, good_evil=-60)  # Mordrekar is NE
    campaign = _campaign_with(cleric)
    compliance.evaluate_character(cleric, campaign_time=campaign.current_time)
    assert cleric.divine_standing.fallen is False

    for _ in range(4):
        campaign.events.emit(CommittedGoodAct(character_id=cleric.id, magnitude=15, description="an act of mercy"))

    assert cleric.divine_standing.fallen is True
    assert spells_per_day_for(cleric, "cleric") == [0] * len(spells_per_day_for(cleric, "cleric"))


def test_cleric_without_a_deity_is_never_flagged_by_the_deity_relative_rule():
    cleric = _cleric_of(None, law_chaos=-90, good_evil=-90)
    campaign = _campaign_with(cleric)
    compliance.evaluate_character(cleric, campaign_time=campaign.current_time)
    assert cleric.divine_standing.fallen is False


# --- (c) atonement restores a fallen paladin -----------------------------

def test_atonement_restores_a_fallen_paladin():
    paladin = _paladin()
    campaign = _campaign_with(paladin)
    restored = []
    campaign.events.subscribe("ClassPowersRestored", lambda e: restored.append(e))
    campaign.events.emit(CommittedEvilAct(character_id=paladin.id, description="murder"))
    assert paladin.divine_standing.fallen is True

    restore_class_powers(paladin, "paladin", campaign.events)

    assert paladin.divine_standing.fallen is False
    assert paladin.can_use_class_powers("paladin") is True
    assert len(restored) == 1
    assert restored[0].via == "atonement"


def test_atonement_does_not_undo_itself_via_alignment_drift_alone():
    """Atonement-restoration classes stay revoked until explicitly
    atoned, even if the alignment vector itself drifts back into
    compliance on its own - unlike the realignment path (monk/barbarian)."""
    paladin = _paladin()
    campaign = _campaign_with(paladin)
    campaign.events.emit(CommittedEvilAct(character_id=paladin.id, description="murder"))
    assert paladin.divine_standing.fallen is True

    changes = compliance.evaluate_character(paladin, campaign_time=CampaignTime())
    assert changes == []
    assert paladin.divine_standing.fallen is True


def test_restore_class_powers_raises_if_not_actually_fallen():
    paladin = _paladin()
    campaign = _campaign_with(paladin)
    with pytest.raises(NotFallenError):
        restore_class_powers(paladin, "paladin", campaign.events)


# --- (d) monk who drifts chaotic is capped but not stripped ----------------

def test_monk_drifting_chaotic_is_capped_not_stripped():
    monk = _monk(law_chaos=60)
    campaign = _campaign_with(monk)

    monk.alignment.law_chaos = -60
    changes = compliance.evaluate_character(monk, campaign_time=campaign.current_time)

    assert changes == [{"class_id": "monk", "reason": monk.divine_standing.fallen_reason, "kind": "violated"}]
    assert "monk" in monk.divine_standing.advancement_blocked_for
    assert "monk" not in monk.divine_standing.powers_revoked  # retains all monk abilities
    assert monk.can_use_class_powers("monk") is True  # only advancement is blocked, not usage


def test_monk_realigns_without_atonement():
    monk = _monk(law_chaos=60)
    campaign = _campaign_with(monk)
    monk.alignment.law_chaos = -60
    compliance.evaluate_character(monk, campaign_time=campaign.current_time)
    assert monk.divine_standing.fallen is True

    monk.alignment.law_chaos = 60  # realigns on their own, no ritual
    changes = compliance.evaluate_character(monk, campaign_time=campaign.current_time)

    assert changes[0]["kind"] == "restored"
    assert monk.divine_standing.fallen is False
    assert "monk" not in monk.divine_standing.advancement_blocked_for


def test_barbarian_becoming_lawful_blocks_advancement_but_keeps_listed_abilities():
    barbarian = _barbarian(law_chaos=-60)
    campaign = _campaign_with(barbarian)
    barbarian.alignment.law_chaos = 60  # becomes lawful
    changes = compliance.evaluate_character(barbarian, campaign_time=campaign.current_time)

    assert changes[0]["class_id"] == "barbarian"
    assert "barbarian" in barbarian.divine_standing.advancement_blocked_for
    kept = class_registry.get("barbarian").alignment_restriction[0]["on_violation"]["keeps"]
    assert set(kept) == {"damage_reduction", "fast_movement", "trap_sense", "uncanny_dodge"}


# --- Deity data + decode helper ---------------------------------------------

def test_starting_deities_cover_lg_neutral_and_evil():
    registry = Registry("deity")
    load_deities(target_registry=registry)
    alignments = {deity.alignment for deity in registry.all()}
    assert {"LG", "N", "NE"} <= alignments


def test_decode_alignment_code_handles_true_neutral():
    assert decode_alignment_code("N") == ("neutral", "neutral")
    assert decode_alignment_code("NE") == ("neutral", "evil")


def test_decode_alignment_code_rejects_unknown_code():
    with pytest.raises(ValueError):
        decode_alignment_code("XX")


def test_load_deities_is_idempotent():
    registry = Registry("deity")
    load_deities(target_registry=registry)
    load_deities(target_registry=registry)
    assert len(registry) == 3


# --- Wiring / exit criteria -------------------------------------------------

def test_commit_evil_act_cli_helper_logs_before_and_after():
    paladin = _paladin()
    campaign = _campaign_with(paladin)
    transcript = debug_cli.commit_evil_act(campaign, paladin, description="betrays an ally")
    assert "Before:" in transcript
    assert "After:" in transcript
    assert "Fallen: True" in transcript


def test_double_attaching_compliance_does_not_duplicate_a_revocation():
    # new_campaign() already calls attach_alignment_and_compliance() once,
    # so this re-attaches a second time (subscribing every handler
    # again - EventBus doesn't dedupe subscriptions). The already-fallen
    # guard inside evaluate_event()/evaluate_character() is what actually
    # keeps this safe: the second handler invocation within the same
    # emit() sees the class already in powers_revoked and no-ops.
    paladin = _paladin()
    campaign = _campaign_with(paladin)
    attach_alignment_and_compliance(campaign)  # second attach
    campaign.events.emit(CommittedEvilAct(character_id=paladin.id, description="murder"))
    assert paladin.divine_standing.powers_revoked.count("paladin") == 1
