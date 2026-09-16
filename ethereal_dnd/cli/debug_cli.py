"""Developer debug CLI (design doc Section 53, subset) - proves Phase 0's
scaffolding boots end-to-end. The GUI's Ethereal DND panel
(ethereal_dnd_widget.py) imports these same functions directly rather
than shelling out to a subprocess, so there's exactly one implementation
of "what does advancing time / rolling a check do."
"""
from ethereal_dnd.campaign.campaign import Campaign
from ethereal_dnd.characters.character import Character
from ethereal_dnd.characters.multiclass import add_class_level
from ethereal_dnd.characters.party import Party
from ethereal_dnd.combat import actions, initiative
from ethereal_dnd.core import dice
from ethereal_dnd.divine.setup import attach_alignment_and_compliance
from ethereal_dnd.items.item import ItemInstance
from ethereal_dnd.world.world import World

MAX_DUEL_ROUNDS = 100


def bootstrap_data() -> None:
    """Load every data-driven registry (races, classes, skills, items,
    spells, deities) - idempotent, so calling this more than once (once
    per campaign, once per test) is harmless. This is the "loaded at
    startup" every Sprint 1.1/1.2/1.4/1.5/1.5-divine loader ticket
    asked for."""
    from ethereal_dnd.characters.class_definition import load_classes
    from ethereal_dnd.characters.race import load_races
    from ethereal_dnd.characters.skills import load_skills
    from ethereal_dnd.divine.deity import load_deities
    from ethereal_dnd.items.item import load_items
    from ethereal_dnd.magic.spell import load_spells

    load_races()
    load_classes()
    load_skills()
    load_items()
    load_spells()
    load_deities()


def new_campaign(name: str = "Untitled Campaign", seed: int | None = None) -> Campaign:
    from ethereal_dnd.campaign.history import attach_history_log

    bootstrap_data()
    campaign = Campaign(name=name, world=World(), party=Party(), random_seed=seed)
    attach_alignment_and_compliance(campaign)
    attach_history_log(campaign)
    return campaign


def new_ravenhollow_campaign(name: str = "The Ashes of Ravenhollow", seed: int | None = None) -> Campaign:
    """The actual starting campaign (Section 46): new_campaign() plus
    Ravenhollow's world content (world/campaign_content.py) and quest
    hooks (quests/quest_hooks.py) - kept separate from the bare
    new_campaign() so Phase 0/1/1.5 tests (and the Scripted Duel/
    Alignment Demo buttons) can keep using an empty world."""
    from ethereal_dnd.quests.quest_hooks import attach_quest_hooks
    from ethereal_dnd.world.campaign_content import load_ashes_of_ravenhollow

    campaign = new_campaign(name=name, seed=seed)
    load_ashes_of_ravenhollow(campaign)
    attach_quest_hooks(campaign)
    return campaign


def show_party(campaign: Campaign) -> str:
    if not campaign.party.members:
        return "Party is empty."
    lines = [f"Party ({len(campaign.party.members)} member(s)):"]
    for member in campaign.party.members:
        lines.append(
            f"  {member.name or member.id} - level {member.level}, "
            f"HP {member.max_hp - member.damage}/{member.max_hp}, "
            f"status={member.status}, alignment={member.alignment.derived_alignment()}"
        )
    return "\n".join(lines)


def show_world(campaign: Campaign) -> str:
    if not campaign.world.locations:
        return "World has no locations yet."
    lines = [f"World ({len(campaign.world.locations)} location(s)):"]
    for location in campaign.world.locations.values():
        marker = "" if location.discovered else " (undiscovered)"
        lines.append(f"  {location.name}{marker}")
    return "\n".join(lines)


def show_location(campaign: Campaign) -> str:
    from ethereal_dnd.narrative.context_builder import build_context, describe_location_text

    return describe_location_text(build_context(campaign))


def talk_to(campaign: Campaign, npc_id: str) -> str:
    npc = campaign.world.npcs[npc_id]
    if not npc.alive:
        return f"{npc.name} is dead and has nothing to say."
    if not npc.rumors:
        return f"{npc.name} has nothing to share right now."
    lines = [f"{npc.name} says:"]
    lines.extend(f'  "{rumor["text"]}"' for rumor in npc.rumors)
    return "\n".join(lines)


def show_time(campaign: Campaign) -> str:
    return str(campaign.current_time)


def advance_time(campaign: Campaign, hours: float = 0, minutes: int = 0) -> str:
    campaign.current_time.advance(hours=hours, minutes=minutes)
    return show_time(campaign)


