"""learning.*: Phase 6's Learning Engine, built as far as there's a real
feedback loop to learn from - currently just one: `run_self_improve_cycle`,
instrumented by Phase 5's Experience System. `evaluator.py` (recent
performance), `critic.py` (failure-pattern detection), `reflection.py`
(cross-experience lesson aggregation), and `experiments.py` (a batch runner
that compares a fresh window of runs against history) all operate purely on
`memory.experience`'s recorded dicts - none of them import webagent.py.

`consolidation.py`, named in the roadmap's own sketch, isn't built: nothing
in Phase 6's actual checklist maps to a distinct consolidation step beyond
what `reflection.py` already does, and inventing a second module to hold
nothing real would just be structure with no member.

Everything here is informational, not enforcing - it reports patterns and
trends for a human (or a future automation) to act on. Actually gating
self-improve runs on these findings is Phase 15's job (permission
enforcement), not this one.
"""
