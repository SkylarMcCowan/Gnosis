"""Character (design doc Section 9) - Phase 0 fixed the shape; Phase 1
fills in the derived-stat math, backed by class/skill/item data loaded
into the shared registries (characters/class_definition.py,
characters/skills.py, items/item.py).
"""
import dataclasses

from ethereal_dnd.characters.abilities import ability_modifier as compute_ability_modifier
from ethereal_dnd.characters.alignment import AlignmentVector
from ethereal_dnd.characters.class_definition import class_registry
from ethereal_dnd.characters.class_level import ClassLevel
from ethereal_dnd.characters.progression import base_attack_bonus_for, save_bonus_for
from ethereal_dnd.characters.race import race_registry
from ethereal_dnd.characters.skills import skill_registry
from ethereal_dnd.core.ids import new_id
from ethereal_dnd.core.time import CampaignTime
from ethereal_dnd.divine.standing import CharacterDivineStanding
from ethereal_dnd.items.inventory import Inventory
from ethereal_dnd.items.item import item_registry

# Size category -> attack roll / AC modifier (Section 11's Small
# Characters box generalized to every size; Medium is the 0-point
# baseline every other size is defined relative to).
_SIZE_MODIFIERS = {
    "Fine": 8, "Diminutive": 4, "Tiny": 2, "Small": 1,
    "Medium": 0, "Large": -1, "Huge": -2, "Gargantuan": -4, "Colossal": -8,
}

# Skills where the SRD (docs/srd_reference/core/SkillsI.md/II.md headers)
# applies the armor check penalty twice, not once.
_DOUBLE_ARMOR_CHECK_PENALTY_SKILLS = {"swim"}


class UntrainedSkillError(ValueError):
    """A trained-only skill was attempted with 0 ranks - the SRD doesn't
    allow even attempting the check, so this surfaces as an error rather
    than silently returning a number that implies the check is legal."""


class MissingAbilityScoreError(KeyError):
    """An ability score was read before it was ever set - Phase 0
    deliberately doesn't default this to "10 (average)", since a
    Character reaching combat/skill math without rolled scores is a bug
    to catch, not a value to guess."""


