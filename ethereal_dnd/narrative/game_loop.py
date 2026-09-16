"""The Section 34 pipeline, assembled two ways:

- process_player_input(): freeform text -> intent parser -> structured
  action -> rules engine -> result -> narrative context -> narrator.
- process_menu_action(): an already-fully-determined ActionIntent (from
  action_menu.available_actions()) straight into the rules engine,
  skipping the intent parser entirely - there's nothing to guess when
  the button click already *is* the structured intent. Only the
  narrator still calls a model, to describe the result.

Both rebuild the narrative context *after* resolving the action, not
before: an action that changes the party's location, the time, or an
NPC's state (travel, rest, a kill) means the pre-action context is stale
by the time the narrator would see it - the resolution's own log is what
carried the real post-action facts in earlier testing, papering over
this, but the narrator's "current scene" line was still describing where
the party *used to be* until this was fixed.
"""
from ethereal_dnd.narrative.action_intent import ActionIntent
from ethereal_dnd.narrative.action_resolver import resolve_action
from ethereal_dnd.narrative.context_builder import build_context
from ethereal_dnd.narrative.intent_parser import parse_intent


def process_player_input(campaign, narrator, player_text: str, chat_fn=None) -> dict:
    """Runs the full pipeline once. Returns {"intent", "resolution",
    "narration"} - the intermediate structured values are returned
    alongside the final prose so a caller (or a test) can inspect what
    actually happened mechanically, not just trust the narration's
    wording."""
    pre_context = build_context(campaign)  # what the intent parser needs to resolve names against
    intent = parse_intent(player_text, pre_context, chat_fn=chat_fn)
    resolution = resolve_action(intent, campaign)
    post_context = build_context(campaign)  # what the narrator needs to describe the real result
    narration = narrator.narrate_resolved_action(resolution, post_context)
    return {"intent": intent, "resolution": resolution, "narration": narration}


def process_menu_action(campaign, narrator, intent: ActionIntent) -> dict:
    """Same shape as process_player_input()'s return value, but for a
    button-driven ActionIntent that's already fully determined - no
    intent-parsing model call at all."""
    resolution = resolve_action(intent, campaign)
    context = build_context(campaign)
    narration = narrator.narrate_resolved_action(resolution, context)
    return {"intent": intent, "resolution": resolution, "narration": narration}
