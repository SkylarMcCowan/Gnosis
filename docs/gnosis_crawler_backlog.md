# Gnosis Crawler — Development Backlog

Phases → sprints → tickets, sequenced so each ticket is executable on
its own and unblocks the next. Ticket IDs (`GC-NNN`) are stable
references to use in commits/branches. Execution has started — Phase 0
(GC-001–GC-022) and the GUI wiring (GC-070) are done; ✅ marks below
track progress as later tickets land.

**Naming note:** the implementation package is `ethereal_dnd/`, not
`gnosis/` as the main design doc's Section 5 tree literally names it —
this repo is already the "Gnosis" app, so the engine took the GUI panel's
own name instead to avoid colliding with that. The Qt side panel is
"🐉 Ethereal DND" in the nav, backed by `ethereal_dnd_widget.py` at the
repo root (Qt layer only) over the pure-Python `ethereal_dnd/` engine
package.

Companion docs:
- [gnosis_crawler.md](gnosis_crawler.md) — full architecture & vision
- [gnosis_crawler_alignment.md](gnosis_crawler_alignment.md) — deity/alignment
  compliance ("falling from grace") design, referenced by Phase 1.5 below
- [srd_reference/](srd_reference/) — local offline copy of the D&D 3.5 SRD
  (Open Game Content), imported so tickets can cite exact rules text
  without a live web request per lookup. See
  [srd_reference/SOURCED.md](srd_reference/SOURCED.md) for exactly what's
  in there (it's essentially the full PHB+DMG+MM already, plus Epic/
  Psionics material) before assuming a ticket needs new research, and
  [srd_reference/SOURCING_GUIDE.md](srd_reference/SOURCING_GUIDE.md) for
  how to pull in something that genuinely isn't covered yet.

Detail level is intentionally uneven on purpose, per the source doc's own
"do not overbuild" guidance (Sections 46/50): **Phases 0–3 are broken into
real tickets** because that's what gets executed first. **Phase 4+
(content expansion) is left as sprint-level stubs** — breaking those into
tickets now would mean inventing detail about spells/monsters/prestige
classes we don't need yet; they get ticketed when that phase is actually
reached.

Sizes: **S** = under an hour of focused work, **M** = a session, **L** =
multiple sessions / should probably be split further when picked up.

---

## Phase 0 — Scaffolding

Matches the source doc's "First Claude Task" (Section 59). Produces the
skeleton every later phase builds on. No game content, no rules depth, no
LLM wiring.

### Sprint 0.1 — Project skeleton & core infra ✅ done

