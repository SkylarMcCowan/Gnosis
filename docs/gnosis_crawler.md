# Gnosis Crawler

## Extensible D&D 3.5-Inspired Single-Player Sandbox RPG

### Initial Architecture, Scaffolding, and Build Guide

Companion docs: [gnosis_crawler_alignment.md](gnosis_crawler_alignment.md)
(deity/alignment compliance — "falling from grace"),
[gnosis_crawler_backlog.md](gnosis_crawler_backlog.md) (phased ticket
backlog), and [srd_reference/](srd_reference/) (local offline copy of the
D&D 3.5 SRD).

---

# 1. Project Vision

Build a single-player, text-driven fantasy CRPG inside the Gnosis ecosystem.

The game should feel like a combination of:

* D&D 3.5 tabletop rules
* Knights of Pen & Paper
* classic CRPG sandbox design
* choose-your-own-adventure storytelling
* persistent world simulation
* AI dungeon master
* party-based RPGs

The player creates one primary adventurer and two companions.

The player directly controls all three party members.

The ultimate long-term objective is for the player's character to become **mythically good, mythically evil, or something in between**, based on actual actions taken throughout the campaign.

The player is not following a fixed linear story.

Instead, the player explores a persistent world containing towns, wilderness, dungeons, NPCs, factions, quests, secrets, encounters, and consequences.

The player should be able to attempt essentially any reasonable action.

The game should not rely on a giant collection of hardcoded dialogue choices.

Instead:

```text
PLAYER INTENT
     ↓
GAME/RULES INTERPRETATION
     ↓
RULES ENGINE
     ↓
WORLD STATE CHANGE
     ↓
NARRATIVE RESULT
```

The AI may narrate and interpret intent, but it must never arbitrarily override deterministic game mechanics.

---

# 2. Core Design Philosophy

## 2.1 Rules First

The simulation owns mechanical truth.

The AI does not decide:

* whether an attack hits
* damage
* whether a spell works
* whether a skill check succeeds
* initiative
* character statistics
* inventory
* gold
* experience
* travel time
* death
* resurrection eligibility
* NPC health
* world-state flags

The rules engine decides these things.

The AI interprets player intent and narrates the resulting state.

---

# 3. Target Ruleset

Use D&D 3.5 / d20-style mechanics as the mechanical foundation.

Initially implement a practical subset of the 3.5 rules, but structure the code so additional rules can continuously be added.

The implementation should prioritize:

1. Ability scores
2. Ability modifiers
3. Races
4. Classes
5. Class levels
6. Multiclassing
7. Skills
8. Feats
9. Combat
10. Initiative
11. Attacks
12. Damage
13. Armor
14. Saving throws
15. Movement
16. Conditions
17. Spells
18. Spell slots
19. Equipment
20. Encumbrance
21. Experience
22. Leveling
23. Death
24. Resurrection
25. Rest
26. Travel
27. Time
28. Day/night
29. Random encounters
30. NPCs
31. Factions
32. Reputation
33. Quests
34. Loot
35. World persistence

Do not attempt to implement the entire ruleset before creating a playable campaign.

Build the rules engine incrementally.

---

# 4. Legal / Content Boundary

Use the freely available d20 System Reference Document / 3.5 SRD as the foundation for rules data.

Do not copy proprietary book text that is outside the applicable open rules material.

Keep game data separated from engine code so that rules content can be expanded or replaced independently.

---

# 5. Recommended Architecture

Use a modular Python architecture.

Do NOT build the crawler as one giant module.

Recommended structure:

```text
gnosis/
│
├── core/
│   ├── __init__.py
│   ├── dice.py
│   ├── events.py
│   ├── ids.py
│   ├── modifiers.py
│   ├── registry.py
│   ├── serialization.py
│   ├── time.py
│   └── rng.py
│
├── rules/
│   ├── __init__.py
│   ├── abilities.py
│   ├── combat.py
│   ├── checks.py
│   ├── conditions.py
│   ├── damage.py
│   ├── death.py
│   ├── experience.py
│   ├── leveling.py
│   ├── movement.py
│   ├── saving_throws.py
│   └── rules_engine.py
│
├── characters/
│   ├── __init__.py
│   ├── character.py
│   ├── party.py
│   ├── race.py
│   ├── class_definition.py
│   ├── class_level.py
│   ├── multiclass.py
│   ├── skills.py
│   ├── feats.py
│   ├── alignment.py
│   └── character_builder.py
│
├── magic/
│   ├── __init__.py
│   ├── spell.py
│   ├── spellcasting.py
│   ├── spell_slots.py
│   ├── spell_effects.py
│   └── targeting.py
│
├── items/
│   ├── __init__.py
│   ├── item.py
│   ├── weapon.py
│   ├── armor.py
│   ├── equipment.py
│   ├── inventory.py
│   ├── treasure.py
│   └── loot_tables.py
│
├── combat/
│   ├── __init__.py
│   ├── encounter.py
│   ├── initiative.py
│   ├── turn.py
│   ├── actions.py
│   ├── targeting.py
│   ├── battlefield.py
│   └── combat_log.py
│
├── world/
│   ├── __init__.py
│   ├── world.py
│   ├── region.py
│   ├── location.py
│   ├── route.py
│   ├── travel.py
│   ├── weather.py
│   ├── time_system.py
│   ├── npc.py
│   ├── faction.py
│   ├── reputation.py
│   ├── economy.py
│   └── world_state.py
│
├── quests/
│   ├── __init__.py
│   ├── quest.py
│   ├── objectives.py
│   ├── quest_manager.py
│   ├── quest_state.py
│   └── quest_hooks.py
│
├── encounters/
│   ├── __init__.py
│   ├── encounter.py
│   ├── encounter_tables.py
│   ├── random_encounters.py
│   └── encounter_generator.py
│
├── narrative/
│   ├── __init__.py
│   ├── narrator.py
│   ├── intent_parser.py
│   ├── dialogue.py
│   ├── context.py
│   └── memory.py
│
├── campaign/
│   ├── __init__.py
│   ├── campaign.py
│   ├── campaign_state.py
│   ├── history.py
│   ├── save_manager.py
│   └── checkpoints.py
│
├── data/
│   ├── races/
│   ├── classes/
│   ├── skills/
│   ├── feats/
│   ├── spells/
│   ├── weapons/
│   ├── armor/
│   ├── items/
│   ├── monsters/
│   ├── npcs/
│   ├── locations/
│   ├── encounters/
│   ├── quests/
│   └── campaigns/
│
├── cli/
│   └── ...
│
└── tests/
```

This is a starting architecture, not a requirement to implement every file immediately.

Create the structure in a way that allows modules to appear as their functionality becomes necessary.

---

# 6. Data-Driven Design

This is one of the most important requirements.

Rules and content should be data-driven wherever practical.

Do not hardcode every spell, monster, weapon, quest, NPC, etc. into Python logic.

For example:

```text
data/classes/fighter.json
data/classes/wizard.json
data/spells/magic_missile.json
data/weapons/longsword.json
data/monsters/goblin.json
```

The engine loads these definitions.

A new spell should ideally require:

```text
1. Create spell data
2. Reference existing effects
3. Register spell
```

rather than:

```text
1. Modify spell_engine.py
2. Add another if statement
3. Modify combat.py
4. Modify character.py
5. Modify UI
```

Avoid conditional spaghetti.

---

# 7. Registries

Create generic registries for extensible content.

Examples:

```python
class_registry
race_registry
spell_registry
feat_registry
skill_registry
item_registry
monster_registry
quest_registry
encounter_registry
location_registry
```

Example conceptual API:

```python
spell_registry.register(spell)
spell_registry.get("magic_missile")
spell_registry.all()
```

This allows content to be dynamically loaded.

---

# 8. Immutable Definitions vs Mutable State

Separate definitions from runtime state.

Example:

```text
SpellDefinition
        ↓
SpellInstance / EffectState
```

Likewise:

```text
ClassDefinition
        ↓
CharacterClassLevel
```

And:

```text
ItemDefinition
        ↓
ItemInstance
```

Definitions describe what something is.

Instances describe what is happening to that particular object in the campaign.

This distinction is essential for persistence.

---

# 9. Character Model

Character should contain:

```text
id
name
race
alignment
class_levels
ability_scores
hp
max_hp
damage
conditions
skills
feats
equipment
inventory
experience
level
gold
spellcasting
background
personality
relationships
reputation
history
```

Do not store derived values unnecessarily.

Instead calculate:

```python
character.armor_class()
character.attack_bonus()
character.skill_bonus("stealth")
character.fortitude_save()
character.reflex_save()
character.will_save()
character.initiative()
character.melee_damage(...)
```