def roll_check(campaign: Campaign, expr: str) -> str:
    result = dice.roll(expr, rng_service=campaign.rng())
    return f"{expr} -> {result}"


def create_test_character(
    name: str,
    class_id: str,
    ability_scores: dict[str, int],
    race_id: str | None = None,
    weapon_id: str | None = None,
    armor_id: str | None = None,
    max_hp: int = 10,
) -> Character:
    """Build a ready-to-fight Character: one class level, ability scores
    set, weapon/armor equipped if given. Used by run_scripted_duel() and
    by anything (CLI or GUI) that wants a quick real combatant without
    hand-wiring inventory/equipment plumbing each time."""
    character = Character(name=name, race_id=race_id, ability_scores=dict(ability_scores), max_hp=max_hp)
    add_class_level(character, class_id)
    for slot, item_id in (("weapon", weapon_id), ("armor", armor_id)):
        if item_id is not None:
            instance = ItemInstance(definition_id=item_id)
            character.inventory.add(instance)
            character.equipment[slot] = instance.id
    return character


def run_scripted_duel(campaign: Campaign, fighter_a: Character, fighter_b: Character) -> str:
    """Phase 1's exit criterion, made runnable: two characters fight to a
    win/loss, every roll logged in the Section 54 format, fully
    deterministic under campaign.rng() (i.e. under campaign.random_seed).
    Does not touch campaign.party - the combatants are the caller's, not
    necessarily the player's own party."""
    rng = campaign.rng()
    combatants = {fighter_a.id: fighter_a, fighter_b.id: fighter_b}
    order = initiative.roll_initiative([fighter_a, fighter_b], rng)
    lines = [f"Initiative order: {', '.join(combatants[cid].name or cid for cid in order)}"]

    rounds = 0
    while fighter_a.status == "alive" and fighter_b.status == "alive" and rounds < MAX_DUEL_ROUNDS:
        rounds += 1
        lines.append(f"--- Round {rounds} ---")
        for actor_id in order:
            actor = combatants[actor_id]
            target = fighter_b if actor is fighter_a else fighter_a
            if actor.status != "alive" or target.status != "alive":
                continue
            result = actions.resolve_attack(actor, target, rng)
            lines.append(result["log"])
            actions.apply_attack_damage(result, target, campaign.current_time, campaign.events)

    winner = fighter_a if fighter_a.status == "alive" else fighter_b
    lines.append(f"Winner: {winner.name or winner.id} after {rounds} round(s)")
    return "\n".join(lines)


def run_party_combat(campaign: Campaign, party_side: list[Character], enemy_side: list[Character]) -> dict:
    """Generalizes run_scripted_duel() to N-vs-N (a random encounter's
    spawned monsters vs. the player's party, or the dungeon's boss room):
    full initiative order across both sides, each living actor attacks a
    random living enemy each turn, fully deterministic under
    campaign.rng(). Returns {"log": str, "party_won": bool}."""
    rng = campaign.rng()
    combatants = {c.id: c for c in party_side + enemy_side}
    party_ids = {c.id for c in party_side}
    order = initiative.roll_initiative(list(combatants.values()), rng)
    lines = [f"Initiative order: {', '.join(combatants[cid].name or cid for cid in order)}"]

    def side_alive(ids):
        return [combatants[cid] for cid in ids if combatants[cid].status == "alive"]

    rounds = 0
    while side_alive(party_ids) and side_alive(set(combatants) - party_ids) and rounds < MAX_DUEL_ROUNDS:
        rounds += 1
        lines.append(f"--- Round {rounds} ---")
        for actor_id in order:
            actor = combatants[actor_id]
            if actor.status != "alive":
                continue
            enemy_ids = (set(combatants) - party_ids) if actor_id in party_ids else party_ids
            living_enemies = side_alive(enemy_ids)
            if not living_enemies:
                continue
            target = living_enemies[rng.randint(0, len(living_enemies) - 1)]
            result = actions.resolve_attack(actor, target, rng)
            lines.append(result["log"])
            actions.apply_attack_damage(result, target, campaign.current_time, campaign.events)

    party_won = bool(side_alive(party_ids)) and not side_alive(set(combatants) - party_ids)
    lines.append(f"{'Party wins' if party_won else 'Party defeated'} after {rounds} round(s).")
    return {"log": "\n".join(lines), "party_won": party_won}


def accept_quest(campaign: Campaign, quest_id: str) -> str:
    from ethereal_dnd.quests.quest_manager import start_quest

    quest = start_quest(campaign, quest_id)
    return f"[QUEST STARTED] {quest.title}: {quest.description}"


