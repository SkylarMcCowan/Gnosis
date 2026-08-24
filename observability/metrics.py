"""Real queries over data Phase 5/6/12 already record - see
observability/__init__.py for what's deliberately not here and why.
"""
import re

from core.activity_log import load_activity
from memory.experience import load_experiences

_GOAL_TARGET_FILE_RE = re.compile(r"^Fix (\S+):")


def tool_usage_stats(agent=None, window=None):
    """For each tool name appearing in any recorded Experience's
    `tools_used`, how many times it was used and what fraction of
    *attempted* uses (success is True or False) succeeded - a coarser but
    real proxy for "Tool success/failure rate," since no experience
    currently tracks an individual tool's own outcome, only the outcome of
    the goal it was used towards. `success=None` ("not attempted" - e.g. a
    blocked self-improve cycle) is excluded from the rate's denominator
    entirely, same three-state discipline as learning/evaluator.py's
    evaluate_recent_performance - collapsing "not attempted" into "failed"
    would misrepresent a tool that's simply never been given a real shot."""
    experiences = load_experiences()
    if agent is not None:
        experiences = [e for e in experiences if e.get("agent") == agent]
    if window is not None:
        experiences = experiences[-window:]
    stats = {}
    for experience in experiences:
        success = experience.get("success")
        for tool_name in experience.get("tools_used") or []:
            entry = stats.setdefault(tool_name, {"used": 0, "attempted": 0, "succeeded": 0})
            entry["used"] += 1
            if success is not None:
                entry["attempted"] += 1
                if success is True:
                    entry["succeeded"] += 1
    return {
        name: {**entry, "success_rate": (entry["succeeded"] / entry["attempted"]) if entry["attempted"] else None}
        for name, entry in stats.items()
    }


def search_quality_stats(window=None):
    """From core.activity_log's real SEARCH_COMPLETED history: how many
    searches returned nothing, and the average result count."""
    entries = load_activity(event_name="SEARCH_COMPLETED", limit=window)
    if not entries:
        return {"total_searches": 0, "zero_result_searches": 0, "zero_result_rate": None, "avg_result_count": None}
    total = len(entries)
    zero_result = sum(1 for e in entries if e.get("result_count") == 0)
    avg_result_count = sum(e.get("result_count", 0) for e in entries) / total
    return {
        "total_searches": total, "zero_result_searches": zero_result,
        "zero_result_rate": zero_result / total, "avg_result_count": avg_result_count,
    }


def task_completion_stats(window=None):
    """From core.activity_log's real TASK_COMPLETED history: how many
    persona-driven chat turns completed, broken down by agent."""
    entries = load_activity(event_name="TASK_COMPLETED", limit=window)
    by_agent = {}
    for entry in entries:
        agent_name = entry.get("agent_name", "unknown")
        by_agent[agent_name] = by_agent.get(agent_name, 0) + 1
    return {"total_completed": len(entries), "by_agent": by_agent}


def self_improve_target_file_stats(window=None):
    """Analytics on what self-improve has actually changed over time -
    parses the target file back out of each recorded goal string
    ("Fix <target_file>: <issue>", set by run_self_improve_cycle)."""
    experiences = [e for e in load_experiences() if e.get("agent") == "self-improve"]
    if window is not None:
        experiences = experiences[-window:]
    stats = {}
    for experience in experiences:
        match = _GOAL_TARGET_FILE_RE.match(experience.get("goal", "") or "")
        if not match:
            continue
        target_file = match.group(1)
        entry = stats.setdefault(target_file, {"attempts": 0, "succeeded": 0})
        entry["attempts"] += 1
        if experience.get("success") is True:
            entry["succeeded"] += 1
    return stats
