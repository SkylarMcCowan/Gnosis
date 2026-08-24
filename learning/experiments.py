"""The experiment runner: runs a batch of an already-real autonomous action
(injected as `run_cycle_fn` - this module never imports webagent.py, same
discipline as tools/skills) and compares the fresh batch's success rate
against the historical baseline immediately, rather than letting a
regression dilute invisibly into a much longer running average.

Deliberately informational only: this reports whether the fresh batch
regressed, it does not stop, retry, or roll anything back on that basis -
acting on a detected regression is Phase 15's permission-enforcement job,
not this one.
"""
from learning.evaluator import evaluate_recent_performance


def run_learning_experiment(run_cycle_fn, cycles=5, agent=None, skill=None, window=10):
    """`run_cycle_fn` is called `cycles` times with no arguments; it's
    expected to record its own Experience as a side effect the same way
    run_self_improve_cycle already does via Phase 5. Returns
    {"baseline": ..., "fresh_batch": ..., "regressed": bool}, comparing the
    `window` experiences before this batch against exactly this batch."""
    baseline = evaluate_recent_performance(agent=agent, skill=skill, window=window)
    for _ in range(cycles):
        run_cycle_fn()
    fresh_batch = evaluate_recent_performance(agent=agent, skill=skill, window=cycles)
    regressed = (
        baseline["success_rate"] is not None and fresh_batch["success_rate"] is not None
        and fresh_batch["success_rate"] < baseline["success_rate"]
    )
    return {"baseline": baseline, "fresh_batch": fresh_batch, "regressed": regressed}
