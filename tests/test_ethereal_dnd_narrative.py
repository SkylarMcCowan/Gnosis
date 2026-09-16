"""Tests for Phase 3's narrative pipeline (intent parser, action
resolver, context builder, narrator, game loop). All model calls are
mocked with a fake chat_fn - fast and deterministic, matching this
repo's existing fake_ollama_chat convention (tests/conftest.py) rather
than depending on a running Ollama instance. Live-verified separately
against the real model (see docs/gnosis_crawler_backlog.md's Phase 3
notes) - that's not something a CI-safe test suite should depend on.
"""
import json

import pytest

from ethereal_dnd.characters.checks import DC_AVERAGE
from ethereal_dnd.cli import debug_cli
from ethereal_dnd.narrative.action_intent import ActionIntent
from ethereal_dnd.narrative.action_resolver import UnresolvableActionError, resolve_action
from ethereal_dnd.narrative.context_builder import build_context
from ethereal_dnd.narrative.game_loop import process_player_input
from ethereal_dnd.narrative.gnosis_narrator import GnosisNarrator
from ethereal_dnd.narrative.intent_parser import parse_intent
from ethereal_dnd.narrative.narrator import NullNarrator


def _campaign_with_fighter():
    campaign = debug_cli.new_ravenhollow_campaign(seed=1)
    sky = debug_cli.create_test_character(
        "Sky", "fighter", {"STR": 16, "DEX": 14, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8},
        weapon_id="longsword", armor_id="chain_shirt", max_hp=13,
    )
    campaign.party.add(sky)
    return campaign, sky


def _json_chat_fn(payload: dict):
    def fn(messages):
        return json.dumps(payload)
    return fn


# --- context_builder ---------------------------------------------------

def test_build_context_reports_location_npcs_and_routes():
    campaign, _ = _campaign_with_fighter()
    context = build_context(campaign)
    assert context["location"]["id"] == "ravenhollow"
    assert {npc["id"] for npc in context["npcs_present"]} == set(campaign.world.npcs)
    assert {route["destination_id"] for route in context["routes"]} == {
        "blackwood", "abandoned_mine", "farmstead",
    }


def test_build_context_includes_only_active_quests():
    campaign, _ = _campaign_with_fighter()
    debug_cli.accept_quest(campaign, "wolves_of_blackwood")
    context = build_context(campaign)
    assert context["active_quests"][0]["id"] == "wolves_of_blackwood"
    assert context["active_quests"][0]["objectives"]


def test_build_context_history_window_is_bounded():
    campaign, _ = _campaign_with_fighter()
    for _ in range(20):
        campaign.history.append("filler entry")
    context = build_context(campaign, history_window=5)
    assert len(context["recent_history"]) == 5


# --- intent_parser -------------------------------------------------------

def test_parse_intent_builds_a_real_action_intent():
    campaign, _ = _campaign_with_fighter()
    context = build_context(campaign)
    chat_fn = _json_chat_fn({
        "action_type": "talk", "target_id": "mabel_innkeeper", "description": "talk to Mabel",
    })
    intent = parse_intent("I talk to Old Mabel", context, chat_fn=chat_fn)
    assert intent.action_type == "talk"
    assert intent.target_id == "mabel_innkeeper"
    assert intent.raw_text == "I talk to Old Mabel"


def test_parse_intent_falls_back_to_unsupported_on_garbage_response():
    campaign, _ = _campaign_with_fighter()
    context = build_context(campaign)
    intent = parse_intent("do something", context, chat_fn=lambda messages: "not json at all")
    assert intent.action_type == "unsupported"


def test_parse_intent_falls_back_to_unsupported_on_unknown_action_type():
    campaign, _ = _campaign_with_fighter()
    context = build_context(campaign)
    chat_fn = _json_chat_fn({"action_type": "fly_to_the_moon"})
    intent = parse_intent("do something wild", context, chat_fn=chat_fn)
    assert intent.action_type == "unsupported"


def test_parse_intent_handles_a_clarify_response_via_agent_dialogue(monkeypatch):
    import agent_dialogue

    calls = {"n": 0}

    def chat_fn(messages):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({"clarify": [{"question": "Which NPC?", "options": ["Mabel"]}]})
        return json.dumps({"action_type": "talk", "target_id": "mabel_innkeeper"})

    monkeypatch.setattr(agent_dialogue, "_ui_asker", lambda questions: {"Which NPC?": "Mabel"})
    campaign, _ = _campaign_with_fighter()
    context = build_context(campaign)

    intent = parse_intent("talk to someone", context, chat_fn=chat_fn)

    assert intent.action_type == "talk"
    assert calls["n"] == 2


# --- action_resolver ---------------------------------------------------