The underlying state should remain authoritative.

---

# 10. Ability Scores

Implement:

```text
STR
DEX
CON
INT
WIS
CHA
```

with standard modifier calculations.

All downstream systems should consume ability modifiers rather than duplicating calculations.

Example:

```python
ability_modifier(score)
```

---

# 11. Races

Initially implement a small starting selection.

Recommended:

```text
Human
Dwarf
Elf
Half-Elf
Half-Orc
Halfling
Gnome
```

The system must support adding races without modifying character logic.

Race definitions should support:

```text
ability modifiers
size
speed
languages
racial traits
favored class
special abilities
```

---

# 12. Classes

Initial classes:

```text
Barbarian
Fighter
Rogue
Cleric
Wizard
```

Later expand.

Class definitions should support:

```text
hit die
base attack progression
saving throw progression
class skills
skill points
weapon proficiencies
armor proficiencies
class features
spellcasting
```

Do not special-case these classes inside character.py.

---

# 13. Multiclassing

Multiclassing must be supported from the beginning at the data-model level even if the first campaign doesn't heavily utilize it.

Example:

```text
Fighter 3
Rogue 2
Wizard 1
```

Represent class levels independently.

Do not represent:

```python
character.class_name = "fighter"
character.level = 6
```

Instead:

```python
[
    Fighter(levels=3),
    Rogue(levels=2),
    Wizard(levels=1)
]
```

This will make future multiclassing and prestige classes possible.

---

# 14. Skills

Skills should be independently registered.

Each skill definition can contain:

```text
name
ability
trained_only
armor_check_penalty
class_skill_by_class
special_rules
```

Initial implementation can use the standard SRD skills required for the first campaign.

Adding a skill later should not require modifying Character.

---

# 15. Feats

Feats should be data-driven.

Each feat should describe:

```text
prerequisites
bonuses
actions
passive effects
```

The rules engine evaluates whether the character qualifies.

---

# 16. Combat

Combat must be explicitly turn-based.

Order:

```text
Encounter begins
        ↓
Initiative
        ↓
Round 1
        ↓
Actor turns
        ↓
Round 2
        ↓
...
        ↓
Victory / Defeat
```

Combat state should contain:

```text
participants
initiative_order
current_round
current_actor
battlefield
positions
conditions
temporary_effects
combat_log
```

---

# 17. Initiative

Each combatant rolls initiative.

Store the result for the encounter.

Tie-breaking should be deterministic according to the ruleset.

Combat log:

```text
Initiative:
Sky        18
Aurelia    15
Goblin     13
Bran       11
```

---

# 18. Actions

Design an action system instead of hardcoding actions directly into Combat.

Examples:

```text
AttackAction
MoveAction
FullAttackAction
CastSpellAction
UseItemAction
ReadyAction
DelayAction
WithdrawAction
ChargeAction
AidAnotherAction
Dash/Move
InteractAction
```

Future combat mechanics should be able to add new actions.

---

# 19. Conditions

Conditions must be reusable and composable.

Examples:

```text
Blinded
Dazed
Dazzled
Deafened
Entangled
Exhausted
Fatigued
Frightened
Grappled
Nauseated
Panicked
Paralyzed
Poisoned
Prone
Shaken
Sickened
Stunned
Unconscious
```

Do not write:

```python
if character.is_stunned:
```

everywhere.

Prefer a generalized condition/effect system.

---

# 20. Spell System

Spells should be independently defined.

Data should include relevant properties such as:

```text
name
school
levels
casting_time
range
target
duration
saving_throw
spell_resistance
components
effect
```

The effect system should allow reusable effects.

Examples:

```text
DamageEffect
HealingEffect
BuffEffect
DebuffEffect
ConditionEffect
SummonEffect
TeleportEffect
StatModifierEffect
```

This allows many spells to reuse the same underlying mechanics.

---

# 21. Equipment

Implement:

```text
Weapons
Armor
Shields
Potions
Scrolls
Wands
Rings
Amulets
Miscellaneous items
```

Items should support:

```text
weight
value
properties
requirements
effects
equipment_slot
rarity
```

---

# 22. Inventory

Inventory should be persistent state.

Support:

```text
stackable items
equipped items
containers
weight
encumbrance
gold
item quantities
```

---

# 23. Death

Character death is permanent by default.

