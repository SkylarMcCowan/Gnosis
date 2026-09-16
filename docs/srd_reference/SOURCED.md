# What's Already Sourced

Inventory of everything currently in [core/](core/) and [extra/](extra/),
mapped to the WotC book each topic traditionally comes from, so a future
ticket can check here first instead of re-sourcing something that's
already sitting in this repo. All of it: [core/](core/) is hand-cleaned
(source repo's `04.done/`), [extra/](extra/) is raw Pandoc conversion,
usable but cross-check before treating as final wording (see
[gnosis_crawler_alignment.md §1a](../gnosis_crawler_alignment.md#1a-exact-srd-wording-ticket-gc-041-done)
for what "verified" looks like in practice).

Bottom line up front: **between `core/` and `extra/`, essentially the
entire OGC-declared D&D 3.5 core SRD is already here** — Player's
Handbook, Dungeon Master's Guide, and Monster Manual content, plus bonus
material from the Epic Level Handbook, Expanded Psionics Handbook, and
Deities & Demigods SRDs. Pulling the "DM manual" and "advanced monsters"
mostly turned out to mean confirming this was already covered, not
finding a new source — see the table below.

## Player's Handbook material — `core/`

| File | Covers |
|---|---|
| `Description.md`, `Basics.md` | Character creation basics |
| `Races.md` | Core races |
| `ClassesI.md`, `ClassesII.md` | All 11 core classes, alignment/code-of-conduct/Ex-X sections |
| `SkillsI.md`, `SkillsII.md` | Full skill list |
| `Feats.md` | Core feats |
| `Equipment.md` | Weapons, armor, gear, mounts |
| `CombatI.md`, `CombatII.md` | Combat rules, actions |
| `AbilitiesandConditions.md` | Conditions (Section 19 of the main design doc) |
| `MagicOverview.md`, `MagicItemsI–VI.md` | Spellcasting rules + full magic item lists |

## Dungeon Master's Guide material — `extra/`

| File | Covers |
|---|---|
| `NPCClasses.md` | The 5 NPC classes (Adept, Aristocrat, Commoner, Expert, Warrior) — what Ravenhollow's Blacksmith/Mayor/etc. (GC-050) should probably be built from instead of PC classes |
| `PrestigeClasses.md` | Full prestige class chapter (1532 lines) — this is where Blackguard-style, alignment-gated prestige classes (Phase 14, and the GC-042 decision) live |
| `Traps.md` | Trap design/mechanics — feeds GC-060's dungeon |
| `Treasure.md` | Treasure-by-CR tables |
| `SpecialMaterials.md` | Adamantine, mithral, etc. |
| `WildernessandEnvironment.md` | Wilderness/weather/dungeon environment rules (1287 lines) — feeds Section 27 travel and Phase 8 "more locations" |
| `Planes.md` | Planar rules — relevant once Deity/afterlife content (atonement, resurrection, Phase 1.5) goes deeper |
| `CarryingandExploration.md` | Encumbrance detail beyond Section 22's summary |
| `DivineRanksandPowers.md`, `DivineAbilitiesandFeats.md`, `DivineDomainsandSpells.md`, `DivineMinions.md` | Deity-building material (Deities & Demigods SRD) — directly useful for GC-044's `Deity` data files |

## Monster Manual material — `extra/`

| File | Covers |
|---|---|
| `TypesSubtypesAbilities.md` | Creature types/subtypes and the special-ability rules (fast healing, DR, SR, etc.) every monster stat block references |
| `Improving Monsters.md` | Templates, class levels on monsters, advancing Hit Dice — how to build a "boss" from a base creature |
| `MonsterFeats.md` | Monster-only feats |
| `MonstersIntro-A.md` through `MonstersT-Z.md` (full alphabet, split across `MonstersAnimals.md`, `MonstersB-C.md`, `MonstersD-De.md`, `MonstersDi-Do.md`, `MonstersDr-Dw.md`, `MonstersE-F.md`, `MonstersG.md`, `MonstersH-I.md`, `MonstersK-L.md`, `MonstersM-N.md`, `MonstersO-R.md`, `MonstersS.md`, `MonstersT-Z.md`, `MonstersVermin.md`) | The complete core Monster Manual bestiary |
| `MonstersasRaces.md` | Using monsters as PC races |
| `EpicMonsters(A-E).md`, `EpicMonsters(G-W).md` | Epic Level Handbook's higher-CR monsters — the "advanced monsters" beyond core MM CR range |

**Caution on names:** [`Legal.md`](extra/Legal.md) lists specific
monster names as Product Identity, *not* Open Game Content: beholder,
gauth, carrion crawler, tanar'ri, baatezu, displacer beast, githyanki,
githzerai, mind flayer, illithid, umber hulk, yuan-ti. They may still
appear as entries in the `Monsters*.md` files here (the source repo
didn't strip them), but before encoding any of these into
`data/monsters/*.json` under this project's own name, check whether the
entry needs renaming — the mechanics are usable, the name may not be
(Section 4 of the main design doc already flags this general concern).

## Beyond the core three books — `extra/`

| File(s) | Covers |
|---|---|
| `EpicClasses.md`, `EpicFeats.md`, `EpicLevelBasics.md`, `EpicMagicItems1.md`, `EpicMagicItems2.md`, `EpicObstacles.md`, `EpicPrestigeClasses.md`, `EpicSkills.md`, `EpicSpells.md` | Epic Level Handbook SRD — feeds Phase 15 ("Epic progression") when that's reached |
| `PsionicClasses.md`, `PsionicItems.md`, `PsionicMonsters.md`, `PsionicPowersA-C/D-F/G-P/Q-W.md`, `PsionicRaces.md`, `PsionicSkills.md`, `PsionicSpells.md`, `PsionicsFeats.md`, `PowerList.md`, `PowersOverview.md` | Expanded Psionics Handbook SRD — not currently on the roadmap anywhere, kept in case a psionic class/monster ever gets pulled in |

## Spells — `extra/`

`SpellListI.md`, `SpellListII.md` (indices) + `SpellsA-B.md` through
`SpellsT-Z.md` (full alphabetical spell descriptions) — the complete
core spell list feeding Phase 5 ("More spells").

## Not sourced (and why)

- **Monster Manual II–V, Complete series, Draconomicon, other
  splatbooks** — each declares its own OGC content independently in its
  own Section 15, not through the core SRD's license. There's no single
  aggregated document for these the way there is for the core three
  books, so pulling from them means sourcing per-book, not just
  extending this corpus. See
  [SOURCING_GUIDE.md](SOURCING_GUIDE.md#sourcing-something-not-covered-yet)
  before starting that.
- **Forgotten Realms / other campaign settings** — almost entirely
  Product Identity (setting names, deities, geography). Don't source
  from these for Gnosis Crawler's own world content.
- **Unearthed Arcana SRD** — a separate WotC SRD document with its own
  variant rules; not pulled in because nothing on the current roadmap
  needs it yet.
