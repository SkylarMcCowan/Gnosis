"""Experience System (Phase 5): a structured record of what an autonomous
action tried, whether it worked, and what to learn from it - the roadmap's
own schema:

    {"goal": ..., "plan": ..., "actions": [], "tools_used": [],
     "result": ..., "success": true, "score": 0.87, "lessons": [],
     "timestamp": ..., "agent": ..., "skill": ...}

Kept deliberately simple: `score_experience` is a binary 1.0/0.0 on
`success`, not a real continuous quality metric (there's no rubric yet for
what "partial credit" would even mean), and `extract_lessons` is rule-based
on the fields already in the record, not a model call - Phase 6's own
`learning/` engine (evaluator/critic/reflection) is the deliberate future
home for judgment calls this simple, deterministic first pass doesn't try
to make. This module never imports webagent.py - same discipline as
tools/skills - only `core.config` (for where to store records) and
`tools.registry` (for `experience_to_knowledge`'s one write).

`success` is one of True (the action's goal was actually achieved), False
(it was attempted and failed/was reverted), or None (never attempted at
all - blocked, or no actionable candidate found) - collapsing "not
attempted" into False would misrepresent a cycle that correctly chose to
do nothing as a failure.
"""
import json
import os
from datetime import datetime

from core import config as core_config
from tools.registry import registry as tool_registry


def _experience_log_path():
    return os.path.join(core_config.path("experience"), "log.jsonl")


def build_experience(goal, plan="", actions=None, tools_used=None, result="",
                      success=None, score=None, lessons=None, agent=None, skill=None):
    """Assemble one experience record. `score`/`lessons` default to derived
    values (score_experience(success), extract_lessons(...)) when not given
    explicitly, so a caller that just has the raw outcome doesn't have to
    compute either itself."""
    experience = {
        "goal": goal,
        "plan": plan,
        "actions": list(actions) if actions else [],
        "tools_used": list(tools_used) if tools_used else [],
        "result": result,
        "success": success,
        "score": score if score is not None else score_experience(success),
        "lessons": [],
        "timestamp": datetime.now().isoformat(),
        "agent": agent,
        "skill": skill,
    }
    experience["lessons"] = list(lessons) if lessons is not None else extract_lessons(experience)
    return experience


def score_experience(success):
    """A deliberately simple first pass: 1.0 if the action succeeded, 0.0 if
    it failed or was never attempted. Not a real continuous quality metric -
    see the module docstring."""
    return 1.0 if success else 0.0


def extract_lessons(experience):
    """Rule-based lessons from the fields already on the record - no model
    call. Real reflective lesson extraction (why did this fail, what should
    change) is Phase 6's `learning/` engine's job, not this one."""
    lessons = []
    goal = experience.get("goal", "an action")
    if experience.get("success") is True:
        lessons.append(f"Succeeded: {goal}.")
    elif experience.get("success") is False:
        result = experience.get("result", "")
        detail = f" ({result[:120]})" if result else ""
        lessons.append(f"Failed: {goal}{detail}.")
    else:
        lessons.append(f"Not attempted: {goal}.")
    return lessons


def record_experience(experience):
    """Append one experience record to the on-disk log (JSON Lines - one
    record per line, so recording never requires rewriting the whole
    file). The only function in this module that creates the experience/
    directory - a read (load_experiences) must never have the side effect
    of creating on-disk state that wasn't there before."""
    log_path = _experience_log_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(experience) + "\n")
    return experience


def load_experiences(limit=None, skill=None, success=None):
    """Read every recorded experience, optionally filtered by `skill` name
    or `success` state, most recent last. `limit` returns only the last N
    matching records."""
    path = _experience_log_path()
    if not os.path.isfile(path):
        return []
    experiences = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                experiences.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if skill is not None:
        experiences = [e for e in experiences if e.get("skill") == skill]
    if success is not None:
        experiences = [e for e in experiences if e.get("success") == success]
    if limit is not None:
        experiences = experiences[-limit:]
    return experiences


def experience_to_knowledge(experience):
    """Write a human-readable summary of an experience into the knowledge
    base via the real knowledge.write tool, so a lesson persists somewhere
    discoverable (/archives, knowledge.search) instead of only in the raw
    JSON Lines log."""
    lines = [
        f"Goal: {experience.get('goal', '')}",
        f"Success: {experience.get('success')}",
        f"Result: {experience.get('result', '')}",
        f"Tools used: {', '.join(experience.get('tools_used', []))}",
        "Lessons:",
    ]
    lines.extend(f"- {lesson}" for lesson in experience.get("lessons", []))
    content = "\n".join(lines)
    timestamp = experience.get("timestamp", datetime.now().isoformat()).replace(":", "-")
    filename = f"experience_{timestamp}.txt"
    tool_registry.execute("knowledge.write", filename=filename, content=content)
    return filename
