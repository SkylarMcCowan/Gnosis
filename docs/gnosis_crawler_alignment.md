# Gnosis Crawler — Alignment & Deity Compliance ("Falling From Grace")

Extends [Section 39 (Alignment / Mythic Progression)](gnosis_crawler.md#39-alignment--mythic-progression)
and [Section 12 (Classes)](gnosis_crawler.md#12-classes) of the main design doc.

## 1. The rule this implements

D&D 3.5 (SRD, open content) ties several classes' power to the character
actually behaving the way their class/faith requires. This is well
documented and not proprietary — it's exactly the kind of open rules
content [Section 4](gnosis_crawler.md#4-legal--content-boundary) says we can use. The general shape,
per class:

| Class | Alignment requirement | On violation |
|---|---|---|
| Paladin | Exactly Lawful Good | Loses all paladin spells/abilities (keeps weapon/armor/shield proficiencies); can't advance in paladin levels; restored only by atonement |
| Cleric | Within one step of their deity's alignment (may differ on *one* of the two axes, not both) | Gross violation of the deity's code loses all spells/class features (keeps proficiencies) until atonement |
| Druid | Some form of neutral (neutral on at least one axis) | Losing neutrality / violating druidic strictures loses spells/abilities until atonement |
| Monk | Lawful (any) | Becoming non-lawful blocks further monk advancement; existing abilities are kept (no atonement needed, just realignment) |
| Barbarian | Non-lawful (any) | Becoming lawful blocks rage/further advancement until realignment |
| Fighter, Rogue, Wizard, Sorcerer, Bard, Ranger | None | N/A |

**Update:** the exact wording is now pulled and verified — see
[Section 1a](#1a-exact-srd-wording-ticket-gc-041-done) below. Ticket
GC-041 is done; what follows was sourced from a local copy of the SRD
rather than hand-typed from memory.

## 1a. Exact SRD wording (ticket GC-041, done)

Pulled verbatim from the SRD text now mirrored locally at
[docs/srd_reference/core/](srd_reference/core/) (see that folder's
README for provenance/license). Quoted here for convenience; the local
files are the source of truth if these ever drift.

**Paladin** (`srd_reference/core/ClassesII.md`, *Code of Conduct* /
*Ex-Paladins*):

> A paladin must be of lawful good alignment and loses all class
> abilities if she ever willingly commits an evil act.
>
> Additionally, a paladin's code requires that she respect legitimate
> authority, act with honor (not lying, not cheating, not using poison,
> and so forth), help those in need (provided they do not use the help
> for evil or chaotic ends), and punish those who harm or threaten
> innocents.
>
> [...] A paladin who ceases to be lawful good, who willfully commits an
> evil act, or who grossly violates the code of conduct loses all
> paladin spells and abilities (including the service of the paladin's
> mount, but not weapon, armor, and shield proficiencies). She may not
> progress any farther in levels as a paladin. She regains her abilities
> and advancement potential if she atones for her violations (see the
> *atonement* spell description), as appropriate.

**Cleric** (`srd_reference/core/ClassesI.md`, *Alignment* / *Ex-Clerics*):

> A cleric's alignment must be within one step of his deity's (that is,
> it may be one step away on either the lawful-chaotic axis or the
> good-evil axis, but not both). A cleric may not be neutral unless his
> deity's alignment is also neutral.
>
> [...] A cleric who grossly violates the code of conduct required by
> his god loses all spells and class features, except for armor and
> shield proficiencies and proficiency with simple weapons. He cannot
> thereafter gain levels as a cleric of that god until he atones (see
> the *atonement* spell description).

**Druid** (`srd_reference/core/ClassesI.md`, *Alignment* / *Ex-Druids*):

> **Alignment:** Neutral good, lawful neutral, neutral, chaotic neutral,
> or neutral evil.
>
> [...] A druid who ceases to revere nature, changes to a prohibited
> alignment, or teaches the Druidic language to a nondruid loses all
> spells and druid abilities (including her animal companion, but not
> including weapon, armor, and shield proficiencies). She cannot
> thereafter gain levels as a druid until she atones (see the
> *atonement* spell description).

**Monk** (`srd_reference/core/ClassesI.md`, *Alignment* / *Ex-Monks*):

> **Alignment:** Any lawful.
>
> [...] A monk who becomes nonlawful cannot gain new levels as a monk
> but retains all monk abilities.

**Barbarian** (`srd_reference/core/ClassesI.md`, *Alignment* /
*Ex-Barbarians*):

> **Alignment:** Any nonlawful.
>
> [...] A barbarian who becomes lawful loses the ability to rage and
> cannot gain more levels as a barbarian. He retains all the other
> benefits of the class (damage reduction, fast movement, trap sense,
> and uncanny dodge).

The general shape in the Section 1 table holds exactly, with two
corrections now that the real text is in hand:

- The cleric's neutrality clause is stricter than "any deviation ≤ 1
  step": *"A cleric may not be neutral unless his deity's alignment is
  also neutral"* — so `ComplianceRule` for clerics needs a second
  check beyond `max_axis_deviation`, specifically forbidding a neutral
  cleric under a non-neutral deity even though N is within one step of
  most alignments. GC-045's data file should encode this as an explicit
  extra condition, not rely on the generic one-step math alone.
- Both Druid and Barbarian's `on_violation` keep *more* than just
  proficiencies (druid keeps proficiencies; barbarian explicitly keeps
  damage reduction, fast movement, trap sense, and uncanny dodge) — the
  `keeps` list in each class's `ComplianceRule` needs to enumerate these
  per-class rather than defaulting to `["proficiencies"]` everywhere.

## 2. Your specific case

> a lawful evil paladin who selects an evil paragon [deity], then starts
> doing good — their god removes their powers.

Two independent contracts apply to this character, and either one alone
would fire:

1. **Class contract** (paladin → must be exactly LG). A LE "paladin" is
   already a contradiction under the class contract as written above —
   worth flagging: if we want to support anti-paladin-style evil
   champions, that's a **different class/prestige class** (e.g. Blackguard,
   an SRD-adjacent variant), not the core Paladin with its alignment
   requirement swapped.

   **GC-042 decision:** Blackguard is expansion-phase content (Phase 14
   in the backlog), not part of the initial roster. Reasoning: it's a
   prestige class, meaning it needs the prerequisite system Phase 4's
   prestige-class work builds, not something to bolt on early just to
   cover one alignment combination; and the compliance *engine* itself
   (this doc) is fully demonstrable with Paladin/Cleric/Druid/Monk/
   Barbarian alone — an evil paragon reads the same as a good one once
   deity-relative checks exist (see §2's Cleric path below), so nothing
   about proving the mechanic actually requires Blackguard to exist yet.
2. **Deity contract** (the evil paragon's dogma). Independent of class,
   a deity can revoke *divine* power (cleric/paladin/blackguard spells
   specifically) from anyone who drifts against its ethos, evil-god or
   not. This is the general mechanism your example is really describing:
   dogma compliance, not just the class's alignment box.

Both contracts are represented the same way (Section 3 below) so the
engine doesn't need to special-case "class alignment" vs "deity alignment."

## 3. Data model

```text
AlignmentVector (mutable, per character — already Section 39)
    law_chaos: float        # -100 (chaotic) .. +100 (lawful)
    good_evil: float        # -100 (evil) .. +100 (good)
    honor, mercy, cruelty, greed, selflessness: float
    derived_alignment() -> one of the 9 alignments (LG..CE)

Deity (definition, data/deities/*.json)
    id, name
    alignment: str                     # the deity's own alignment
    domains: [str]
    dogma: str                          # flavor text, shown to the player
    code_of_conduct: [ComplianceRule]   # structured, see below
    favored_weapon, symbol, etc.

ComplianceRule (shared by class contracts AND deity dogma)
    id, description
    scope: "class" | "deity"
    trigger: {
        type: "alignment_deviation" | "event_pattern"
        # alignment_deviation: checked continuously against derived_alignment()
        max_axis_deviation: int          # 0 = exact match, 1 = cleric's one-step rule
        required_axis: "law_chaos" | "good_evil" | "any_neutral" | null
        required_value: "lawful" | "chaotic" | "good" | "evil" | "neutral" | null
        forbid_neutral_unless_deity_neutral: bool  # cleric-specific extra clause, see §1a
        # event_pattern: checked against the Event stream (Section 35)
        matches_event: str                # e.g. "CommittedEvilAct", "BrokeOath"
    }
    on_violation: {
        effect: "revoke_class_powers" | "revoke_spells_only" | "block_advancement" | "block_advancement_and_signature_ability"
        keeps: [str]                      # per-class, from the exact SRD text — e.g.
                                           # paladin: ["weapon_proficiency", "armor_proficiency", "shield_proficiency"]
                                           # cleric: ["armor_proficiency", "shield_proficiency", "simple_weapon_proficiency"]
                                           # druid: ["weapon_proficiency", "armor_proficiency", "shield_proficiency"]
                                           # barbarian: ["damage_reduction", "fast_movement", "trap_sense", "uncanny_dodge"]
        restoration: "atonement" | "realignment" | null
    }

ClassAlignmentContract (definition, part of ClassDefinition — Section 12)
    class_id
    rules: [ComplianceRule]   # scope="class"

CharacterDivineStanding (runtime state, on Character)
    deity_id: str | None
    fallen: bool
    fallen_reason: str | None
    fallen_at: CampaignTime | None
    powers_revoked: [str]      # which ability/spell groups are currently suspended
    advancement_blocked_for: [class_id]
```

Definitions (`Deity`, `ClassAlignmentContract`) go through `deity_registry`
and hang off `class_registry` the same way spells/feats/monsters already
do (Section 7) — no new registry pattern needed.

## 4. Evaluation flow

```text
Player action / narrative event
        ↓
Rules engine resolves it, emits Event(s)        (Section 35, existing)
        ↓
AlignmentTracker consumes relevant events
        ↓
AlignmentVector updated
        ↓
ComplianceEvaluator runs on:
    - the character's active ClassAlignmentContract(s)
    - the character's Deity's code_of_conduct (if any deity selected)
        ↓
Any ComplianceRule now violated?
        ↓ yes
Apply on_violation effect to CharacterDivineStanding
        ↓
Emit ClassPowersRevoked (new Event type, Section 35)
        ↓
Narrator (Section 33) narrates the consequence —
it does NOT decide whether powers are revoked, only how it's described
```

This keeps the existing "rules decide, AI narrates" boundary
([Section 2.1](gnosis_crawler.md#21-rules-first)) intact: the compliance
evaluator is pure rules-engine code, deterministic and testable without an
LLM, same as attack rolls or saving throws.

Evaluation should run **on every event that could move the alignment
vector or match an `event_pattern` trigger** (single evil/good act, oath
broken, etc.) — not on a timer — so a single "willful evil act" can trigger
a paladin's fall the instant it happens, matching the SRD behavior, rather
than only being caught on some periodic sweep.

## 5. Atonement / restoration

- `atonement` restoration: requires an in-world action (the `Atonement`
  spell/ritual, or a quest-equivalent) — modeled as a `QuestObjective` or a
  direct `restore_class_powers(character, class_id)` engine call gated on
  a condition (e.g., "atonement ritual completed" flag), not something the
  player can just toggle off.
- `realignment` restoration: for monk/barbarian-style soft locks, simply
  re-deriving `derived_alignment()` back into the required range clears
  the block — no ritual needed, matching the SRD's lighter treatment of
  those two classes.

## 6. Non-goals for the first pass

- Prestige classes with their own alignment locks (Blackguard, Assassin,
  etc.) — expansion phase (see backlog GC-1xx range), not part of the
  vertical slice.
- Multiple deities per character, or deity-vs-deity conflict — one
  optional `deity_id` per character is enough for the first campaign.
- Exact numeric thresholds for "how far is too far" on the alignment
  vector — start with a simple, tunable constant per axis and log every
  compliance check (Section 54's logging discipline) so it can be tuned
  from real playtesting rather than guessed up front.
