"""The Critic: rule-based pattern detection over recent failures - not a
model call. A model asked "what's wrong lately" tends to produce a
plausible-sounding narrative whether or not there's a real pattern; simple
counting over structured fields (goal, tools_used) can't do that. Real
reflective judgment (why does this keep happening, what should change) is
left to a human reading these findings, not invented here.
"""
from memory.experience import load_experiences

MIN_PATTERN_COUNT = 2


def critique_recent_failures(agent=None, skill=None, window=10, min_pattern_count=MIN_PATTERN_COUNT):
    """Look at the most recent `window` experiences and surface two kinds
    of pattern, each only reported once it recurs at least
    `min_pattern_count` times (a single failure is just a failure, not a
    pattern worth flagging):

    - the same `goal` failing more than once (a stuck loop - the same
      target keeps getting attempted and keeps not working)
    - the same tool showing up as the *last* tool used before failure more
      than once (a stage-level weak point - e.g. test.run failing
      repeatedly suggests the test-generation step, not the fix step)

    Returns a list of finding dicts, most-frequent first.
    """
    experiences = load_experiences(skill=skill)
    if agent is not None:
        experiences = [e for e in experiences if e.get("agent") == agent]
    failures = [e for e in experiences[-window:] if e.get("success") is False]

    goal_counts = {}
    last_tool_counts = {}
    for failure in failures:
        goal = failure.get("goal", "")
        if goal:
            goal_counts[goal] = goal_counts.get(goal, 0) + 1
        tools_used = failure.get("tools_used") or []
        if tools_used:
            last_tool = tools_used[-1]
            last_tool_counts[last_tool] = last_tool_counts.get(last_tool, 0) + 1

    findings = []
    for goal, count in goal_counts.items():
        if count >= min_pattern_count:
            findings.append({
                "pattern": "repeated_goal_failure", "goal": goal, "count": count,
                "summary": f"'{goal}' has failed {count} times recently - likely stuck, not just unlucky.",
            })
    for tool, count in last_tool_counts.items():
        if count >= min_pattern_count:
            findings.append({
                "pattern": "stage_failure", "tool": tool, "count": count,
                "summary": f"{count} recent failures happened at the '{tool}' stage.",
            })
    return sorted(findings, key=lambda f: f["count"], reverse=True)