A character dying should become:

```text
status = DEAD
```

rather than immediately being removed.

The party then gets the possibility of resurrection.

The campaign must track:

```text
time_of_death
location_of_body
resurrection_eligibility
```

If the party cannot obtain an appropriate resurrection effect within the applicable timeframe/rules:

```text
character = permanently dead
```

This should create genuine campaign consequences.

---

# 24. Rest

Implement:

```text
Short/rest-like recovery
Full rest
Sleep
Spell preparation
HP recovery
condition recovery
```

The exact mechanics should follow the implemented 3.5 rules rather than modern D&D assumptions.

Rest should advance world time.

Rest should potentially trigger:

```text
random encounter
NPC movement
quest progression
enemy activity
weather changes
```

---

# 25. World Clock

Create a single authoritative campaign clock.

Example:

```python
CampaignTime(
    day=4,
    hour=18,
    minute=32
)
```

Everything else reads from this.

Never maintain independent clocks for towns, quests, NPCs, etc.

---

# 26. Day/Night

Support:

```text
Dawn
Morning
Afternoon
Evening
Night
Midnight
```

Time should influence:

```text
NPC availability
shop availability
town gates
random encounters
visibility
stealth
monsters
travel
rest
quests
```

---

# 27. Travel

Travel is not instantaneous.

Each route should define:

```text
origin
destination
distance
terrain
road_quality
danger_level
base_travel_time
available
discovery_state
```

Travel calculation may eventually incorporate:

```text
party movement speed
encumbrance
weather
terrain
mounts
special abilities
navigation
```

Travel should advance the campaign clock.

Example:

```text
Ravenhollow
     ↓
6 hours travel
     ↓
Blackwood
```

---

# 28. Random Encounters

Random encounters occur while traveling and potentially during wilderness rest.

Encounter probability should depend on:

```text
route
region
terrain
time
weather
party level
danger level
world state
```

Encounter types can include:

```text
combat
NPC
merchant
traveler
monster
environmental event
discovery
ambush
quest hook
treasure
stranded adventurer
weather event
```

Do not make every encounter combat.

---

# 29. World Map

The world should consist of interconnected locations.

Example initial campaign:

```text
                     OLD RUINS
                        |
                        |
                     NORTH ROAD
                        |
                        |
BLACKWOOD ---- RAVENHOLLOW ---- EAST ROAD ---- CAPITAL
    |
    |
WITCH HUT

Ravenhollow
    |
SOUTH ROAD
    |
FARMSTEAD

Ravenhollow
    |
WEST ROAD
    |
ABANDONED MINE
```

Some locations begin undiscovered or locked.

---

# 30. Location System

A location is an interactive stateful environment.

Example:

```text
Location:
Ravenhollow Tavern
```

Possible interactions:

```text
talk
rest
eat
drink
rent_room
listen_for_rumors
gamble
steal
inspect
fight
leave
```

But player intent should not be limited to this list.

The intent parser should be capable of converting freeform requests into game actions.

---

# 31. Player Freedom

The player should be allowed to attempt unconventional actions.

Example:

```text
"I intimidate the blacksmith."

"I climb onto the roof."

"I steal the mayor's horse."

"I burn the tavern."

"I ask the guard about the missing travelers."

"I attack the merchant."

"I wait until midnight."

"I follow the suspicious traveler."

"I cast Detect Magic on the statue."
```

The game determines whether the action is mechanically possible.

Never assume:

```text
not predefined option = impossible
```

Instead use:

```text
player intent
→ action resolution
→ rules
→ consequences
```

---

# 32. Action Resolver

Create an abstraction for player intent.

For example:

```python
ActionIntent(
    actor_id="player",
    action_type="attempt_theft",
    target_id="merchant_01",
    context={...}
)
```

The action resolver maps intent to mechanics.

Example:

```text
"I try to steal the merchant's dagger."
        ↓
STEAL ACTION
        ↓
Sleight of Hand
        ↓
Merchant Spot
        ↓
SUCCESS
```

---

# 33. Narrative Layer

Gnosis should act as the Dungeon Master.

It should receive:

```text
current location
current time
party state
NPC state
relevant history
player intent
rules result
```

Then produce:

```text
description
dialogue
consequence narration
new opportunities
NPC reactions
```

The model must not invent mechanical outcomes that conflict with the state supplied by the engine.

---