def test_resolve_attack_against_a_real_npc():
    campaign, sky = _campaign_with_fighter()
    npc = campaign.world.npcs["mayor_voss"]
    intent = ActionIntent(action_type="attack", target_id=npc.id)
    result = resolve_action(intent, campaign)
    assert result["resolved"] is True
    assert result["kind"] == "attack"


def test_resolve_attack_against_a_nonexistent_target_is_unresolved():
    campaign, _ = _campaign_with_fighter()
    intent = ActionIntent(action_type="attack", target_id="nobody_here")
    result = resolve_action(intent, campaign)
    assert result["resolved"] is False


def test_resolve_attack_cannot_yet_target_a_random_encounter_monster():
    """GC-073: confirmed via a live continuous playthrough of Section
    65's success list (docs/gnosis_crawler_backlog.md) - "I attack the
    wolf" after a travel roll spawns a combat encounter comes back "no
    one matching None here to attack", because a spawned monster is a
    bare Character living only in the encounter dict
    (encounters/random_encounters.py), never registered into
    campaign.world.npcs. This test locks in *today's* behavior as a
    known gap, not a fix - see GC-073 for what closing it requires."""
    from ethereal_dnd.encounters.monster_factory import spawn_monster

    campaign, _ = _campaign_with_fighter()
    wolf = spawn_monster("wolf")  # a real monster id, just never registered anywhere campaign-visible
    intent = ActionIntent(action_type="attack", target_id=wolf.id)
    result = resolve_action(intent, campaign)
    assert result["resolved"] is False


def test_resolve_skill_check_uses_the_average_dc():
    campaign, sky = _campaign_with_fighter()
    intent = ActionIntent(action_type="skill_check", skill_id="climb")
    result = resolve_action(intent, campaign)
    assert result["resolved"] is True
    assert result["detail"]["dc"] == DC_AVERAGE


def test_resolve_skill_check_handles_untrained_only_skill_gracefully():
    campaign, _ = _campaign_with_fighter()
    intent = ActionIntent(action_type="skill_check", skill_id="spellcraft")  # trained-only, 0 ranks
    result = resolve_action(intent, campaign)
    assert result["resolved"] is False
    assert "cannot attempt" in result["log"]


def test_resolve_talk_returns_real_rumors():
    campaign, _ = _campaign_with_fighter()
    intent = ActionIntent(action_type="talk", target_id="mabel_innkeeper")
    result = resolve_action(intent, campaign)
    assert result["resolved"] is True
    assert "Blackwood" in result["log"]


def test_resolve_talk_to_a_dead_npc():
    from ethereal_dnd.characters import death

    campaign, _ = _campaign_with_fighter()
    npc = campaign.world.npcs["tam_trader"]
    death.apply_damage(npc.character, 9999, campaign.current_time, campaign.events)
    result = resolve_action(ActionIntent(action_type="talk", target_id="tam_trader"), campaign)
    assert result["resolved"] is True
    assert "dead" in result["log"]


def test_resolve_travel_moves_the_party():
    campaign, _ = _campaign_with_fighter()
    result = resolve_action(ActionIntent(action_type="travel", destination_id="farmstead"), campaign)
    assert result["resolved"] is True
    assert campaign.current_location_id == "farmstead"


def test_resolve_travel_with_no_destination_is_unresolved():
    campaign, _ = _campaign_with_fighter()
    result = resolve_action(ActionIntent(action_type="travel"), campaign)
    assert result["resolved"] is False


def test_resolve_rest_heals_the_party():
    campaign, sky = _campaign_with_fighter()
    sky.damage = 10
    resolve_action(ActionIntent(action_type="rest"), campaign)
    assert sky.damage < 10


def test_resolve_cast_spell_applies_a_real_effect():
    campaign, _ = _campaign_with_fighter()
    from ethereal_dnd.characters.multiclass import add_class_level

    wizard = debug_cli.create_test_character(
        "Vex", "wizard", {"STR": 8, "DEX": 12, "CON": 12, "INT": 16, "WIS": 10, "CHA": 10}, max_hp=6,
    )
    campaign.party.members.clear()
    campaign.party.add(wizard)
    result = resolve_action(ActionIntent(action_type="cast_spell", spell_id="magic_missile"), campaign)
    assert result["resolved"] is True
    assert result["detail"]["type"] == "damage"


def test_resolve_wait_advances_time_by_the_given_hours():
    campaign, _ = _campaign_with_fighter()
    before = campaign.current_time.hour
    resolve_action(ActionIntent(action_type="wait", duration_hours=3), campaign)
    assert campaign.current_time.hour == before + 3


def test_resolve_unsupported_never_touches_state():
    campaign, _ = _campaign_with_fighter()
    before_time = str(campaign.current_time)
    result = resolve_action(ActionIntent(action_type="unsupported"), campaign)
    assert result["resolved"] is False
    assert str(campaign.current_time) == before_time


