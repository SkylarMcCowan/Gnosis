"""observability.*: Phase 13, built on top of what Phase 5/6/12 already
record - not a new data-collection layer, a set of real queries over data
that already exists (memory/experience.py's Experience log, core/activity_log.py's
event log). "Agent performance," "Generated-tool success," "Generated-skill
success," and "Learning outcomes" from this phase's own checklist aren't
duplicated here at all - `learning/evaluator.py`'s `evaluate_recent_performance`
and `learning/reflection.py`'s `consolidated_lessons` already answer them
(just call either with `agent="tool-generator"` for the generated-skill
case); re-implementing the same query under a different name here would be
duplication, not a new capability.

Deliberately not built, for stated reasons rather than left silently
missing:
- Token/model usage, Execution time: the obvious place to capture this is
  `core/models.py`'s `chat()` funnel - every model call in the whole app
  passes through it. But adding a real subscriber's disk-writing side
  effect there would touch every one of the ~15 existing tests across
  `test_fact_check.py`/`test_fallback_research_query.py`/`test_smoke.py`
  that mock a model call without `isolated_data_dir`, since none of them
  were ever written expecting `chat()` to touch disk. Retrofitting
  isolation onto all of them is a disproportionate blast radius for this
  one metric; a real implementation wants a different design (e.g. opt-in
  instrumentation) that deserves its own pass, not a guess forced in here.
- Regression rate: `learning/experiments.py`'s `run_learning_experiment`
  already computes a `regressed` flag, but nothing in production calls it
  yet, so there's no real historical data to report a *rate* over.
- User approval rate: no existing signal tracks whether a human actually
  kept or discarded a staged self-improve fix / Phase 9 proposal - that
  would need new tracking (e.g. detecting a matching commit), not a query
  over data that already exists.
- UI/browser-based dashboard: a text report (the new `/report` command)
  substitutes for now; a real browser UI is a separate, larger undertaking.
- Prompt size monitoring/warnings, file truncation: substantially already
  covered by the existing `_SELFIMPROVE_MAX_TARGET_BYTES` hard cap
  (webagent.py) - self-improve rejects an oversized candidate outright
  rather than truncating it into the prompt. A truncate-and-include
  strategy would be a genuinely different design choice, not attempted here.
- Caching for repo audits/file reads, incremental analysis: no observed
  real performance problem to justify either yet - self-improve runs
  infrequently (once per cycle).
"""