def complete_quest_objective(campaign: Campaign, quest_id: str, objective_index: int) -> str:
    from ethereal_dnd.quests.quest_manager import complete_objective

    quest = complete_objective(campaign, quest_id, objective_index)
    status = f"[QUEST COMPLETE] {quest.title}!" if quest.state == "completed" else f"Objective complete: {quest.objectives[objective_index]['description']}"
    return status


def show_quests(campaign: Campaign) -> str:
    if not campaign.state.quest_state:
        return "No quests accepted yet."
    lines = []
    for quest in campaign.state.quest_state.values():
        lines.append(f"{quest.title} [{quest.state}]")
        for objective in quest.objectives:
            lines.append(f"  [{'x' if objective['done'] else ' '}] {objective['description']}")
    return "\n".join(lines)


def enter_dungeon(dungeon_id: str):
    """Returns (Dungeon, log_str) for the dungeon's entry room. The
    caller holds onto the returned Dungeon and passes it back into
    enter_room() for each subsequent room - dungeon state (cleared
    rooms, sprung traps) lives on that instance, not in the campaign,
    since nothing else needs it once the dungeon is done."""
    from ethereal_dnd.world.dungeon import load_dungeon

    dungeon = load_dungeon(dungeon_id)
    room = dungeon.rooms[dungeon.entry_room_id]
    return dungeon, f"[DUNGEON] Entering {dungeon_id.replace('_', ' ').title()}.\n{_describe_room(room)}"


def _describe_room(room) -> str:
    lines = [f"{room.name}: {room.description}"]
    if room.exits:
        lines.append("Exits: " + ", ".join(room.exits))
    return "\n".join(lines)


def enter_room(campaign: Campaign, dungeon, room_id: str) -> dict:
    """Move into `room_id`: describe it, spring its trap against the
    first living party member if it has one and hasn't fired yet, and
    report any monsters present (not yet fought - the caller runs
    run_party_combat() separately, same split as roll_encounter())."""
    from ethereal_dnd.world.dungeon import trigger_trap

    room = dungeon.rooms[room_id]
    lines = [_describe_room(room)]

    if room.trap is not None and not room.trap.triggered:
        living = campaign.party.living_members()
        if living:
            result = trigger_trap(living[0], room.trap, campaign.rng())
            lines.append(result["log"])

    monsters = []
    if room.monster_ids and not room.cleared:
        from ethereal_dnd.encounters.monster_factory import spawn_monster

        monsters = [spawn_monster(monster_id) for monster_id in room.monster_ids]
        lines.append(f"Monsters: {', '.join(m.name for m in monsters)}")

    return {"log": "\n".join(lines), "room": room, "monsters": monsters}


def save_current_campaign(campaign: Campaign) -> str:
    from ethereal_dnd.campaign.save_manager import save_campaign

    path = save_campaign(campaign)
    return f"Saved to {path}"


def load_saved_campaign(campaign_id: str) -> Campaign:
    """Loads the campaign and re-attaches the alignment/compliance and
    quest-hook event subscriptions - a freshly-loaded Campaign's
    `events` bus starts empty (save_manager.py's known limitation), the
    same as a brand-new Campaign() does before new_ravenhollow_campaign()
    wires it up."""
    from ethereal_dnd.campaign.history import attach_history_log
    from ethereal_dnd.campaign.save_manager import load_campaign
    from ethereal_dnd.quests.quest_hooks import attach_quest_hooks

    bootstrap_data()
    campaign = load_campaign(campaign_id)
    attach_alignment_and_compliance(campaign)
    attach_quest_hooks(campaign)
    attach_history_log(campaign)
    return campaign


def buy_item(campaign: Campaign, character: Character, npc_id: str, item_id: str) -> str:
    from ethereal_dnd.items.item import item_registry
    from ethereal_dnd.world.shop import buy_from_npc

    buy_from_npc(character, campaign.world.npcs[npc_id], item_id, campaign.events)
    return f"Bought {item_registry.get(item_id).name} for {item_registry.get(item_id).value_gp} gp."


def sell_item(character: Character, instance_id: str) -> str:
    from ethereal_dnd.world.shop import sell_item as _sell_item

    price = _sell_item(character, instance_id)
    return f"Sold for {price} gp."


def create_narrator():
    from ethereal_dnd.narrative.gnosis_narrator import GnosisNarrator

    return GnosisNarrator()