def test_resolve_look_describes_the_real_current_location():
    """Found by live playtesting: "I look around" originally fell
    through to "unsupported" with a jarring meta narration - the most
    basic player action there is was missing entirely."""
    campaign, _ = _campaign_with_fighter()
    result = resolve_action(ActionIntent(action_type="look"), campaign)
    assert result["resolved"] is True
    assert "Ravenhollow" in result["log"]
    assert "Old Mabel" in result["log"] or "innkeeper" in result["log"]


def test_resolve_look_reflects_travel():
    campaign, _ = _campaign_with_fighter()
    resolve_action(ActionIntent(action_type="travel", destination_id="farmstead"), campaign)
    result = resolve_action(ActionIntent(action_type="look"), campaign)
    assert "Farmstead" in result["log"]


def test_resolve_action_raises_for_a_truly_unknown_action_type():
    campaign, _ = _campaign_with_fighter()
    with pytest.raises(UnresolvableActionError):
        resolve_action(ActionIntent(action_type="teleport_to_the_moon"), campaign)


def test_no_living_party_member_raises_cleanly():
    from ethereal_dnd.characters import death

    campaign, sky = _campaign_with_fighter()
    death.apply_damage(sky, 9999, campaign.current_time, campaign.events)
    with pytest.raises(UnresolvableActionError):
        resolve_action(ActionIntent(action_type="skill_check", skill_id="climb"), campaign)


# --- gnosis_narrator -----------------------------------------------------

def test_gnosis_narrator_narrate_resolved_action_calls_the_chat_fn():
    campaign, _ = _campaign_with_fighter()
    context = build_context(campaign)
    seen = []
    narrator = GnosisNarrator(chat_fn=lambda messages: seen.append(messages) or "A vivid description.")
    resolution = {"resolved": True, "kind": "wait", "log": "Time passes."}
    narration = narrator.narrate_resolved_action(resolution, context)
    assert narration == "A vivid description."
    assert seen  # the chat_fn was actually invoked


def test_gnosis_narrator_describe_location():
    campaign, _ = _campaign_with_fighter()
    location = campaign.world.locations["ravenhollow"]
    narrator = GnosisNarrator(chat_fn=lambda messages: "It's a cozy little town.")
    assert narrator.describe_location(location) == "It's a cozy little town."


def test_gnosis_narrator_respond_to_dialogue():
    campaign, _ = _campaign_with_fighter()
    npc = campaign.world.npcs["mabel_innkeeper"]
    narrator = GnosisNarrator(chat_fn=lambda messages: "Welcome, traveler!")
    assert narrator.respond_to_dialogue(None, npc, "hello") == "Welcome, traveler!"


def test_gnosis_narrator_interpret_player_intent_is_intentionally_unimplemented():
    narrator = GnosisNarrator(chat_fn=lambda messages: "")
    with pytest.raises(NotImplementedError):
        narrator.interpret_player_intent("anything")


# --- game_loop / debug_cli.play -----------------------------------------

def test_process_player_input_runs_the_full_pipeline():
    campaign, sky = _campaign_with_fighter()
    intent_chat_fn = _json_chat_fn({"action_type": "wait", "duration_hours": 2})
    narrator = GnosisNarrator(chat_fn=lambda messages: "Two hours pass quietly.")

    result = process_player_input(campaign, narrator, "I wait a couple hours", chat_fn=intent_chat_fn)

    assert result["intent"].action_type == "wait"
    assert result["resolution"]["resolved"] is True
    assert result["narration"] == "Two hours pass quietly."


def test_null_narrator_works_with_the_full_pipeline():
    """NullNarrator (Phase 0's LLM-free proof) must still satisfy the
    Narrator interface Phase 3's game loop actually calls - not just the
    original four Section 55 methods."""
    campaign, _ = _campaign_with_fighter()

    def broken_chat_fn(messages):
        return "not valid json"

    result = process_player_input(campaign, NullNarrator(), "gibberish", chat_fn=broken_chat_fn)

    assert result["intent"].action_type == "unsupported"
    assert result["narration"] == result["resolution"]["log"]


# --- characters/relationships --------------------------------------------

def test_adjust_and_get_relationship():
    from ethereal_dnd.characters.relationships import adjust_relationship, get_relationship

    _, sky = _campaign_with_fighter()
    assert get_relationship(sky, "mabel_innkeeper") == 0.0
    adjust_relationship(sky, "mabel_innkeeper", 5.0)
    adjust_relationship(sky, "mabel_innkeeper", 2.0)
    assert get_relationship(sky, "mabel_innkeeper") == 7.0
