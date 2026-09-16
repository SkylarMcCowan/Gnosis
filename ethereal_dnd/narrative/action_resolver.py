"""Action resolver (design doc Section 32/34) - maps an ActionIntent to
the correct rules-engine call. This is pure rules code: no LLM
involvement anywhere in this module, matching Section 2.1's "AI never
overrides mechanics" - the narrator describes what this function
decided, never the other way around.

Covers the Section 31 example actions that have real mechanical handling
in this engine so far (attack, skill checks, talking, travel, resting,
casting one of the 4 starting spells, waiting) - anything else is a
correct "unsupported" result, not a crash or an invented outcome.
"""
from ethereal_dnd.characters.checks import DEFAULT_DC, perform_skill_check
from ethereal_dnd.combat import actions as combat_actions
from ethereal_dnd.narrative.action_intent import ActionIntent


class UnresolvableActionError(ValueError):
    """Raised when the resolver is asked to resolve something outside
    KNOWN_ACTION_TYPES - a parser bug (it must already restrict itself to
    that list), not a normal "the player tried something weird" case,
    which is what "unsupported" already exists to handle."""


def _acting_character(campaign):
    """The "player" placeholder from intent_parser.py resolves to the
    first living party member - true multi-character control switching
    isn't built yet (GC-071's character creation gap note applies here
    too: there's one active character for now, not real party-member
    selection)."""
    living = campaign.party.living_members()
    if not living:
        raise UnresolvableActionError("No living party member to act.")
    return living[0]


def resolve_action(intent: ActionIntent, campaign) -> dict:
    """Returns {"resolved": bool, "kind": str, "detail": dict, "log": str}.
    `kind` matches (or explains why it doesn't match) intent.action_type."""
    handler = _HANDLERS.get(intent.action_type)
    if handler is None:
        raise UnresolvableActionError(f"No handler for action_type {intent.action_type!r}")
    return handler(intent, campaign)


def _resolve_attack(intent: ActionIntent, campaign) -> dict:
    actor = _acting_character(campaign)
    npc = campaign.world.npcs.get(intent.target_id) if intent.target_id else None
    if npc is None or not npc.alive:
        return {
            "resolved": False, "kind": "attack", "detail": {},
            "log": f"There's no one matching {intent.target_id!r} here to attack.",
        }
    result = combat_actions.resolve_attack(actor, npc.character, campaign.rng())
    combat_actions.apply_attack_damage(result, npc.character, campaign.current_time, campaign.events)
    return {"resolved": True, "kind": "attack", "detail": result, "log": result["log"]}


def _resolve_skill_check(intent: ActionIntent, campaign) -> dict:
    actor = _acting_character(campaign)
    if not intent.skill_id:
        return {
            "resolved": False, "kind": "skill_check", "detail": {},
            "log": "No specific skill was identified for that attempt.",
        }
    try:
        result = perform_skill_check(actor, intent.skill_id, dc=DEFAULT_DC, rng_service=campaign.rng())
    except Exception as exc:  # UntrainedSkillError, KeyError (unknown skill_id), etc.
        return {
            "resolved": False, "kind": "skill_check", "detail": {},
            "log": f"{actor.name or actor.id} cannot attempt that: {exc}",
        }
    return {"resolved": True, "kind": "skill_check", "detail": result, "log": result["log"]}


def _resolve_talk(intent: ActionIntent, campaign) -> dict:
    npc = campaign.world.npcs.get(intent.target_id) if intent.target_id else None
    if npc is None:
        return {
            "resolved": False, "kind": "talk", "detail": {},
            "log": f"There's no one matching {intent.target_id!r} here to talk to.",
        }
    if not npc.alive:
        return {"resolved": True, "kind": "talk", "detail": {"npc_id": npc.id}, "log": f"{npc.name} is dead."}
    rumors = [rumor["text"] for rumor in npc.rumors]
    return {
        "resolved": True, "kind": "talk",
        "detail": {"npc_id": npc.id, "npc_name": npc.name, "rumors": rumors},
        "log": f"{npc.name}: " + (" ".join(rumors) if rumors else "(nothing to share)"),
    }


def _resolve_travel(intent: ActionIntent, campaign) -> dict:
    from ethereal_dnd.world.travel import NoRouteError, travel

    if not intent.destination_id:
        return {
            "resolved": False, "kind": "travel", "detail": {},
            "log": "No clear destination was identified.",
        }
    try:
        result = travel(campaign, intent.destination_id)
    except NoRouteError as exc:
        return {"resolved": False, "kind": "travel", "detail": {}, "log": str(exc)}
    return {"resolved": True, "kind": "travel", "detail": result, "log": result["log"]}


def _resolve_rest(intent: ActionIntent, campaign) -> dict:
    from ethereal_dnd.campaign.rest import rest

    rest(campaign.party, campaign.current_time, campaign.events)
    return {
        "resolved": True, "kind": "rest", "detail": {},
        "log": f"The party rests. {campaign.current_time}",
    }


def _resolve_cast_spell(intent: ActionIntent, campaign) -> dict:
    from ethereal_dnd.magic.spell import spell_registry

    actor = _acting_character(campaign)
    if not intent.spell_id or intent.spell_id not in spell_registry:
        return {
            "resolved": False, "kind": "cast_spell", "detail": {},
            "log": f"No known spell matching {intent.spell_id!r}.",
        }
    spell = spell_registry.get(intent.spell_id)
    effect = spell.build_effect()
    if spell.effect_type in ("damage", "healing"):
        detail = effect.apply(campaign.rng(), caster_level=actor.level)
    elif spell.effect_type == "buff":
        detail = effect.apply(caster_level=actor.level)
    else:
        detail = effect.apply()
    return {
        "resolved": True, "kind": "cast_spell",
        "detail": detail, "log": f"{actor.name or actor.id} casts {spell.name}.",
    }


def _resolve_wait(intent: ActionIntent, campaign) -> dict:
    hours = intent.duration_hours or 1
    campaign.current_time.advance(hours=hours)
    return {
        "resolved": True, "kind": "wait", "detail": {"hours": hours},
        "log": f"Time passes. {campaign.current_time}",
    }


def _resolve_look(intent: ActionIntent, campaign) -> dict:
    """Section 30's "describe the current location" - the most basic
    player action there is, and one that was missing entirely until a
    live playtest exposed it: "I look around" fell through to
    "unsupported" with a jarringly meta narration ("the engine confirms
    your request..."). Deliberately doesn't call the narrator directly -
    this module stays LLM-free; it just supplies the real facts (via
    context_builder, the same source the narrator's own context comes
    from) for narrate_resolved_action() to describe."""
    from ethereal_dnd.narrative.context_builder import build_context, describe_location_text

    context = build_context(campaign)
    return {"resolved": True, "kind": "look", "detail": {}, "log": describe_location_text(context)}


def _resolve_unsupported(intent: ActionIntent, campaign) -> dict:
    return {
        "resolved": False, "kind": "unsupported", "detail": {},
        "log": "That isn't something this engine can resolve mechanically yet.",
    }


_HANDLERS = {
    "attack": _resolve_attack,
    "skill_check": _resolve_skill_check,
    "talk": _resolve_talk,
    "travel": _resolve_travel,
    "rest": _resolve_rest,
    "cast_spell": _resolve_cast_spell,
    "wait": _resolve_wait,
    "look": _resolve_look,
    "unsupported": _resolve_unsupported,
}