def dialogue(campaign: Campaign, narrator, npc_id: str, player_text: str) -> str:
    """Direct NPC conversation (Section 38): the narrator voices the NPC
    in character, constrained to what that NPC actually knows (their
    rumors - see GnosisNarrator.respond_to_dialogue()), and the acting
    party member's relationship with them nudges up slightly for
    engaging at all. Distinct from action_type "talk" in the intent-
    parser pipeline, which surfaces rumors directly rather than an
    in-character reply - this is for when the player is already talking
    to a specific NPC they've identified, not for parsing "I talk to
    someone" out of freeform text."""
    from ethereal_dnd.characters.relationships import adjust_relationship

    npc = campaign.world.npcs[npc_id]
    actor = campaign.party.living_members()[0] if campaign.party.living_members() else None
    reply = narrator.respond_to_dialogue(actor, npc, player_text)
    if actor is not None:
        adjust_relationship(actor, npc_id, 1.0)
    return f"{npc.name}: {reply}"


def play(campaign: Campaign, narrator, player_text: str) -> str:
    """The natural-language entry point (Phase 3): freeform text through
    the full intent-parser -> rules-engine -> narrator pipeline. Returns
    just the narration; use ethereal_dnd.narrative.game_loop.process_player_input()
    directly instead if the intent/resolution detail is also needed
    (e.g. for logging or a test)."""
    from ethereal_dnd.narrative.game_loop import process_player_input

    return process_player_input(campaign, narrator, player_text)["narration"]


def list_actions(campaign: Campaign):
    """The button-menu entry point: every action currently available,
    built straight from real campaign state (narrative/action_menu.py) -
    no model call involved in producing this list."""
    from ethereal_dnd.narrative.action_menu import available_actions

    return available_actions(campaign)


def do_action(campaign: Campaign, narrator, menu_action) -> str:
    """Resolve a MenuAction (from list_actions()) straight through the
    rules engine and narrator, skipping the intent parser entirely - the
    button already *is* the structured action, so there's nothing left
    to guess. Returns just the narration, same convention as play()."""
    from ethereal_dnd.narrative.game_loop import process_menu_action

    return process_menu_action(campaign, narrator, menu_action.intent)["narration"]


def show_history(campaign: Campaign, last: int | None = None) -> str:
    entries = campaign.history if last is None else campaign.history[-last:]
    if not entries:
        return "No history recorded yet."
    return "\n".join(entries)


def show_divine_standing(character: Character) -> str:
    standing = character.divine_standing
    header = f"{character.name or character.id} - alignment: {character.alignment.derived_alignment()}"
    if character.deity_id:
        header += f" (deity: {character.deity_id})"
    lines = [header, f"  Fallen: {standing.fallen}"]
    if standing.fallen:
        lines.append(f"  Reason: {standing.fallen_reason}")
    if standing.powers_revoked:
        lines.append(f"  Powers revoked for: {', '.join(standing.powers_revoked)}")
    if standing.advancement_blocked_for:
        lines.append(f"  Advancement blocked for: {', '.join(standing.advancement_blocked_for)}")
    return "\n".join(lines)


def commit_evil_act(campaign: Campaign, character: Character, description: str = "a willful evil act") -> str:
    """Phase 1.5's exit criterion, made runnable: force an alignment
    shift on a party member (`character` must already be in
    campaign.party - attach_alignment_and_compliance() looks members up
    by id there) and show whatever the compliance engine decides,
    logged the same way a combat roll is - no LLM involved anywhere in
    this call."""
    from ethereal_dnd.core.events import CommittedEvilAct

    before = show_divine_standing(character)
    campaign.events.emit(CommittedEvilAct(character_id=character.id, description=description))
    after = show_divine_standing(character)
    return f"[ALIGNMENT] {character.name or character.id} commits {description}.\nBefore:\n{before}\nAfter:\n{after}"


def commit_good_act(campaign: Campaign, character: Character, description: str = "an act of good") -> str:
    """See commit_evil_act() - the mirror case (what let a NE cleric's
    alignment actually drift toward good over repeated calls)."""
    from ethereal_dnd.core.events import CommittedGoodAct

    before = show_divine_standing(character)
    campaign.events.emit(CommittedGoodAct(character_id=character.id, description=description))
    after = show_divine_standing(character)
    return f"[ALIGNMENT] {character.name or character.id} performs {description}.\nBefore:\n{before}\nAfter:\n{after}"


def main() -> None:
    """Minimal standalone REPL - not the GUI's entry point, just enough
    to prove the scaffolding boots from a terminal too."""
    campaign = new_campaign()
    print(f"New campaign: {campaign.name} (seed={campaign.random_seed})")
    print(show_time(campaign))
    print(advance_time(campaign, hours=2))
    print(roll_check(campaign, "1d20+3"))
    print(show_party(campaign))
    print(show_world(campaign))


if __name__ == "__main__":
    main()