# 34. Suggested AI Pipeline

```text
User message
    ↓
Intent Parser
    ↓
Structured Action
    ↓
Rules / World Engine
    ↓
Result
    ↓
Event System
    ↓
Narrative Context Builder
    ↓
Gnosis LLM
    ↓
Narrative Response
```

Example:

User:

> "I tell the innkeeper I'm a royal investigator and demand a free room."

Intent:

```json
{
  "action": "deception",
  "actor": "player",
  "target": "innkeeper",
  "claim": "royal investigator",
  "desired_result": "free_room"
}
```

Rules engine performs the appropriate check.

Only then does the narrator produce the response.

---

# 35. Event System

Create a generic event architecture.

Examples:

```text
CharacterCreated
CharacterLeveled
CharacterDied
CharacterResurrected
ItemPurchased
ItemStolen
SpellCast
CombatStarted
CombatEnded
QuestStarted
QuestCompleted
QuestFailed
LocationDiscovered
NPCKilled
FactionChanged
PartyTravelStarted
PartyArrived
RestStarted
RestCompleted
```

Events should be useful for:

```text
history
quests
NPC reactions
factions
achievements
world state
narrative memory
```

---

# 36. Persistent World State

Everything important should be represented by state rather than narrative memory alone.

Examples:

```python
world.npcs["guard_17"].alive = False
world.locations["mine"].cleared = True
world.factions["thieves"].reputation = 42
world.quests["missing_travelers"].state = "completed"
```

The narrative AI can reference this state.

---

# 37. NPC Architecture

NPCs should have:

```text
id
name
race
role
location
alive
stats
inventory
faction
alignment
personality
relationships
schedule
goals
knowledge
memory
```

NPCs should eventually be able to move through the world according to schedules and events.

---

# 38. Relationships

Track relationships between characters.

For example:

```text
player → companion
friendship
trust
respect
fear
romance
resentment
loyalty
```

Companions should be characters, not merely AI combat units.

They may:

```text
approve
disapprove
argue
refuse
leave
betray
assist
sacrifice themselves
```

depending on the campaign.

---

# 39. Alignment / Mythic Progression

Do not reduce morality to one boolean.

Track behavior vectors.

Potential dimensions:

```text
law
chaos
good
evil
honor
mercy
cruelty
greed
selflessness
```

Actions modify these values.

The character's alignment can be derived from behavior.

Long-term progression:

```text
Normal Hero
     ↓
Renowned
     ↓
Legendary
     ↓
Mythic
```

and similarly for darker paths.

This system should be extensible.

---

# 40. Quests

Quests should be data-driven and stateful.

A quest might contain:

```text
id
title
description
giver
objectives
requirements
rewards
failure_conditions
expiration
state
consequences
```

Objectives should be modular:

```text
Kill
Find
Retrieve
Escort
Talk
Visit
Investigate
Survive
Deliver
Steal
Protect
Escape
Discover
```

Do not hardcode quests directly into the campaign engine.

---

# 41. Quest Hooks

Quests should be able to react to world events.

Examples:

```text
NPC dies
→ quest fails

Player discovers location
→ quest unlocks

Faction reputation reaches threshold
→ quest appears

Player steals artifact
→ new quest generated

Player kills bandit leader
→ merchant quest completes
```

Build this around events.

---

# 42. Campaign Architecture

A Campaign contains:

```text
campaign_id
name
world
party
current_time
current_location
quest_state
world_state
npc_state
faction_state
history
random_seed
```

A campaign should be serializable.

---

# 43. Deterministic RNG

Use a campaign-specific random seed.

This allows debugging and potential replay.

Example:

```python
campaign.seed = 123456
```

The game should use a centralized RNG service rather than calling Python's random functions throughout the codebase.

This is important for:

```text
reproducibility
testing
debugging
save/load
```

---

# 44. Save System

Save the entire campaign state.

Use JSON or another transparent format initially.

Example:

```text
saves/
    campaign_001/
        campaign.json
        history.json
```

Later, a database can replace the implementation without changing the campaign API.

---

# 45. Campaign History

Maintain an immutable event history.

Example:

```text
DAY 1
09:00 - Party entered Ravenhollow
09:22 - Player purchased longsword
11:04 - Party met Aldric
15:38 - Party traveled toward Blackwood
18:02 - Random encounter: wolves
18:18 - Combat ended
21:40 - Party reached Blackwood
```

