"""Quest state machine (design doc Section 40) - covers the objective
types the starting campaign actually needs (Kill, Find, Talk,
Investigate), not Section 40's full list. Objective *completion* is
driven by explicit calls from wherever the completing action happens
(winning a fight, talking to an NPC, finding an item) - see
quest_hooks.py for the two things that genuinely need to be event-driven
instead (an NPC dying failing a quest, a location being discovered
unlocking one).
"""
import json
import os

from ethereal_dnd.core.events import QuestCompleted, QuestFailed, QuestStarted
from ethereal_dnd.quests.quest import Quest

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "quests")


class QuestError(ValueError):
    pass


def load_quest_template(quest_id: str) -> dict:
    path = os.path.join(_DATA_DIR, f"{quest_id}.json")
    if not os.path.isfile(path):
        raise QuestError(f"No quest template for {quest_id!r}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def start_quest(campaign, quest_id: str) -> Quest:
    if quest_id in campaign.state.quest_state:
        raise QuestError(f"Quest {quest_id!r} has already been started")
    template = load_quest_template(quest_id)
    quest = Quest(
        id=quest_id, title=template["title"], description=template["description"],
        giver_id=template.get("giver_id"),
        objectives=[dict(o) for o in template["objectives"]],
        requirements=list(template.get("requirements", [])),
        rewards=dict(template.get("rewards", {})),
        failure_conditions=list(template.get("failure_conditions", [])),
        state="active",
    )
    campaign.state.quest_state[quest_id] = quest
    campaign.events.emit(QuestStarted(quest_id=quest_id))
    return quest


def complete_objective(campaign, quest_id: str, objective_index: int) -> Quest:
    quest = campaign.state.quest_state[quest_id]
    if quest.state != "active":
        raise QuestError(f"Quest {quest_id!r} is not active (state={quest.state!r})")
    quest.objectives[objective_index]["done"] = True
    if all(objective["done"] for objective in quest.objectives):
        complete_quest(campaign, quest_id)
    return quest


def complete_quest(campaign, quest_id: str) -> Quest:
    quest = campaign.state.quest_state[quest_id]
    quest.state = "completed"
    grant_quest_rewards(campaign, quest)
    campaign.events.emit(QuestCompleted(quest_id=quest_id))
    return quest


def fail_quest(campaign, quest_id: str, reason: str) -> Quest:
    quest = campaign.state.quest_state[quest_id]
    quest.state = "failed"
    quest.consequences.append(reason)
    campaign.events.emit(QuestFailed(quest_id=quest_id, reason=reason))
    return quest


def grant_quest_rewards(campaign, quest: Quest) -> None:
    """Split gold evenly across the living party, and award XP to each
    member's first (primary) class - matching characters/leveling.py's
    award_experience(), which needs a specific class_id to level rather
    than inferring one."""
    from ethereal_dnd.characters.leveling import award_experience

    living = campaign.party.living_members()
    if not living:
        return
    gold_share, remainder = divmod(quest.rewards.get("gold", 0), len(living))
    xp_amount = quest.rewards.get("experience", 0)
    for index, member in enumerate(living):
        member.gold += gold_share + (remainder if index == 0 else 0)
        if xp_amount and member.class_levels:
            award_experience(member, xp_amount, member.class_levels[0].class_id, campaign.events)
