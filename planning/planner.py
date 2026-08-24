"""The planner's one real decision: should a proposed goal actually be
attempted, or has it already failed enough times recently that attempting
it again unchanged would just be repeating the same mistake?

Built on Phase 6's critic rather than duplicating its pattern-matching -
`is_stuck_goal` is a thin, named check over `critique_recent_failures`'s
`repeated_goal_failure` findings, kept as its own function (rather than
inlined at the one call site) so a second real decision point, when one
exists, has something to import instead of copy-pasting the check.
"""
from learning.critic import critique_recent_failures


def is_stuck_goal(goal, agent=None, window=10, min_pattern_count=2):
    """True if `goal` has already failed at least `min_pattern_count`
    times in the most recent `window` experiences for `agent` - i.e. it
    shows up as a `repeated_goal_failure` finding from the critic."""
    findings = critique_recent_failures(agent=agent, window=window, min_pattern_count=min_pattern_count)
    return any(f["pattern"] == "repeated_goal_failure" and f["goal"] == goal for f in findings)