History should provide context to Gnosis.

Do not pass the entire history to the LLM.

Create context summaries as the campaign grows.

---

# 46. Initial Campaign

Create one small but complete campaign for testing.

Working title:

**The Ashes of Ravenhollow**

Starting location:

```text
Ravenhollow
```

Available destinations:

```text
Blackwood
Old Ruins
Abandoned Mine
Farmstead
Capital Road
```

The campaign should contain:

```text
1 town
1 village/farmstead
1 forest
1 mine
1 ruin
1 main road
1 dangerous road
several NPCs
several shops
multiple rumors
multiple quests
random encounters
one dungeon
one major antagonist
```

Do not overbuild the campaign.

It exists to prove the engine.

---

# 47. Initial Campaign Goal

The player should be able to start with almost no predetermined direction.

Early rumors might include:

```text
Miners have disappeared.

Something strange is happening in Blackwood.

The old ruins may contain treasure.

The mayor is looking for mercenaries.

Someone has been attacking travelers.

A priest is paying for undead remains.

A merchant claims to have lost an important package.
```

The player chooses which threads to pursue.

The campaign should continue even if the player ignores the main story.

---

# 48. Initial Party

Character creation should produce:

```text
Player
Companion A
Companion B
```

The player controls all three in combat and exploration.

Companions should have different personalities and motivations.

---

# 49. First Playable Milestone

The FIRST working milestone should NOT attempt to implement the entire D&D 3.5 ruleset.

It should implement a complete gameplay loop:

```text
Create character
      ↓
Choose race
      ↓
Choose class
      ↓
Create two companions
      ↓
Enter Ravenhollow
      ↓
Explore location
      ↓
Talk to NPC
      ↓
Receive rumor / quest
      ↓
Travel
      ↓
Time passes
      ↓
Potential random encounter
      ↓
Turn-based combat
      ↓
Loot
      ↓
Return to town
      ↓
Rest
      ↓
Time passes
      ↓
Continue adventure
      ↓
Save
      ↓
Load
```

Once this loop works, expand rules and content.

---

# 50. Development Strategy

Use vertical slices.

Do NOT develop:

```text
all spells
then all classes
then all monsters
then all locations
```

Instead develop:

```text
character
+
combat
+
location
+
travel
+
quest
+
NPC
+
save
```

until one small campaign works.

Then deepen each subsystem.

---

# 51. Expansion Strategy

Every subsystem should answer:

> "How do we add another one without changing engine code?"

Examples:

Adding a class:

```text
data/classes/paladin.json
```

Adding a spell:

```text
data/spells/cure_light_wounds.json
```

Adding a monster:

```text
data/monsters/ogre.json
```

Adding a weapon:

```text
data/weapons/greataxe.json
```

Adding a quest:

```text
data/quests/missing_caravan.json
```

Adding a location:

```text
data/locations/forgotten_temple.json
```

Adding an encounter:

```text
data/encounters/forest_wolves.json
```

The engine should remain unchanged whenever possible.

---

# 52. Testing Requirements

Write unit tests for the rules engine before building large amounts of content.

At minimum:

```text
dice tests
ability modifier tests
attack tests
damage tests
AC tests
saving throw tests
skill tests
initiative tests
condition tests
spell tests
inventory tests
encumbrance tests
experience tests
leveling tests
death tests
travel-time tests
time progression tests
quest state tests
save/load tests
```

Rules must be deterministic under a seeded RNG.

---

# 53. Debug Mode

Build a developer/debug mode from the start.

It should allow:

```text
show party state
show world state
show NPC state
show active quests
show current time
force encounter
teleport
give item
give XP
kill character
revive character
set reputation
advance time
roll check
start combat
```

Do not expose this to normal players.

This will dramatically speed up development.

---

# 54. Logging

All important mechanical decisions should be logged.

Example:

```text
[COMBAT]
Sky attacks Goblin

d20 = 17
BAB = +2
STR = +3
Weapon = +1

Attack total = 23
Goblin AC = 16

RESULT: HIT

Damage:
1d8 = 5
STR = +3
enhancement = +1

TOTAL = 9
```

This is invaluable for debugging both the rules engine and Gnosis explanations.

---

# 55. API Boundaries

Keep Gnosis integration behind an interface.

For example:

```python
class Narrator:
    def narrate_event(...)
    def describe_location(...)
    def respond_to_dialogue(...)
    def interpret_player_intent(...)
```

