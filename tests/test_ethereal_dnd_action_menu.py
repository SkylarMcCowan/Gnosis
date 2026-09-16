"""Tests for the button-driven action menu (narrative/action_menu.py)
and its game_loop.process_menu_action() entry point - the "contained
logic" alternative to freeform text: a button's ActionIntent is already
fully determined, so no intent-parsing model call happens for these.
"""
from ethereal_dnd.cli import debug_cli
from ethereal_dnd.narrative.action_menu import MenuAction, available_actions
from ethereal_dnd.narrative.game_loop import process_menu_action
from ethereal_dnd.narrative.gnosis_narrator import GnosisNarrator


def _campaign_with_fighter():
    campaign = debug_cli.new_ravenhollow_campaign(seed=1)
    sky = debug_cli.create_test_character(
        "Sky", "fighter", {"STR": 16, "DEX": 14, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8},
        weapon_id="longsword", armor_id="chain_shirt", max_hp=13,
    )
    campaign.party.add(sky)
    return campaign, sky


def test_available_actions_always_includes_look_and_rest():
    campaign, _ = _campaign_with_fighter()
    labels = [action.label for action in available_actions(campaign)]
    assert any("Look Around" in label for label in labels)
    assert any("Rest" in label for label in labels)


def test_available_actions_offers_talk_and_attack_for_every_living_npc():
    campaign, _ = _campaign_with_fighter()
    actions = available_actions(campaign)
    talk_targets = {a.intent.target_id for a in actions if a.intent.action_type == "talk"}
    attack_targets = {a.intent.target_id for a in actions if a.intent.action_type == "attack"}
    assert talk_targets == attack_targets == set(campaign.world.npcs)


def test_available_actions_excludes_dead_npcs():
    from ethereal_dnd.characters import death

    campaign, _ = _campaign_with_fighter()
    npc = campaign.world.npcs["tam_trader"]
    death.apply_damage(npc.character, 9999, campaign.current_time, campaign.events)
    actions = available_actions(campaign)
    assert not any(a.intent.target_id == "tam_trader" for a in actions)


def test_available_actions_offers_travel_for_every_real_route():
    campaign, _ = _campaign_with_fighter()
    actions = available_actions(campaign)
    destinations = {a.intent.destination_id for a in actions if a.intent.action_type == "travel"}
    assert destinations == {"blackwood", "abandoned_mine", "farmstead"}


def test_available_actions_refreshes_after_travel():
    campaign, _ = _campaign_with_fighter()
    travel_action = next(a for a in available_actions(campaign) if a.intent.destination_id == "blackwood")
    narrator = GnosisNarrator(chat_fn=lambda messages: "You arrive.")

    process_menu_action(campaign, narrator, travel_action.intent)

    new_actions = available_actions(campaign)
    assert not any(a.intent.action_type == "talk" for a in new_actions)  # Blackwood has no NPCs
    new_destinations = {a.intent.destination_id for a in new_actions if a.intent.action_type == "travel"}
    assert new_destinations == {"ravenhollow", "old_ruins"}


def test_process_menu_action_never_calls_a_model_to_decide_the_action():
    """The whole point: only the narrator's chat_fn should ever be
    invoked - there is no intent-parsing call in this path at all."""
    campaign, _ = _campaign_with_fighter()
    calls = []
    narrator = GnosisNarrator(chat_fn=lambda messages: calls.append(messages) or "Described.")
    look_action = next(a for a in available_actions(campaign) if a.intent.action_type == "look")

    result = process_menu_action(campaign, narrator, look_action.intent)

    assert result["intent"] is look_action.intent
    assert result["resolution"]["resolved"] is True
    assert result["narration"] == "Described."
    assert len(calls) == 1  # exactly one model call, for narration only


def test_process_menu_action_gives_the_narrator_post_action_context():
    """Regression test for the stale-context bug found and fixed
    alongside this feature: the narrator's context must reflect the
    location *after* the action resolves, not before."""
    campaign, _ = _campaign_with_fighter()
    seen_context = {}

    def chat_fn(messages):
        seen_context["location_mentioned"] = "Blackwood" in messages[-1]["content"]
        return "narrated"

    narrator = GnosisNarrator(chat_fn=chat_fn)
    travel_action = next(a for a in available_actions(campaign) if a.intent.destination_id == "blackwood")

    process_menu_action(campaign, narrator, travel_action.intent)

    assert seen_context["location_mentioned"] is True


def test_do_action_cli_wrapper_returns_just_the_narration():
    campaign, _ = _campaign_with_fighter()
    narrator = GnosisNarrator(chat_fn=lambda messages: "You look around.")
    look_action = next(a for a in debug_cli.list_actions(campaign) if a.intent.action_type == "look")

    assert debug_cli.do_action(campaign, narrator, look_action) == "You look around."


def test_menu_action_is_frozen_and_comparable():
    from ethereal_dnd.narrative.action_intent import ActionIntent

    action = MenuAction("Test", ActionIntent(action_type="look"))
    assert action.label == "Test"
    assert action.intent.action_type == "look"
