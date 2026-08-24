"""Reflection: consolidates the free-text `lessons` Phase 5 already
attaches to every Experience into one deduplicated, frequency-ranked list
- turning "N separate records each say roughly the same thing" into "here
is the one thing worth paying attention to, and how often it's come up."

Distinct from critic.py: the critic pattern-matches structured fields
(goal, tools_used) to find *where* things are going wrong; this
consolidates the *lessons* already recorded to summarize what's been
learned, independent of any single experience's phrasing.
"""
from memory.experience import load_experiences


def consolidated_lessons(agent=None, skill=None, window=10):
    """Return {lesson: count} for every distinct lesson text seen across
    the most recent `window` experiences, most-frequent first, as a list of
    (lesson, count) tuples."""
    experiences = load_experiences(skill=skill)
    if agent is not None:
        experiences = [e for e in experiences if e.get("agent") == agent]
    recent = experiences[-window:]

    counts = {}
    for experience in recent:
        for lesson in experience.get("lessons", []):
            counts[lesson] = counts.get(lesson, 0) + 1
    return sorted(counts.items(), key=lambda pair: pair[1], reverse=True)