The crawler must still function mechanically without an LLM.

This makes testing possible and allows different models later.

---

# 56. Future Model Compatibility

Do not hardwire the crawler to a particular LLM.

The narrative layer should support:

```text
Ollama
OpenAI-compatible APIs
local models
cloud models
future Gnosis models
```

The crawler should only require an abstract interface.

---

# 57. Long-Term Content Roadmap

After the first campaign works, gradually expand:

## Phase 1

Core mechanics.

## Phase 2

More classes and races.

## Phase 3

More spells.

## Phase 4

More monsters.

## Phase 5

Expanded equipment.

## Phase 6

More locations.

## Phase 7

More factions.

## Phase 8

Companion relationships.

## Phase 9

Economy.

## Phase 10

Crafting.

## Phase 11

Advanced magic.

## Phase 12

Prestige classes.

## Phase 13

Epic progression.

## Phase 14

More campaigns.

## Phase 15

Procedural world generation.

---

# 58. What NOT to Do

Do not:

* build everything into one Python file
* put game logic in the UI
* allow the LLM to determine mechanical outcomes
* hardcode every quest
* hardcode every spell
* hardcode every NPC
* make locations disposable
* make travel instantaneous
* ignore time
* make random encounters exclusively combat
* make companions simple stat blocks
* make death meaningless
* store derived character statistics as authoritative state
* couple campaign data directly to a particular model
* assume the first implementation is the final architecture

---

# 59. First Claude Task

Claude's initial task is to create the scaffolding and foundational abstractions.

Do NOT attempt to implement the entire game in the first pass.

The first implementation should produce:

```text
project structure
configuration
core interfaces
registries
serialization
dice/RNG
basic character model
basic party model
basic race model
basic class model
basic inventory
basic campaign state
world/location model
time model
event system
combat skeleton
quest skeleton
narrative interface
tests
developer CLI
```

All major systems should have clean interfaces even if the first implementation is minimal.

---

# 60. Second Claude Task

Once scaffolding is generated:

Implement:

```text
Ability scores
Races
Fighter
Rogue
Barbarian
Cleric
Wizard
Skills
Basic feats
Weapons
Armor
Basic spells
Initiative
Attack
Damage
HP
Death
Rest
Experience
Leveling
Inventory
```

---

# 61. Third Claude Task

Implement the first vertical slice:

```text
Ravenhollow
NPCs
Inn
Blacksmith
Temple
Market
Mayor
Travel routes
Blackwood
Old Mine
Old Ruins
Random encounters
Basic quests
Basic dungeon
Save/load
```

---

# 62. Fourth Claude Task

Connect Gnosis narrative intelligence:

```text
player input
→ intent extraction
→ action resolution
→ rules
→ world events
→ narrative generation
```

At this stage the crawler becomes an actual interactive AI-powered tabletop-like game.

---

# 63. Quality Bar

The project should eventually make this interaction possible:

Player:

> I want to leave the tavern, wait until midnight, sneak around the eastern side of town, climb the wall, and investigate the old watchtower.

The engine should be able to determine:

```text
leave tavern
advance time
time reaches midnight
stealth conditions change
navigation
movement
climb check
location discovery
possible encounter
```

without requiring a developer to create a special "investigate-watchtower-at-midnight" command.

That is the ultimate design goal.

---

# 64. Core Principle

The game should feel like:

> "I wonder if I can do this."

rather than:

> "Which button represents the thing I want to do?"

The rules engine provides boundaries.

The world provides consequences.

The AI provides interpretation and storytelling.

The player provides the story.

---

# 65. Initial Success Definition

The project is successful when a player can:

1. Create a D&D-style character.
2. Create two companions.
3. Enter a persistent world.
4. Explore locations.
5. Speak naturally to NPCs.
6. Travel between locations.
7. Experience actual passage of time.
8. Encounter random events.
9. Fight turn-based battles using initiative.
10. Use equipment, skills, feats, and spells.
11. Gain experience and levels.
12. Die and potentially be resurrected.
13. Complete or ignore quests.
14. Make morally meaningful decisions.
15. Return to previous locations.
16. Change the world.
17. Save the campaign.
18. Load the campaign later.
19. Continue pursuing whatever story they choose.

Everything after that is expansion.

Build the engine so expansion is expected, not exceptional.
