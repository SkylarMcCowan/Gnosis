"""ComplianceRule evaluation (alignment doc §3-4) - pure functions, no
event bus involvement here (divine/setup.py wires this to events). Given
a Character, checks every alignment_restriction rule on every class
they've taken levels in, applies on_violation effects to
CharacterDivineStanding, and reports what changed so the caller can emit
events.
"""
from ethereal_dnd.characters.class_definition import class_registry
from ethereal_dnd.divine.deity import decode_alignment_code, deity_registry

# lawful/good = +1, chaotic/evil = -1, neutral = 0 on their respective
# axis - lets "how many steps apart" be a plain integer difference
# instead of a bespoke lookup table per axis.
_AXIS_POSITION = {"lawful": 1, "chaotic": -1, "good": 1, "evil": -1, "neutral": 0}


def _steps_apart(label_a: str, label_b: str) -> int:
    return abs(_AXIS_POSITION[label_a] - _AXIS_POSITION[label_b])


def _is_violated(trigger: dict, character) -> bool:
    """True if `trigger` (an alignment_deviation-type trigger dict) is
    currently violated by `character`'s alignment. event_pattern triggers
    are never "currently violated" in this sense - they fire once, on
    the matching event - so callers must not pass one here."""
    check = trigger["check"]
    alignment = character.alignment

    if check == "exact_alignment":
        required_lc, required_ge = decode_alignment_code(trigger["required_alignment"])
        return alignment.law_chaos_label() != required_lc or alignment.good_evil_label() != required_ge

    if check == "deity_relative":
        if character.deity_id is None:
            return False  # no deity selected: nothing to be out of compliance with
        deity = deity_registry.get(character.deity_id)
        deity_lc, deity_ge = decode_alignment_code(deity.alignment)
        char_lc, char_ge = alignment.law_chaos_label(), alignment.good_evil_label()

        lc_steps = _steps_apart(char_lc, deity_lc)
        ge_steps = _steps_apart(char_ge, deity_ge)
        max_deviation = trigger["max_axis_deviation"]

        if lc_steps > max_deviation or ge_steps > max_deviation:
            return True
        if lc_steps >= 1 and ge_steps >= 1:
            return True  # "one axis, but not both"
        if trigger.get("forbid_neutral_unless_deity_neutral") and char_lc == "neutral" and char_ge == "neutral":
            if not (deity_lc == "neutral" and deity_ge == "neutral"):
                return True
        return False

    if check == "axis_requirement":
        if trigger["required_axis"] == "any_neutral":
            return alignment.law_chaos_label() != "neutral" and alignment.good_evil_label() != "neutral"
        axis_label = alignment.law_chaos_label() if trigger["required_axis"] == "law_chaos" else alignment.good_evil_label()
        return axis_label != trigger["required_value"]

    if check == "axis_forbidden":
        axis_label = alignment.law_chaos_label() if trigger["required_axis"] == "law_chaos" else alignment.good_evil_label()
        return axis_label == trigger["forbidden_value"]

    raise ValueError(f"Unknown alignment_deviation check: {check!r}")


def _apply_violation(character, class_id: str, rule: dict, campaign_time) -> None:
    on_violation = rule["on_violation"]
    standing = character.divine_standing

    if on_violation["effect"] in ("revoke_class_powers", "revoke_spells_only"):
        if class_id not in standing.powers_revoked:
            standing.powers_revoked.append(class_id)
    if on_violation["effect"] in ("block_advancement", "block_advancement_and_signature_ability"):
        if class_id not in standing.advancement_blocked_for:
            standing.advancement_blocked_for.append(class_id)

    standing.fallen = True
    standing.fallen_reason = rule["description"]
    standing.fallen_at = campaign_time


def _clear_class_standing(character, class_id: str) -> None:
    standing = character.divine_standing
    if class_id in standing.powers_revoked:
        standing.powers_revoked.remove(class_id)
    if class_id in standing.advancement_blocked_for:
        standing.advancement_blocked_for.remove(class_id)
    if not standing.powers_revoked and not standing.advancement_blocked_for:
        standing.fallen = False
        standing.fallen_reason = None
        standing.fallen_at = None


def evaluate_character(character, campaign_time=None) -> list[dict]:
    """Check every alignment_deviation rule (not event_pattern ones -
    see evaluate_event() for those) on every class `character` has
    levels in. Applies newly-triggered violations, auto-clears
    "realignment"-restoration blocks whose trigger no longer holds
    (Section 5's "no ritual needed" monk/barbarian path), and returns
    a list of {"class_id", "reason", "kind": "violated"|"restored"} for
    whatever actually changed, so the caller can emit events for it."""
    changes = []
    for class_level in character.class_levels:
        class_def = class_registry.get(class_level.class_id)
        for rule in class_def.alignment_restriction:
            trigger = rule["trigger"]
            if trigger["type"] != "alignment_deviation":
                continue

            violated = _is_violated(trigger, character)
            class_id = class_level.class_id
            currently_blocked = (
                class_id in character.divine_standing.powers_revoked
                or class_id in character.divine_standing.advancement_blocked_for
            )

            if violated and not currently_blocked:
                _apply_violation(character, class_id, rule, campaign_time)
                changes.append({"class_id": class_id, "reason": rule["description"], "kind": "violated"})
            elif not violated and currently_blocked and rule["on_violation"]["restoration"] == "realignment":
                _clear_class_standing(character, class_id)
                changes.append({"class_id": class_id, "reason": "realigned", "kind": "restored"})
    return changes


def evaluate_event(character, event_name: str, event_class_id: str | None = None, campaign_time=None) -> list[dict]:
    """Check every event_pattern rule matching `event_name` (and, if
    given, scoped to `event_class_id` - e.g. a BrokeCodeOfConduct event
    always carries the class whose code was broken) on every class
    `character` has levels in."""
    changes = []
    for class_level in character.class_levels:
        if event_class_id is not None and class_level.class_id != event_class_id:
            continue
        class_def = class_registry.get(class_level.class_id)
        for rule in class_def.alignment_restriction:
            trigger = rule["trigger"]
            if trigger["type"] != "event_pattern" or trigger["matches_event"] != event_name:
                continue
            class_id = class_level.class_id
            if class_id not in character.divine_standing.powers_revoked:
                _apply_violation(character, class_id, rule, campaign_time)
                changes.append({"class_id": class_id, "reason": rule["description"], "kind": "violated"})
    return changes