@dataclasses.dataclass
class Character:
    id: str = dataclasses.field(default_factory=new_id)
    name: str = ""
    race_id: str | None = None
    alignment: AlignmentVector = dataclasses.field(default_factory=AlignmentVector)
    class_levels: list[ClassLevel] = dataclasses.field(default_factory=list)
    ability_scores: dict[str, int] = dataclasses.field(default_factory=dict)  # STR/DEX/CON/INT/WIS/CHA
    hp: int = 0
    max_hp: int = 0
    damage: int = 0
    conditions: list[str] = dataclasses.field(default_factory=list)
    skill_ranks: dict[str, int] = dataclasses.field(default_factory=dict)
    feats: list[str] = dataclasses.field(default_factory=list)
    equipment: dict[str, str] = dataclasses.field(default_factory=dict)  # slot -> item instance id
    inventory: Inventory = dataclasses.field(default_factory=Inventory)
    # Natural armor (hide, scales, etc.) - 0 for every PC race; real for
    # monster stat blocks built via encounters/monster_factory.py.
    natural_armor_bonus: int = 0
    experience: int = 0
    gold: int = 0
    spellcasting: dict = dataclasses.field(default_factory=dict)
    background: str = ""
    personality: str = ""
    relationships: dict[str, float] = dataclasses.field(default_factory=dict)
    reputation: dict[str, float] = dataclasses.field(default_factory=dict)
    history: list[str] = dataclasses.field(default_factory=list)
    status: str = "alive"  # "alive" | "dead"
    deity_id: str | None = None
    divine_standing: CharacterDivineStanding = dataclasses.field(default_factory=CharacterDivineStanding)
    time_of_death: CampaignTime | None = None
    location_of_death: str | None = None

    @property
    def level(self) -> int:
        """Total character level - the sum across every ClassLevel entry
        (Section 13), never a single class/level pair."""
        return sum(class_level.levels for class_level in self.class_levels)

    # --- Ability scores ---------------------------------------------------

    def get_ability_score(self, ability: str) -> int:
        try:
            return self.ability_scores[ability]
        except KeyError:
            raise MissingAbilityScoreError(
                f"{self.name or self.id} has no {ability} score set yet"
            ) from None

    def ability_modifier(self, ability: str) -> int:
        return compute_ability_modifier(self.get_ability_score(ability))

    # --- Size ---------------------------------------------------------------

    def size_category(self) -> str:
        """"Medium" if no race is set yet - a character mid-creation
        (race not yet chosen) is assumed Medium the same way the SRD
        assumes a Medium baseline for anything not otherwise specified."""
        if self.race_id is None:
            return "Medium"
        return race_registry.get(self.race_id).size

    def size_modifier(self) -> int:
        return _SIZE_MODIFIERS[self.size_category()]

    # --- Equipment -------------------------------------------------------

    def equipped_item_definition(self, slot: str):
        """The ItemDefinition equipped in `slot`, or None if nothing is
        equipped there. Raises KeyError if `equipment` points at an
        instance id this character's own inventory doesn't actually
        have - a dangling reference is a bug, not a silent no-op."""
        instance_id = self.equipment.get(slot)
        if instance_id is None:
            return None
        instance = next((item for item in self.inventory.items if item.id == instance_id), None)
        if instance is None:
            raise KeyError(
                f"Equipped item instance {instance_id!r} for slot {slot!r} "
                f"not found in {self.name or self.id}'s inventory"
            )
        return item_registry.get(instance.definition_id)

    def armor_check_penalty(self) -> int:
        total = 0
        for slot in ("armor", "shield"):
            item_def = self.equipped_item_definition(slot)
            if item_def is not None:
                total += item_def.properties.get("armor_check_penalty", 0)
        return total

    # --- Skills -----------------------------------------------------------

    def skill_bonus(self, skill_id: str) -> int:
        skill_def = skill_registry.get(skill_id)
        ranks = self.skill_ranks.get(skill_id, 0)
        if skill_def.trained_only and ranks == 0:
            raise UntrainedSkillError(
                f"{skill_def.name} cannot be attempted untrained (0 ranks)"
            )
        bonus = ranks
        if skill_def.key_ability is not None:
            bonus += self.ability_modifier(skill_def.key_ability)
        if skill_def.armor_check_penalty:
            penalty = self.armor_check_penalty()
            if skill_id in _DOUBLE_ARMOR_CHECK_PENALTY_SKILLS:
                penalty *= 2
            bonus += penalty
        return bonus

    # --- Class progression (BAB / saves) ------------------------------------

    def base_attack_bonus(self) -> int:
        """Sum of each class's own BAB progression at the number of
        levels taken in that class (Section 13's multiclass rule - BAB
        is computed per class, then added together, not derived from
        total character level against one progression)."""
        total = 0
        for class_level in self.class_levels:
            class_def = class_registry.get(class_level.class_id)
            total += base_attack_bonus_for(class_def.base_attack_progression, class_level.levels)
        return total

    def _multiclass_save_bonus(self, save_name: str) -> int:
        total = 0
        for class_level in self.class_levels:
            class_def = class_registry.get(class_level.class_id)
            progression = class_def.save_progression[save_name]
            total += save_bonus_for(progression, class_level.levels)
        return total

    def fortitude_save(self) -> int:
        return self._multiclass_save_bonus("fortitude") + self.ability_modifier("CON")

    def reflex_save(self) -> int:
        return self._multiclass_save_bonus("reflex") + self.ability_modifier("DEX")

    def will_save(self) -> int:
        return self._multiclass_save_bonus("will") + self.ability_modifier("WIS")

    # --- Combat -----------------------------------------------------------

    def effective_dex_bonus_to_ac(self) -> int:
        """The Dex modifier actually applied to AC, capped by whichever
        equipped armor/shield restricts it most (Section 11's "Maximum
        Dex Bonus" column) - separated out from armor_class() so combat
        resolution can subtract exactly this (not a fresh, uncapped
        ability_modifier("DEX")) when a condition removes Dex-to-AC."""
        max_dex_candidates = [10**9]  # effectively "no cap" if nothing restricts it
        for slot in ("armor", "shield"):
            item_def = self.equipped_item_definition(slot)
            if item_def is not None:
                cap = item_def.properties.get("max_dex_bonus")
                if cap is not None:
                    max_dex_candidates.append(cap)
        return min(self.ability_modifier("DEX"), min(max_dex_candidates))

    def armor_class(self) -> int:
        armor_def = self.equipped_item_definition("armor")
        shield_def = self.equipped_item_definition("shield")
        armor_bonus = armor_def.properties["armor_bonus"] if armor_def else 0
        shield_bonus = shield_def.properties["armor_bonus"] if shield_def else 0
        return (
            10 + armor_bonus + shield_bonus + self.natural_armor_bonus
            + self.effective_dex_bonus_to_ac() + self.size_modifier()
        )

    def attack_bonus(self, weapon_slot: str = "weapon") -> int:
        """Melee attack bonus (Str-based) unless the equipped weapon is a
        ranged weapon, in which case it's Dex-based - the standard SRD
        split (Section 11's "Ranged Weapons" category description)."""
        weapon_def = self.equipped_item_definition(weapon_slot)
        is_ranged = weapon_def is not None and weapon_def.properties.get("weapon_group") == "ranged"
        ability_bonus = self.ability_modifier("DEX" if is_ranged else "STR")
        return self.base_attack_bonus() + ability_bonus + self.size_modifier()

    def melee_damage(self, weapon_id: str, rng_service) -> dict:
        """Roll a weapon's damage dice (via `rng_service`, so this stays
        deterministic under the campaign's seed - Section 43) plus the
        Strength modifier, returning the same detail shape as
        core.dice.roll_detailed() (used directly by combat/combat_log.py
        for Section 54-style logging). `weapon_id` is an ItemDefinition
        id (not an equipment slot), so this also works for evaluating an
        unequipped weapon (e.g. a shop preview) without touching
        `equipment`."""
        from ethereal_dnd.core.dice import roll_detailed

        weapon_def = item_registry.get(weapon_id)
        detail = roll_detailed(weapon_def.properties["damage_dice"], rng_service=rng_service)
        detail["modifier"] += self.ability_modifier("STR")
        detail["total"] = max(0, sum(detail["kept"]) + detail["modifier"])
        return detail

    def initiative(self) -> int:
        return self.ability_modifier("DEX")

    # --- Alignment / deity compliance (Phase 1.5) ---------------------------

    def can_use_class_powers(self, class_id: str) -> bool:
        """False if `class_id`'s powers are currently revoked by the
        alignment/deity compliance engine (ethereal_dnd/divine/) - the
        actual ability gate: spellcasting and any other class-granted
        ability must consult this before acting, rather than the
        narrator being trusted to remember a character has fallen
        (Section 2.1 - the AI never overrides mechanics, so the
        mechanics have to actually enforce this themselves)."""
        return self.divine_standing.is_class_usable(class_id)

    # --- Death --------------------------------------------------------------

    def die(self, campaign_time: CampaignTime, location_id: str | None = None) -> None:
        self.status = "dead"
        self.time_of_death = dataclasses.replace(campaign_time)
        self.location_of_death = location_id
