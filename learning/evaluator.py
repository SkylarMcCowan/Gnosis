"""The Evaluator: turns raw recorded Experiences into a performance summary
for one real feedback loop - defines what "learning objectives" and
"success metrics" concretely mean here, rather than leaving those as
abstract checklist items with nothing behind them.

LEARNING_OBJECTIVES documents what this evaluates and why; there's exactly
one real objective right now because there's exactly one instrumented
autonomous action (run_self_improve_cycle, via Phase 5). Extending this to
more agents/skills as they get instrumented is just calling
evaluate_recent_performance with a different `agent`/`skill` filter - no
new code needed.
"""
from memory.experience import load_experiences

LEARNING_OBJECTIVES = {
    "self-improve": (
        "Maximize the fraction of attempted self-improve cycles that end in "
        "success=True (a fix applied and kept), without regressing over time."
    ),
}


def evaluate_recent_performance(agent=None, skill=None, window=10):
    """Summarize the most recent `window` experiences matching `agent`/
    `skill` (Phase 5's Experience fields). Distinguishes "attempted"
    (success is True or False) from "not attempted" (success is None,
    e.g. blocked or no candidate found) - a run that correctly did nothing
    should not count against or for the success rate.

    Returns a dict: {"attempted": int, "succeeded": int, "success_rate":
    float|None, "not_attempted": int, "total": int}. success_rate is None
    when nothing was attempted, not 0.0 - "no data yet" and "always fails"
    are different things and 0.0 would conflate them.
    """
    experiences = load_experiences(skill=skill)
    if agent is not None:
        experiences = [e for e in experiences if e.get("agent") == agent]
    recent = experiences[-window:]

    attempted = [e for e in recent if e.get("success") is not None]
    succeeded = [e for e in attempted if e.get("success") is True]
    not_attempted = len(recent) - len(attempted)

    return {
        "total": len(recent),
        "attempted": len(attempted),
        "succeeded": len(succeeded),
        "not_attempted": not_attempted,
        "success_rate": (len(succeeded) / len(attempted)) if attempted else None,
    }