- **GC-001** (S) — ✅ Created the `ethereal_dnd/` package tree (see the
  naming note above — not `gnosis/` as
  [Section 5](gnosis_crawler.md#5-recommended-architecture) literally
  names it) with `core/`, `characters/`, `items/`, `world/`, `campaign/`,
  `combat/`, `quests/`, `narrative/`, `cli/`, each with an empty
  `__init__.py`. Skipped creating empty `data/` subdirectories for now —
  they'll come into existence naturally once GC-024/GC-026 actually
  write JSON into them; an empty dir with nothing pointing at it yet
  isn't worth the ceremony. `tests/` uses this repo's existing top-level
  `tests/` convention (`tests/test_ethereal_dnd_*.py`), not a nested
  package-local tests dir.
- **GC-002** (S) — ✅ `core/ids.py`: a single `new_id()` helper (uuid4-based,
  matching the pattern already used elsewhere in the repo, e.g.
  `worklog.py`'s `uuid` usage) so every model gets IDs the same way.
- **GC-003** (M) — ✅ `core/dice.py` + `core/rng.py`: a `roll(expr: str)`
  parser for standard dice notation (`1d20+3`, `2d6`, `4d6kh3` for
  ability-score generation), backed by a centralized, campaign-seeded RNG
  service (Section 43) — nothing in the engine calls `random` directly.
  Depends on: GC-001.
- **GC-004** (M) — ✅ `core/registry.py`: one generic `Registry` class
  (`register`, `get`, `all`, duplicate-id guard) used for every content
  type in Section 7. `class_registry`, `race_registry`, `skill_registry`,
  `feat_registry`, and `item_registry` instances exist now; `deity_registry`
  is created by GC-044 when the `Deity` model itself lands (Phase 1.5) —
  the generic `Registry` class doesn't need to know about deities ahead
  of that. Depends on: GC-001.
- **GC-005** (M) — ✅ `core/serialization.py`: `to_dict()`/`from_dict()`
  conventions (or a small dataclass-based (de)serializer) used by every
  definition/instance pair (Section 8) and by `campaign/save_manager.py`
  later. Depends on: GC-001.
- **GC-006** (M) — ✅ `core/events.py`: a minimal synchronous event bus
  (`emit(event)`, `subscribe(event_type, handler)`) plus the `Event` base
  type and the full event catalog from Section 35 as concrete dataclasses
  (empty payloads are fine for now). Depends on: GC-001.
- **GC-007** (S) — ✅ `core/time.py`: `CampaignTime` (day/hour/minute),
  arithmetic (`advance(hours=...)`), and the day/night period lookup from
  Section 26. Depends on: GC-001.
- **GC-008** (S) — ✅ `core/modifiers.py`: a generic stacking-modifier
  container (named bonuses/penalties with a source, so AC/attack/skill
  totals can later show *why* a number is what it is — feeds the
  Section 54 logging format). Depends on: GC-001.

### Sprint 0.2 — Minimal domain models (interfaces only)

- **GC-009** (M) — ✅ `characters/character.py`: bare `Character` dataclass
  with the full field list from Section 9, and stub methods
  (`armor_class()`, `attack_bonus()`, etc.) that raise
  `NotImplementedError` — the *shape* of the API, not the math yet.
  Depends on: GC-002, GC-005.
- **GC-010** (S) — ✅ `characters/party.py`: `Party` holding up to 3
  `Character`s (Section 48). Depends on: GC-009.
- **GC-011** (S) — ✅ `characters/race.py` + register into
  `race_registry`: `RaceDefinition` shape from Section 11, no race data
  yet. Depends on: GC-004, GC-009.
- **GC-012** (M) — ✅ `characters/class_definition.py` +
  `characters/class_level.py` + `characters/multiclass.py`: the
  `ClassDefinition` shape from Section 12, and `Character.class_levels`
  represented as the list-of-`ClassLevel` structure from Section 13 (not
  a single class/level pair). Depends on: GC-004, GC-009.
- **GC-013** (S) — ✅ `characters/skills.py` + `characters/feats.py`:
  registry-backed definition shapes from Sections 14–15, no content.
  Depends on: GC-004.
- **GC-014** (S) — ✅ `characters/alignment.py`: the `AlignmentVector` shape
  from the [alignment doc §3](gnosis_crawler_alignment.md#3-data-model)
  (fields only, `derived_alignment()` stubbed). Depends on: GC-009.
- **GC-015** (S) — ✅ `items/item.py` + `items/inventory.py`: minimal
  `ItemDefinition`/`ItemInstance` split (Section 8) and an `Inventory`
  container (Section 22) with no weight/encumbrance math yet.
  Depends on: GC-004, GC-005.
- **GC-016** (M) — ✅ `world/location.py` + `world/world.py`: `Location`
  and `World` shapes (Section 30), a `World` being a graph of `Location`s
  connected by `world/route.py` `Route`s (Section 27), no travel-time math
  yet. Depends on: GC-004, GC-005.
- **GC-017** (S) — ✅ `campaign/campaign_state.py` +
  `campaign/campaign.py`: the `Campaign` shape from Section 42 wiring
  together `World`, `Party`, `CampaignTime`, and a `random_seed`.
  Depends on: GC-007, GC-010, GC-016.
- **GC-018** (S) — ✅ `combat/encounter.py` interface stub (participants,
  initiative_order, current_round — Section 16 shape, no resolution
  logic). Depends on: GC-009.
- **GC-019** (S) — ✅ `quests/quest.py` interface stub (Section 40 field
  list, no state machine logic yet). Depends on: GC-004, GC-005.
- **GC-020** (S) — ✅ `narrative/narrator.py`: the abstract `Narrator`
  interface from Section 55 (`narrate_event`, `describe_location`,
  `respond_to_dialogue`, `interpret_player_intent`) plus one trivial
  `NullNarrator` implementation that returns canned strings — proves the
  engine runs with zero LLM dependency. Depends on: GC-006.
- **GC-021** (M) — ✅ `cli/` developer CLI (Section 53's debug-mode list, at
  least: show party state, show world state, show current time, advance
  time, roll check) wired against the Phase 0 stubs — this is what proves
  the scaffolding actually boots end-to-end. Depends on: GC-009 through
  GC-020.
- **GC-022** (M) — ✅ `tests/test_ethereal_dnd_core.py`: round-trip tests
  for `core/dice.py` (seeded determinism), `core/registry.py`
  (register/get/duplicate-guard), `core/serialization.py`
  (to_dict/from_dict identity), and `core/time.py` (advance/day-night
  boundary) — 20 tests. Added beyond ticket scope:
  `tests/test_ethereal_dnd_models.py` (Sprint 0.2 model shapes — Party
  size cap, alignment derivation, inventory, world graph) and
  `tests/test_ethereal_dnd_cli.py` (GC-021's functions). 37 tests total,
  all passing. Depends on: GC-003, GC-004, GC-005, GC-007.

**Phase 0 exit criteria: ✅ met.** `ethereal_dnd/cli/debug_cli.py` boots,
creates a `Campaign` with an empty `Party` in an empty `World`, advances
time, and rolls dice deterministically per campaign seed; every Sprint
0.2 module imports without circular-dependency errors (verified both via
`python3 -c` smoke test and the full pytest run). No game content is
playable yet — that's Phase 2.

- **GC-070** (M) — ✅ *(new, not originally ticketed — added when the
  user asked to wire this into the GUI ahead of schedule)* Qt side panel:
  `ethereal_dnd_widget.py` at the repo root (`EtherealDndWidget`, Qt
  layer only — imports `ethereal_dnd.cli.debug_cli`'s plain functions,
  same split as `worklog.py`/`hacker.py` between logic and Qt layers),
  wired into `webagent_gui.py`'s nav as "🐉 Ethereal DND" (13th page).
  Buttons: New Campaign, Show Party, Show World, Show Time, Advance 1
  Hour, and a free-text dice-roll box — all backed by one in-memory
  `Campaign` per widget instance, no save/load (that's GC-062, still
  pending). Updated `tests/test_gui_pages.py`'s hardcoded page count
  (12→13) accordingly. Depends on: GC-021.

---

## Phase 1 — Core Rules Mechanics ✅ done

Matches "Second Claude Task" (Section 60). This is where the rules engine
actually starts producing real numbers.

**Deviations from the original ticket text, made during implementation:**
- `Character.inventory_id: str | None` (Phase 0's stub) became
  `Character.inventory: Inventory` (an embedded live object). An id
  needing a lookup only makes sense for shared, registry-backed content
  (Section 8's "definitions"); a character's inventory is pure per-
  character instance state, so embedding it directly — the same way
  `Party`/`World` embed their own live sub-objects — removed a lookup
  mechanism that had nowhere to look things up *from*.
- `Character.melee_damage(weapon_id, rng_service)` gained the
  `rng_service` parameter the original Phase 0 stub signature didn't
  have (every roll must go through the campaign's seeded RNG, so the
  method needs one), and returns the same detail dict shape as
  `core.dice.roll_detailed()` (rolls/kept/modifier/total) instead of a
  bare `int`, so `combat/combat_log.py` can render the Section 54
  breakdown without re-deriving it.
- `Campaign` gained an `events: EventBus` field (not in Phase 0's
  original shape) — GC-038/GC-039 need somewhere to actually emit
  `CharacterLeveled`/`CharacterDied` into, and Section 35's event bus
  was sitting unused without a campaign-level instance.
- The ability-score point-buy costs (GC-023) and the character-level XP
  table (GC-038) are **not** part of the core SRD's declared Open Game
  Content (`docs/srd_reference` has no chapter for either) — both are
  cross-checked against well-known secondary sources rather than pulled
  from the local corpus, flagged in code comments
  (`characters/abilities.py`, `characters/leveling.py`) the same way
  GC-041 flagged the alignment rules before they were verified.

### Sprint 1.1 — Abilities, races, skills ✅ done

- **GC-023** (S) — ✅ `characters/abilities.py`: `ability_modifier(score)`,
  `roll_ability_scores()` (4d6-drop-lowest, via the existing `4d6kh3`
  dice notation), and `point_buy_cost()`/`validate_point_buy()` for the
  25-point buy variant (see the provenance note above). `Character`
  reads scores via `get_ability_score()`/`ability_modifier()`, which
  raise `MissingAbilityScoreError` rather than defaulting to 10 — an
  unset score is a bug to catch, not a value to guess. Depends on:
  GC-003, GC-009.
- **GC-024** (M) — ✅ `ethereal_dnd/data/races/*.json` for all 7 starting
  races, sourced verbatim from `docs/srd_reference/core/Races.md`
  (ability modifiers, size, speed, languages, racial traits, favored
  class), loaded into `race_registry` via `characters/race.py`'s
  `load_races()` (idempotent — safe to call once per campaign or once
  per test). Depends on: GC-011.
- **GC-025** (M) — ✅ All 36 core SRD skills (`ethereal_dnd/data/skills/
  *.json`, sourced from `docs/srd_reference/core/SkillsI.md`,
  `SkillsII.md`'s own headers — including `Use Rope`, which that
  fan-conversion filed under a plain-text heading `load_skills()`'s
  source grep initially missed). `Character.skill_bonus()` implements
  ranks + ability modifier + armor-check-penalty (doubled for Swim, per
  the sourced text), and raises `UntrainedSkillError` for a trained-only
  skill with 0 ranks rather than returning a number that implies the
  check is legal. Depends on: GC-013, GC-023.

### Sprint 1.2 — Classes & multiclassing ✅ done

- **GC-026** (L) — ✅ `ethereal_dnd/data/classes/{barbarian,fighter,
  rogue,cleric,wizard}.json`, every field (hit die, BAB/save
  progression, class skills, skill points, weapon/armor proficiencies,
  spellcasting table for Cleric/Wizard) sourced verbatim from
  `docs/srd_reference/core/ClassesI.md`/`ClassesII.md` and cross-checked
  against `characters/progression.py`'s BAB/save formulas at every
  level in the actual sourced tables (not just spot-checked). Depends
  on: GC-012, GC-025.
- **GC-027** (M) — ✅ `characters/multiclass.py`'s `add_class_level()`
  (Phase 0 stub, unchanged) + `Character.base_attack_bonus()` and the
  three save methods, which sum each class's *own* progression formula
  at that class's levels (the real 3.5 multiclass rule — BAB/saves are
  computed per class-level chunk and added together, not derived from
  total character level against one table). Depends on: GC-026.

### Sprint 1.3 — Combat core ✅ done

- **GC-028** (M) — ✅ `combat/initiative.py`'s `roll_initiative()`: d20 +
  Dex modifier per participant, ties broken by modifier then by id for
  full determinism. Depends on: GC-018, GC-023.
- **GC-029** (L) — ✅ `combat/actions.py`'s `resolve_attack()`: attack
  roll (with natural-1-always-misses/natural-20-always-hits) vs. target
  AC, then a damage roll on a hit, logged via `combat/combat_log.py` in
  the Section 54 format. Depends on: GC-026, GC-028.
- **GC-030** (M) — ✅ `Character.armor_class()`, backed by
  `effective_dex_bonus_to_ac()` (the Dex-vs-max-Dex-cap math, exposed
  separately so `resolve_attack()` can subtract exactly that amount when
  a condition removes Dex-to-AC, rather than recomputing an uncapped
  ability modifier). Depends on: GC-023.
- **GC-031** (M) — ✅ `fortitude_save()`/`reflex_save()`/`will_save()`,
  each class's own progression + the matching ability modifier, summed
  across every class level the same way BAB is (GC-027). Depends on:
  GC-026.
- **GC-032** (L) — ✅ `combat/conditions.py`: Shaken/Frightened (flat -2
  to all rolls), Stunned (-2 AC, loses Dex-to-AC, can't act),
  Unconscious (can't act), and Prone (directional — its own functions,
  since attacker-vs-defender and melee-vs-ranged effects don't fit the
  flat `ConditionEffect` shape the other four use) — all sourced
  verbatim from `docs/srd_reference/core/AbilitiesandConditions.md`.
  Depends on: GC-006, GC-009.
- **GC-033** (M) — ✅ `combat/actions.py`: `full_attack()` (using
  `attack_sequence()`'s iterative-attack-bonus generator, verified
  against the literal "+16/+11/+6/+1" notation in the sourced class
  tables), `move_action()`, `withdraw_action()` (both log-only — no
  battlefield/grid model yet), and `aid_another_action()` (returns a
  `+2` bonus for the caller to apply to the ally's next roll, rather
  than modeling it as an ongoing `Condition`, since the bonus is scoped
  to one specific next roll rather than a duration to track). Depends
  on: GC-029.

### Sprint 1.4 — Equipment & inventory ✅ done

- **GC-034** (M) — ✅ 12 weapons (`ethereal_dnd/data/weapons/*.json`) and
  10 armor/shields (`ethereal_dnd/data/armor/*.json`) covering what the
  5 starting classes are actually proficient with, sourced verbatim from
  `docs/srd_reference/core/Equipment.md`'s Table: Weapons and Table:
  Armor and Shields. `load_items()` loads both directories into one
  `item_registry`. Depends on: GC-015, GC-030.
- **GC-035** (S) — ✅ `items/encumbrance.py`: the full Strength 1-29
  carrying-capacity table plus the documented "Tremendous Strength"
  extension formula for higher scores, sourced verbatim from
  `docs/srd_reference/extra/CarryingandExploration.md` (the table
  actually runs to 29, not just the first 20 rows glanced at initially).
  Depends on: GC-034.

### Sprint 1.5 — Spells ✅ done

- **GC-036** (M) — ✅ `magic/spell_slots.py`'s `spells_per_day()`, reading
  the per-class `spellcasting.spells_per_day` table already stored in
  each class's JSON (GC-026) — Cleric/Wizard tables sourced verbatim
  from `docs/srd_reference/core/ClassesI.md`/`ClassesII.md`. The
  domain-spell "+1" a real cleric gets isn't modeled (Section 12's
  Deity/Domain system isn't built yet), documented in the module
  docstring rather than silently omitted. Depends on: GC-026.
- **GC-037** (L) — ✅ `magic/spell_effects.py`: `DamageEffect`,
  `HealingEffect`, `BuffEffect`, `ConditionEffect` as composable
  primitives, plus a 5th, `UtilityEffect` (not one of Section 20's four
  named examples — added because Detect Magic doesn't fit any of them).
  `ethereal_dnd/data/spells/{magic_missile,cure_light_wounds,bless,
  detect_magic}.json`, every mechanical number (missile scaling, heal
  dice + level cap, buff bonus/duration) sourced verbatim from
  `docs/srd_reference/extra/SpellsM-O.md`/`SpellsC.md`/`SpellsA-B.md`/
  `SpellsD-E.md`. Depends on: GC-032, GC-036.

### Sprint 1.6 — XP, leveling, death, rest ✅ done

- **GC-038** (S) — ✅ `characters/leveling.py`: `xp_required_for_level()`/
  `level_for_xp()` (see the provenance note above) and
  `award_experience()`, which emits `CharacterLeveled` once per level
  actually crossed (not once per call) via `Campaign.events`. Depends
  on: GC-006, GC-027.
- **GC-039** (M) — ✅ `characters/death.py`'s `apply_damage()`: HP ≤ 0 →
  `Character.die()` (records `time_of_death`/`location_of_death`) +
  `CharacterDied` emitted, idempotent (further damage to a corpse
  doesn't re-trigger it). Resurrection is still Phase 2 work. Depends
  on: GC-006, GC-009.
- **GC-040** (M) — ✅ `campaign/rest.py`'s `rest()`: 1 HP/level for a full
  night (8 hrs), 2 HP/level for complete bed rest (24 hrs) — the exact
  sourced rule from `docs/srd_reference/core/CombatI.md`'s "Healing"
  section — plus clearing Phase 1's round-scoped conditions (spell
  re-preparation isn't modeled yet; nothing consumes spell slots in
  combat yet either) and a `post_rest_hooks` list Phase 2 can append
  random-encounter/NPC-movement callbacks onto. Depends on: GC-007,
  GC-032, GC-036.

**Phase 1 exit criteria: ✅ met**, locked in by
`tests/test_ethereal_dnd_phase1_exit_criteria.py`: two characters fight
a scripted combat encounter to a win/loss via
`ethereal_dnd/cli/debug_cli.py`'s `run_scripted_duel()`, every roll
logged in the Section 54 format, byte-for-byte identical transcripts
under a repeated seed and a different transcript under a different seed.
Also wired into the GUI (`ethereal_dnd_widget.py`'s "⚔️ Scripted Duel"
button) so the same fight is runnable without touching a test file.

---

## Phase 1.5 — Alignment & Deity Compliance Engine ✅ done

New subsystem, not in the original roadmap — added per your "falling from
grace" requirement. Full design in
[gnosis_crawler_alignment.md](gnosis_crawler_alignment.md). Sequenced
after Phase 1 because it needs real classes (paladin/cleric contracts) and
the event system, but before Phase 2's vertical slice so Ravenhollow can
actually feature a paladin or cleric companion whose faith matters.

**Deviations from the original ticket text, made during implementation:**
- **Paladin, Druid, and Monk didn't exist as classes yet** — Phase 1's
  Sprint 1.2 only built the 5 starting classes (barbarian, fighter,
  rogue, cleric, wizard), but GC-049's own test scenarios need a paladin
  and a monk to exist. Added all three now (`ethereal_dnd/data/classes/
  {paladin,druid,monk}.json`), sourced verbatim from
  `docs/srd_reference/core/ClassesI.md`/`ClassesII.md` the same way the
  original 5 were — ahead of Phase 4 ("More classes"), not instead of it.
- **New top-level `ethereal_dnd/divine/` package** (`deity.py`,
  `standing.py`, `compliance.py`, `atonement.py`, `setup.py`) rather than
  folding everything into `characters/` — `Deity`/`ComplianceRule`
  evaluation is a self-contained subsystem the same way `combat/` and
  `magic/` are, not PC-shape data.
- **`ClassDefinition.alignment_restriction` is a `list[dict]`, not a
  single dict** (Phase 1's stub had it as `dict | None`) — a paladin
  falls on any of *three* independent triggers (ceasing to be LG, one
  willful evil act, or a gross code violation), which doesn't fit one
  rule.
- **Evaluation is reactive, not automatic on construction** — per the
  alignment doc §4 ("on every event... not on a timer"), a character
  built with a pre-set alignment and just added to the party is *not*
  auto-checked; something must emit `CommittedEvilAct`/`CommittedGoodAct`/
  `BrokeCodeOfConduct`, or the caller calls
  `divine.compliance.evaluate_character()` directly (e.g. after loading a
  save, or recruiting a companion). Found by writing GC-049's own tests —
  two of them initially "passed" by accident because their expected
  result (`fallen=False`) matched the untouched default state without the
  evaluator ever running.
- **Real bug fix in `characters/alignment.py`**: the new
  `law_chaos_label()`/`good_evil_label()` methods (lowercase, for
  programmatic comparison) initially inherited a private helper's
  hardcoded `"Neutral"` (capitalized) for the neutral case, breaking
  every deity-relative comparison the moment either axis landed in the
  neutral band. Fixed to return lowercase consistently; `derived_alignment()`
  (the title-case display string) is unaffected since it already
  `.capitalize()`s its inputs.
- **`spells_per_day_for(character, class_id)`** added to
  `magic/spell_slots.py` alongside the existing `spells_per_day(class_id,
  level)` — the concrete ability gate GC-047 asked for: returns all
  zeros if `character.can_use_class_powers(class_id)` is `False`.

- **GC-041** (M) — ✅ **Done.** SRD research pass: pull the *exact*
  alignment-restriction and code-of-conduct text for Paladin, Cleric
  (deity one-step rule, plus the stricter neutrality clause), Druid,
  Monk, and Barbarian. Landed as two things: a full offline SRD corpus at
  [docs/srd_reference/](../docs/srd_reference/) (imported so later
  tickets can grep local files instead of hitting live SRD mirrors,
  several of which block automated fetches) and the verbatim quotes +
  citations in [gnosis_crawler_alignment.md §1a](gnosis_crawler_alignment.md#1a-exact-srd-wording-ticket-gc-041-done).
  Two corrections to the original table came out of this: the cleric
  neutrality clause is stricter than plain one-step math, and Druid/
  Barbarian each keep a different, wider set of abilities on violation
  than a generic `["proficiencies"]` — both folded into §1a and the §3
  data model. Depends on: none (pure research, ran in parallel with
  Phase 1).
- **GC-042** (S) — ✅ Decision recorded in
  [gnosis_crawler_alignment.md §2](gnosis_crawler_alignment.md#2-your-specific-case):
  Blackguard is expansion-phase content (Phase 14), not part of the
  initial roster — it's a prestige class needing Phase 4's prerequisite
  system, and the compliance engine is fully demonstrable without it.
  Depends on: GC-041.
- **GC-043** (M) — ✅ `characters/alignment.py`'s `derived_alignment()`
  was already real (built ahead of schedule during Phase 0/1 for
  `debug_cli.show_party()`); added `law_chaos_label()`/
  `good_evil_label()` (lowercase, for the compliance engine's
  programmatic checks) and fixed the case-mismatch bug that surfaced
  (see the deviations note above). `characters/alignment_tracker.py`'s
  `attach_alignment_tracker()` is the behavior-vector update hook,
  subscribing `CommittedEvilAct`/`CommittedGoodAct` and nudging
  `good_evil` (clamped to ±100). Depends on: GC-014, GC-006.
- **GC-044** (M) — ✅ `ethereal_dnd/divine/deity.py`'s `Deity` +
  `deity_registry` + `load_deities()`, and 3 original deities for the
  Ravenhollow setting (`ethereal_dnd/data/deities/{aurelia,sylvanis,
  mordrekar}.json` — LG/N/NE, covering every alignment band the starting
  classes' contracts need to be testable against). `code_of_conduct` is
  real in the data model but empty on all three for now — see the
  Non-goals-style note in `deity.py`'s docstring; only the class-level
  contracts are wired to actual triggers this pass. Depends on: GC-004,
  GC-041.
- **GC-045** (L) — ✅ `ComplianceRule` lives as plain dicts (no separate
  Python class — a `ClassAlignmentContract` wrapper would have added
  nothing over `ClassDefinition.alignment_restriction: list[dict]`
  itself), evaluated by `divine/compliance.py`'s `_is_violated()`
  dispatcher (`exact_alignment` / `deity_relative` / `axis_requirement` /
  `axis_forbidden` / `event_pattern` check kinds). Real rule data for
  all 5 classes in their own JSON files (barbarian/cleric/druid/monk/
  paladin). Depends on: GC-041, GC-043, GC-044.
- **GC-046** (L) — ✅ `divine/compliance.py`'s `evaluate_character()`
  (alignment_deviation rules) and `evaluate_event()` (event_pattern
  rules), wired to `campaign.events` by `divine/setup.py`'s
  `attach_alignment_and_compliance()` — subscribing the GC-043 tracker
  *before* the evaluator on the same events, so a single
  `CommittedEvilAct` both moves the vector and gets checked against it
  within one `emit()` call. Emits `ClassPowersRevoked` (and
  `ClassPowersRestored` for the realignment auto-clear path — a new
  event beyond what this ticket asked for, needed to make the monk/
  barbarian restoration path observable the same way revocation is).
  Depends on: GC-045.
- **GC-047** (M) — ✅ `Character.can_use_class_powers(class_id)` is the
  gate; `magic/spell_slots.py`'s `spells_per_day_for(character,
  class_id)` is the first (and, this pass, only) real consumer of it —
  smite/aura aren't implemented as callable mechanics yet (they're
  `class_features` string labels, same as `rage` on Barbarian), so
  there's nothing else concrete to gate until those land. Depends on:
  GC-046, GC-037.
- **GC-048** (M) — ✅ `divine/atonement.py`'s `restore_class_powers()`
  (explicit, raises `NotFallenError` if called on a class that isn't
  actually fallen — atoning twice is a caller bug, not a no-op). The
  monk/barbarian "realignment" path needs no separate function — it
  auto-clears inside `evaluate_character()` itself the moment the
  trigger stops being violated, per §5's "no ritual needed." Depends on:
  GC-046.
- **GC-049** (M) — ✅ `tests/test_ethereal_dnd_alignment_compliance.py`,
  21 tests covering all 4 scenarios plus deity data, the tracker, and
  atonement edge cases (double-atoning, atonement not self-reversing on
  alignment drift, a deity-less cleric never being flagged). Depends on:
  GC-047, GC-048.

**Phase 1.5 exit criteria: ✅ met.** `debug_cli.commit_evil_act()` forces
a `CommittedEvilAct` on a paladin companion and shows their powers
actually disappear (`show_divine_standing()`'s before/after transcript),
with no LLM involved anywhere in the call chain — also wired into the
GUI as the "⚖️ Paladin Alignment Demo" button.

---

## Phase 2 — World & Vertical Slice ✅ done

Matches "Third Claude Task" (Section 61): *The Ashes of Ravenhollow*
(Section 46).

**Deviations from the original ticket text, made during implementation:**
- **Monsters and NPCs are both just `Character`**, built via
  `world/npc.py`'s `build_npc()` / `encounters/monster_factory.py`'s
  `spawn_monster()` from data files, rather than a separate parallel
  stat-block system — reusing the same BAB/save/AC math PCs use, backed
  by two new "classes" (`animal`, `undead` Hit-Dice types, sourced from
  `docs/srd_reference/extra/TypesSubtypesAbilities.md`) alongside the 5
  real NPC classes (Adept/Aristocrat/Commoner/Expert/Warrior, sourced
  from `NPCClasses.md`). Verified against the sourced Wolf stat block
  exactly (AC, BAB, all three saves, HP all matched; only the listed
  attack bonus is 1 lower, because Weapon Focus isn't a modeled feat
  effect yet).
- **`characters/hit_points.py` needed a second formula**,
  `average_monster_hp()` — Monster Manual stat blocks average *every*
  Hit Die evenly, unlike the PC/NPC-class convention (`average_max_hp()`)
  of maxing the first level's die. Conflating them was the first bug
  hit while building the Wolf.

- **Monsters and NPCs are both just `Character`**, built via
  `world/npc.py`'s `build_npc()` / `encounters/monster_factory.py`'s
  `spawn_monster()` from data files, rather than a separate parallel
  stat-block system — reusing the same BAB/save/AC math PCs use, backed
  by two new "classes" (`animal`, `undead` Hit-Dice types, sourced from
  `docs/srd_reference/extra/TypesSubtypesAbilities.md`) alongside the 5
  real NPC classes (Adept/Aristocrat/Commoner/Expert/Warrior, sourced
  from `NPCClasses.md`). Verified against the sourced Wolf stat block
  exactly (AC, BAB, all three saves, HP all matched; only the listed
  attack bonus is 1 lower, because Weapon Focus isn't a modeled feat
  effect yet).
- **`characters/hit_points.py` needed a second formula**,
  `average_monster_hp()` — Monster Manual stat blocks average *every*
  Hit Die evenly, unlike the PC/NPC-class convention (`average_max_hp()`)
  of maxing the first level's die. Conflating them was the first bug
  hit while building the Wolf.
- **`EventBus` gained `subscribe_all()`** (Phase 0's shape only had
  per-type `subscribe()`) — GC-063's history log needs to hear every
  event, not one type at a time.
- **`Campaign` gained a `history: list[str]` field** for the same
  reason, populated by the new `campaign/history.py`, not by `Campaign`
  itself.
- **`NPC` gained a `stock: list[str]` field** (not in the original
  Section 37 shape) — GC-051 needed *some* way to say which NPCs are
  shops and what they sell; empty stock means "not a shop," and a real
  bug shipped-then-caught here: the first version treated an *empty*
  stock list as "sells anything," backwards from the intent, until a
  test (`test_buy_from_a_non_shop_npc_always_fails`) caught it.
- **A found gap, filled in this pass:** GC-051 (shop/economy) had been
  skipped entirely in an earlier session despite Sprint 2.1 reading as
  done — caught while writing this final backlog entry, not by a test
  (there were no shop tests yet either). Built now: `world/shop.py`'s
  `buy_from_npc()`/`sell_item()`, Boran and Tam's `stock` lists, and
  `tests/test_ethereal_dnd_shop.py`.
- **A second real gap, recorded rather than filled:** there was never a
  ticket for actual player-facing character creation (interactive race/
  class selection, ability-score generation via GC-023's 4d6/point-buy
  methods, building the 2 companions) — Section 5's architecture names a
  planned `characters/character_builder.py`, and Section 49/this phase's
  exit criteria assume "create character" is a real step, but nothing in
  Sprint 0-1.5 ever ticketed it. Recorded as **GC-071** below (Sprint
  2.1, out of numeric sequence — appended rather than renumbering every
  ticket after it, same as GC-070). Decision: ticket it now, build it
  later — `debug_cli.create_test_character()` (a developer/test
  convenience that assumes ability scores and class are already decided)
  stands in for it through all of Phase 2.

### Sprint 2.1 — Ravenhollow ✅ done (except GC-071)

- **GC-071** (M) — Not started (see the gap note above). Interactive
  character creation: race/class selection, ability-score generation
  (`characters/abilities.py`'s `roll_ability_scores()` or
  `validate_point_buy()`, the player's choice), and building the
  player's 2 companions the same way (Section 48). Belongs in a new
  `characters/character_builder.py` (matching the design doc's own
  planned file), with a CLI entry point now and a GUI form later
  (mirroring how GC-070 added the GUI panel ahead of its own original
  ticketing). Depends on: GC-023, GC-024, GC-026.
- **GC-050** (M) — ✅ `ethereal_dnd/data/locations/ravenhollow.json` +
  5 NPCs (`ethereal_dnd/data/npcs/*.json`, loaded by
  `world/campaign_content.py`) — Mayor Voss (Aristocrat 5), Old Mabel
  the innkeeper (Commoner 3), Boran Ironhand the blacksmith (Warrior 4),
  Sister Wren the priest (Cleric 5, devoted to Aurelia), Tam the Trader
  (Expert 3) — every one a real `Character` with real HP/AC via
  `world/npc.py`'s `build_npc()`. Depends on: GC-016, GC-024.
- **GC-051** (S) — ✅ `world/shop.py` (see the gap note above for why
  this landed late). `buy_from_npc()` checks the NPC's `stock` list and
  the buyer's gold; `sell_item()` returns half list price (the standard
  SRD secondhand-goods assumption). Depends on: GC-050, GC-034.
- **GC-052** (M) — ✅ Every NPC's `rumors` list (Section 47's exact 7
  rumors, distributed across the 5 NPCs, 2 wired to real `quest_id`s),
  surfaced via `debug_cli.talk_to()`. Depends on: GC-050.

### Sprint 2.2 — Travel & map ✅ done

- **GC-053** (M) — ✅ `ethereal_dnd/data/locations/{blackwood,old_ruins,
  abandoned_mine,farmstead}.json` + `ethereal_dnd/data/world/routes.json`
  (8 directional routes), loaded by the same `world/campaign_content.py`
  as GC-050. `world/travel.py`'s `travel()` advances `CampaignTime` by
  the route's real `base_travel_time_hours`. Depends on: GC-016, GC-007.
- **GC-054** (S) — ✅ Every non-Ravenhollow location starts
  `discovered=False`; `travel()` flips it and emits `LocationDiscovered`
  the first time the party arrives, not on subsequent visits. Depends
  on: GC-053, GC-006.

### Sprint 2.3 — Random encounters ✅ done

- **GC-055** (M) — ✅ `encounters/encounter_tables.py` (keyed by a
  route's `terrain`, not per-route — forest/hills/plains cover all 8
  routes) + `ethereal_dnd/data/encounters/*.json`, weighted so "nothing
  happens" is itself a normal-weight entry rather than a separate roll.
  Monsters sourced from `docs/srd_reference/extra/MonstersAnimals.md`
  (Wolf) and the Humanoid-1-HD-as-NPC-class rule (Bandit = Warrior 1,
  from `NPCClasses.md`, not a dedicated Monster Manual block). Depends
  on: GC-053.
- **GC-056** (M) — ✅ `traveler` and `discovery` outcomes are real,
  distinct log lines in every terrain table (verified by
  `test_plains_route_never_rolls_combat` and
  `test_combat_encounter_spawns_real_fightable_monsters` actually
  exercising both branches, not just asserting the data exists).
  Depends on: GC-055.

### Sprint 2.4 — Quests ✅ done

- **GC-057** (M) — ✅ `quests/quest_manager.py`: `start_quest()`,
  `complete_objective()` (auto-completes the quest once every objective
  is done), `fail_quest()`, `grant_quest_rewards()` (splits gold evenly
  across the living party, awards XP to each member's first/primary
  class). Objective *completion* is an explicit call from wherever the
  completing action happens (a won fight, a location entered) — see
  GC-058 for the two things that are genuinely event-driven instead.
  Depends on: GC-019, GC-006.
- **GC-058** (M) — ✅ `quests/quest_hooks.py`'s `attach_quest_hooks()`:
  "NPC dies → quest fails" is derived from the generic `CharacterDied`
  event (there's no separate NPC-specific death event — it checks
  `campaign.world.npcs` membership), and "location discovered → quest
  unlocks" via `register_locked_quest()` + a scratch bucket in
  `CampaignState.npc_state` (no new Campaign-level field needed).
  Depends on: GC-057, GC-054.
- **GC-059** (M) — ✅ 2 quests (not 3 — two solid ones over three thin
  ones): "The Missing Miners" (Investigate + Kill, 2 objectives, ends at
  the Abandoned Mine dungeon) and "Wolves of Blackwood" (1 Kill
  objective, the simpler of the two). Both wired to real NPC rumors.
  Depends on: GC-058, GC-053.

### Sprint 2.5 — Dungeon ✅ done

- **GC-060** (L) — ✅ `world/dungeon.py` (`Dungeon`/`DungeonRoom`/`Trap`
  + `load_dungeon()`, a fresh instance per call so trap/room state never
  leaks between runs) + `ethereal_dnd/data/dungeons/abandoned_mine.json`:
  4 rooms (entrance → collapsed tunnel with a real Camouflaged Pit Trap,
  sourced verbatim from `docs/srd_reference/extra/Traps.md` → miners'
  cage with a guard → boss chamber with the Bandit Leader), tied to
  "The Missing Miners." Playtested to both a loss (a solo level-1
  fighter vs. the full room, correctly overwhelming) and a win (a
  2-person level-4 party). Depends on: GC-033, GC-059.

### Sprint 2.6 — Death, resurrection, save/load ✅ done

- **GC-061** (M) — ✅ `characters/resurrection.py`, sourced verbatim from
  the *Raise Dead* spell: eligible if dead ≤ 1 day per caster level;
  costs 5,000 gp in diamonds (the real spell-text number, not an
  invented placeholder — deliberately large, so resurrection stays rare
  for a low-level party); the raised character loses a level (or 2
  Constitution at 1st level, refused outright if that would hit 0) and
  returns with HP equal to their new Hit Dice count, not full health.
  Gold can be paid from the whole party's pooled coin, including the
  corpse's own (a real fix mid-session: `living_members()` alone
  couldn't cover a solo character's own resurrection since a dead
  character isn't "living"). Depends on: GC-050, GC-039.
- **GC-062** (L) — ✅ `campaign/save_manager.py`: `dataclasses.asdict()`
  handles the entire nested object graph for serialization in one call;
  loading needs an explicit reconstruction function per dataclass with a
  dataclass-typed field (`_character_from_dict`, `_npc_from_dict`,
  `_world_from_dict`, etc.), since `asdict()` has no stdlib inverse.
  Writes to `saves/<campaign.id>/campaign.json` (matching the ticket's
  path shape; no separate `history.json` — `Campaign.history` is just
  another field in the same document). **Known, documented limitation**
  inherited from `Campaign`'s own Phase 1 design: the RNG stream itself
  isn't persisted, only `random_seed` — a loaded campaign's future rolls
  restart that seed's sequence rather than continuing where the live
  session's stream had gotten to. Verified with a deep round-trip test
  covering character/divine-standing/world/NPC/quest/time/history state.
  Depends on: GC-005, GC-017, everything above it in Phase 2.
- **GC-063** (S) — ✅ `campaign/history.py`'s `attach_history_log()`,
  using a new `EventBus.subscribe_all()` (Phase 0's bus only supported
  per-type subscription) to append a day/time-stamped, human-readable
  line for every event to `Campaign.history`. A loaded campaign's event
  bus starts empty (same as GC-062's RNG limitation note) — re-attaching
  is `debug_cli.load_saved_campaign()`'s job, not automatic. Depends on:
  GC-006, GC-062.

**Phase 2 exit criteria: ✅ met**, aside from GC-071 (character
creation stands in via `debug_cli.create_test_character()`, per the gap
note above). The CLI plays the full loop from Section 49 — recruit a
character → enter Ravenhollow → talk to an NPC → accept a quest → travel
(real time cost) → random encounter (combat or not) → combat →
dungeon → quest completion + reward → save → load — with zero narrative/
LLM involvement, verified end-to-end by
`tests/test_ethereal_dnd_dungeon.py`'s
`test_full_dungeon_run_with_a_strong_party_completes_the_quest` and the
full `tests/test_ethereal_dnd_save_load.py` suite. Also wired into the
GUI as the "🏘️ Explore Ravenhollow" button (recruit → talk → accept →
travel → auto-resolve encounter → quest status, one click).

---

## Phase 3 — Narrative Intelligence ✅ done

Matches "Fourth Claude Task" (Section 62). This is where Gnosis actually
becomes the dungeon master and the project hits the Section 65 success
definition.

**The pipeline, assembled** (`ethereal_dnd/narrative/game_loop.py`'s
`process_player_input()`): freeform text → `intent_parser.parse_intent()`
→ `ActionIntent` → `action_resolver.resolve_action()` (pure rules code,
zero LLM involvement) → a result dict → `GnosisNarrator.
narrate_resolved_action()` describing only what the resolver already
decided. `debug_cli.play(campaign, narrator, text)` is the one-line
entry point; wired into the GUI as a "What do you do?" box running on a
background `QThread` (`_NarrativeWorker` in `ethereal_dnd_widget.py`),
since a real model call is slow enough to freeze the GUI thread
otherwise.

**Deviations from the original ticket text, made during implementation:**
- **`MODELS["main"]` (qwen3.5:4b), not `MODELS["fast"]` (yi:6b)**, for
  both the intent parser and the narrator's default chat function —
  live-tested against the actual running Ollama instance (see below),
  `yi:6b` asked a spurious clarifying question ("Are you referring to
  the Innkeeper, Old Mabel, by her id or her title?") for as
  unambiguous a prompt as "I talk to Old Mabel." — exactly the failure
  mode `core/models.py`'s own comment on `yi:6b` already documents for
  other call sites, now confirmed for this one too. `MODELS["main"]`
  handled the same prompts correctly with no clarify triggered.
  `agent_dialogue.call_agent_json()`'s clarify round-trip is still
  wired in (a genuinely ambiguous prompt should still be able to ask),
  just no longer fighting a model that clarifies on things that aren't
  actually ambiguous.
- **`Narrator` gained a 5th abstract method**, `narrate_resolved_action(resolution, context)`
  — Section 55's original four methods predate having a real resolved-
  action shape to narrate, but `game_loop.process_player_input()` needs
  exactly this, and it needs to work for *any* Narrator implementation,
  not just `GnosisNarrator`. Added to the abstract base and to
  `NullNarrator` (returns the resolution's own log line — still zero
  LLM dependency, proving the engine runs standalone per Section 56).
  `interpret_player_intent()` (one of the original four) is
  deliberately left raising `NotImplementedError` on `GnosisNarrator` —
  intent parsing is `narrative/intent_parser.py`'s job, a distinct,
  earlier pipeline stage per Section 34's own diagram, not the
  narrator's.
- **New `characters/checks.py`** — a generic `perform_skill_check()`
  needed for `action_resolver.py`'s "skill_check" action type didn't
  exist anywhere in Phase 1's combat-focused rules code. DCs sourced
  verbatim from `docs/srd_reference/core/SkillsI.md`'s "Table:
  Difficulty Class Examples" (Very Easy 0 through Nearly Impossible 40),
  not invented numbers.
- **GC-069's literal quality-bar example needs content that doesn't
  exist** — there's no watchtower location in *The Ashes of
  Ravenhollow* (Section 63's example was always illustrative of the
  *mechanism*, per Section 63's own framing, not a literal room this
  vertical slice was ever going to have). Verified the real mechanism
  instead against real Ravenhollow content — see the transcripts below.
  Building an actual watchtower scene is Phase 2-style content work,
  not a Phase 3 gap.

**Live verification against the actually-running Ollama instance** (not
mocked — this project has one installed and running), because a
narrative pipeline's real behavior isn't something a mocked-chat_fn unit
test can prove on its own:

```
> I climb onto the roof of the inn.
[CHECK] Sky attempts a climb check: d20 5 + +3 = 8 vs DC 10 -> FAILURE
"The first pale light of dawn breaks over Ravenhollow as you dig your
fingers into the rock surface... Your grip slips under your weight, and
you find yourself unable to make any upward progress against the slope."

> I wait until midnight.
Time passes. Day 2, 00:00 (Midnight)
"...you remain still in the deep silence while hours pass by..."
(the model correctly computed 18 hours from 06:00 to reach midnight)

> I travel to Blackwood.
[TRAVEL] Ravenhollow -> Blackwood, 3 hours pass, Discovered: Blackwood
[ENCOUNTER] A hooded traveler passes the other way, nodding but saying nothing.
"...a hooded traveler passes you in the other direction, nodding but
saying nothing." (narration matches the real encounter roll exactly)

> I try to burn down the tavern.
"unsupported" -> "That isn't something this engine can resolve
mechanically yet." (correctly refused rather than inventing a fire)

> I talk to Old Mabel.
[talk, target_id=mabel_innkeeper] -> real rumors returned
"...Old Mabel speaking with another traveler at the nearby tavern. She
mentions that something strange and unsettling is happening in
Blackwood..." (rumor content matches exactly; the "another traveler" and
dawn-birdsong flourishes are narrative color, not invented mechanics)

> [dialogue()] "Hello! Any strange news lately?" (direct in-character
  conversation with Old Mabel, not the intent-parser pipeline)
Old Mabel: "Come have a seat, folks say something strange is happening
in Blackwood. It sounds like someone has been attacking travelers
lately. I ain't got any more news than that."
(both lines are Old Mabel's actual rumors, verbatim in substance -
nothing invented; relationship with her correctly nudged 0.0 -> 1.0)
```

Every mechanical fact in every narration traces back to a real dice
roll, a real state change, or a real "no" from the resolver — never
something the model decided on its own. The one soft spot: the
"unsupported" case's narration leans slightly meta ("the system informs
you...") rather than staying fully in-world - a prompt-polish item, not
a correctness bug, left for whenever Phase 3's prose quality gets a
second pass.

**A real gap found and fixed via this same live playtesting**: "I look
around the town square" — arguably the single most basic action in any
text adventure — fell through to `"unsupported"` with a jarring, fully
meta narration ("The engine confirms your request falls outside current
mechanical support..."). Section 30's whole location-interaction system
and Section 33's narrator both assumed "describe where I am" would be
reachable, but nothing had ever actually wired it into
`KNOWN_ACTION_TYPES`/`action_resolver.py`. Fixed: added `"look"` as a
9th action type, resolved by a new `context_builder.describe_location_text()`
(shared with `debug_cli.show_location()`, which now delegates to it
instead of keeping its own copy of the same three lines). Re-verified
live after the fix:

```
> I look around the town square.
[look] -> real location/NPCs/routes returned
"You stand at dawn in Ravenhollow, a weathered timber-and-stone market
town situated where the North, South, and West Roads intersect. Morning
smoke curls from the forge while the temple bell rings to mark the
passing hours..." (fully in-world now, every fact real)
```

- **GC-064** (L) — ✅ `narrative/action_intent.py` (`ActionIntent`,
  `KNOWN_ACTION_TYPES`) + `narrative/intent_parser.py`
  (`parse_intent()`), built on `agent_dialogue.call_agent_json()` +
  `core.models.chat()` exactly as specified — no new LLM client.
  Depends on: GC-020.
- **GC-065** (L) — ✅ `narrative/action_resolver.py`'s `resolve_action()`,
  covering attack, skill_check, talk, travel, rest, cast_spell, wait, and
  look (8 of Section 31's examples — "look" added after live playtesting
  exposed it was missing, see below) plus the explicit `"unsupported"`
  case for everything else (theft/burning/etc. — real mechanical
  handling for those specific actions doesn't exist yet, and pretending
  otherwise would violate Section 2.1 worse than admitting the gap).
  `actor_id` currently always resolves to the first living party member
  (GC-071's
  gap note applies again: there's no real multi-character selection
  yet). Depends on: GC-064, GC-025, GC-057.
- **GC-066** (M) — ✅ `narrative/context_builder.py`'s `build_context()`:
  location, time, NPCs present, reachable routes, party status, active
  quests, and the last 8 history entries (not the whole log). Depends
  on: GC-063.
- **GC-067** (L) — ✅ `narrative/gnosis_narrator.py`'s `GnosisNarrator`,
  replacing `NullNarrator` for real play (both still coexist —
  `NullNarrator` keeps proving the engine needs no LLM to function).
  Depends on: GC-066, GC-020.
- **GC-068** (M) — ✅ `characters/relationships.py`
  (`adjust_relationship()`/`get_relationship()`, using Character's
  existing `relationships` dict) + `debug_cli.dialogue()` for direct
  in-character NPC conversation via `GnosisNarrator.
  respond_to_dialogue()`, constrained to that NPC's actual rumor list so
  it can't invent lore on the NPC's behalf. Live-verified against Old
  Mabel. Not yet done: the fuller Section 38 relationship *behaviors*
  (approve/disapprove/leave/betray) — that's Phase 10, this is just the
  numeric foundation Phase 3 needed to have dialogue mean anything at
  all. Depends on: GC-067.
- **GC-069** (L) — ✅ Live-verified above against real Ravenhollow
  content (talk, skill check, wait, travel-with-encounter, unsupported,
  dialogue) rather than the literal watchtower example (see the
  deviation note). `tests/test_ethereal_dnd_narrative.py` (28 tests,
  mocked chat_fn, CI-safe) locks in the pipeline wiring itself so this
  doesn't depend on a running Ollama instance to stay green. Depends on:
  GC-065, GC-067.

- **GC-072** (M) — ✅ *(new, not originally ticketed — added when the
  user asked for buttons instead of relying entirely on freeform-text
  intent parsing: "id rather give the user buttons or actions to select
  to do. this way we can contain the logic a little better.")*
  `narrative/action_menu.py`'s `available_actions()` builds a list of
  already-fully-determined `ActionIntent`s straight from real campaign
  state (look, talk/attack for every living NPC present, travel for
  every real route, rest) — no LLM guess involved in constructing the
  list itself. `narrative/game_loop.py`'s new `process_menu_action()`
  takes one of these straight into `resolve_action()`, skipping the
  intent parser entirely (only the narrator still calls a model, to
  describe an already-decided result). `debug_cli.list_actions()` /
  `do_action()` expose it to the CLI/GUI the same way `play()` exposes
  the freeform path. Per Section 31, the button menu supplements rather
  than replaces freeform text — `ethereal_dnd_widget.py`'s "What do you
  do?" box stays alongside the new action grid, and both paths refresh
  the grid after every resolution since routes/NPCs can change (a
  discovered route, a killed NPC). `tests/test_ethereal_dnd_action_menu.py`
  (9 tests) covers menu construction, refresh-after-travel, dead-NPC
  exclusion, and that the menu path makes exactly one model call (the
  narrator's, never an intent-parsing one). Live-verified against the
  real Ollama model (`do_action()` on both "look" and "travel"). Depends
  on: GC-064, GC-065, GC-066, GC-067.

  **A real latent bug found while building this**: both
  `process_player_input()` and (the not-yet-written)
  `process_menu_action()` would have built the narrative context
  *before* resolving the action, so the narrator described stale
  pre-action state (e.g., the party's old location right after a
  successful travel). This had been silently masked in every earlier
  live test because the resolution's own log carried the real facts and
  the model mostly deferred to that wording rather than the stale
  context. Fixed by rebuilding context *after* `resolve_action()` runs,
  in both pipeline entry points — regression-tested by
  `test_process_menu_action_gives_the_narrator_post_action_context`.

**The full Section 65 list, run in one continuous live sitting** (one
`Campaign`, one running Ollama-backed `GnosisNarrator`, seed=42), to
close out the "not verified" gap noted above. Points 1-2 (character
creation) are skipped per GC-071 — `create_test_character()` stands in,
same as every other demo this project has. Every other point was
attempted through natural language (`debug_cli.play()`) first; three of
them (11, 13, 14) have no matching `ActionIntent` action type yet and
fell back to the direct `debug_cli`/engine call that's always been
there since Phases 1-2 — labeled honestly as such rather than faked
through text:

```
[3]  Enter a persistent world        -> loaded The Ashes of Ravenhollow, Day 1 06:00, Ravenhollow described
[4]  Explore locations          [NL] -> "I look around." - real location/NPCs/routes
[5]  Speak to NPCs              [NL] -> "I talk to Boran Ironhand." - his real rumor, verbatim
[6]  Travel between locations   [NL] -> "I travel to Blackwood." - real 3-hour route
[7]  Passage of time            [NL] -> "I wait for four hours." - clock actually advanced
[8]  Random encounters          [NL] -> triggered as part of [6]'s travel roll
[9]  Turn-based combat w/ init. -> direct debug_cli.run_party_combat() - see gap below
[10] Equipment/skills/spells    [NL] -> climb check + "I cast cure light wounds on myself."
[11] XP and levels                   -> direct characters.leveling.award_experience() - no NL action type
[12] Die and be resurrected          -> direct characters.death/resurrection calls - no NL action type
[13] Complete or ignore quests       -> direct debug_cli.accept_quest()/complete_quest_objective() - no NL action type
[14] Morally meaningful decisions    -> direct debug_cli.commit_evil_act() - no NL action type
[15] Return to previous locations [NL] -> "I travel back to Ravenhollow."
[16] Change the world                -> all of the above persisted on one live `campaign` object
[17] Save the campaign               -> debug_cli.save_current_campaign()
[18] Load the campaign later         -> debug_cli.load_saved_campaign(), party/location intact
[19] Continue the story         [NL] -> "I look around." on the *loaded* campaign - worked identically
```

**A real, confirmed structural gap, found by actually trying point 9
through natural language** rather than assuming it worked: after
`[6]`'s travel rolled a combat encounter, `"I attack the wolf."` came
back "no one matching None here to attack" — the intent parser
correctly had nothing to resolve "the wolf" against, because
`context_builder.build_context()`'s `npcs_present` only ever lists
persistent `campaign.world.npcs`, never the ephemeral `Character`
objects `encounters/random_encounters.py` spawns for a combat roll
(`world/travel.py`'s `travel()` returns them in the encounter dict and
then does nothing further with them). So today, a random encounter that
turns out to be combat is narrated but **cannot be fought through
natural language at all** — `debug_cli.run_party_combat()` (real
initiative order, real rounds, already used by the GUI's Explore
Ravenhollow demo) is the only way to resolve it, exactly as the
transcript's `[9]` line shows. Recorded as **GC-073** below. Decision:
ticket it now, build it later, matching how GC-071 handled the
character-creation gap — wiring a live encounter into the resolver
means giving `Campaign` real "there's an unresolved fight right now"
state and extending `_resolve_attack`/`build_context()` to see it,
which is new mechanism, not a quick patch.

A smaller, non-blocking observation from the same run: asking to travel
somewhere with no route from the current location (tried after already
being in Blackwood) narrates identically to a truly-impossible action
("that isn't something this engine can resolve mechanically yet")
rather than the more specific "no route from here" message
`_resolve_travel`'s `NoRouteError` handling already produces for a
`kind: "travel"` failure — the intent parser evidently classifies it as
`"unsupported"` outright rather than `"travel"` with a bad destination,
since Blackwood's own routes aren't in the context it's given. Harmless
(the refusal is still correct), just a slightly generic message; not
worth a ticket on its own.

**Phase 3 exit criteria: met.** All 19 of Section 65's success points
were demonstrated in one continuous live session against the real
Ollama model — 16 through natural language, 3 (XP/leveling,
death/resurrection, quests) through the direct engine calls Phases 1-2
already built, since the intent parser has no action type for those
yet. The one real gap the sitting surfaced (fighting a random
encounter's monsters through natural language) is ticketed as GC-073
rather than silently left unnoticed.

- **GC-073** (L) — Not started. Let a random-encounter combat actually
  be fought through natural language: give `Campaign` a slot for "the
  fight currently in progress" (set when `world/travel.py`'s `travel()`
  returns a `type: "combat"` encounter, cleared when every monster in it
  is dead or the party flees), have `context_builder.build_context()`
  list its monsters the same way it lists `npcs_present` so the intent
  parser has real names to resolve "the wolf" against, and extend
  `action_resolver._resolve_attack()` to check that slot in addition to
  `campaign.world.npcs`. Whether one `"I attack the wolf"` per NL
  message should mean "resolve the next full round of
  `combat/actions.py`'s existing initiative order" or "just this one
  swing, then wait for the model to say what's next" is a real design
  choice to make before writing this, not during. Depends on: GC-065,
  GC-066, GC-072.

---

## Phase 4+ — Content Expansion (stubs)

Sprint-level only, per the note at the top of this doc — ticketed when
each is actually picked up, not now.

- **Phase 4 — More classes & races**: Paladin, Ranger, Bard, Sorcerer,
  Druid, Monk (several of which need their Phase 1.5 alignment contracts
  written first), plus remaining SRD core races.
- **Phase 5 — More spells**: expand `magic/spell_effects.py`'s primitive
  set as needed; bulk out the spell list per class/level.
- **Phase 6 — More monsters**: `data/monsters/*.json` beyond whatever
  Phase 2's dungeon needed. Source material is already sitting in
  `srd_reference/extra/Monsters*.md` (the full core bestiary) and
  `EpicMonsters(A-E/G-W).md` for higher-CR content — this phase is
  mostly "convert more of what's already sourced to JSON," not new
  research (see [srd_reference/SOURCED.md](srd_reference/SOURCED.md)).
- **Phase 7 — Expanded equipment**: magic items, wands/rings/amulets,
  full mundane equipment lists. `srd_reference/core/MagicItemsI–VI.md`
  already covers this in full.
- **Phase 8 — More locations**: beyond the Ravenhollow cluster —
  Capital, additional regions. `srd_reference/extra/
  WildernessandEnvironment.md` and `Planes.md` have the environment/
  planar rules to build these from.
- **Phase 9 — More factions**: faction/reputation depth beyond Section
  36's minimal state.
- **Phase 10 — Companion relationships**: the fuller Section 38
  approve/disapprove/leave/betray behaviors.
- **Phase 11 — Economy**: dynamic pricing, supply/demand, trade routes.
- **Phase 12 — Crafting**.
- **Phase 13 — Advanced magic**: higher-level spells, metamagic.
- **Phase 14 — Prestige classes**: including alignment-gated ones
  (Blackguard, Assassin) once GC-042's decision is revisited. Full
  chapter already sourced at `srd_reference/extra/PrestigeClasses.md`
  (1532 lines, every core prestige class).
- **Phase 15 — Epic progression**. `srd_reference/extra/EpicClasses.md`,
  `EpicFeats.md`, `EpicLevelBasics.md`, `EpicSkills.md`, `EpicSpells.md`,
  `EpicMagicItems1/2.md`, `EpicObstacles.md`,
  `EpicPrestigeClasses.md` — the full Epic Level Handbook SRD — are
  already sourced.
- **Phase 16 — More campaigns** (beyond *Ashes of Ravenhollow*).
- **Phase 17 — Procedural world generation**.

(Numbered as Phase 4–17 here vs. the source doc's "Phase 1–15" in
Section 57, to avoid colliding with this backlog's Phase 0–3 numbering.)
