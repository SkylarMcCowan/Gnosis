"""Regression tests for learning/experiments.py, Phase 6's batch
experiment runner - run_cycle_fn is injected, never webagent.py directly.
"""
from learning.experiments import run_learning_experiment
from memory.experience import build_experience, record_experience


def _record(goal, success):
    record_experience(build_experience(goal=goal, success=success))


def test_run_learning_experiment_calls_run_cycle_fn_the_requested_number_of_times(isolated_data_dir):
    calls = []
    run_learning_experiment(lambda: calls.append(True) or _record("cycle", True), cycles=3)
    assert len(calls) == 3


def test_run_learning_experiment_detects_a_regression(isolated_data_dir):
    # Baseline: 2/2 succeeded.
    _record("a", True)
    _record("b", True)

    # Fresh batch: 1/2 succeeded - a real regression.
    fresh_results = iter([True, False])
    result = run_learning_experiment(lambda: _record("new", next(fresh_results)), cycles=2, window=2)

    assert result["baseline"]["success_rate"] == 1.0
    assert result["fresh_batch"]["success_rate"] == 0.5
    assert result["regressed"] is True


def test_run_learning_experiment_no_regression_when_performance_holds(isolated_data_dir):
    _record("a", True)
    _record("b", False)  # baseline 0.5

    result = run_learning_experiment(lambda: _record("new", True), cycles=2, window=2)

    assert result["baseline"]["success_rate"] == 0.5
    assert result["fresh_batch"]["success_rate"] == 1.0
    assert result["regressed"] is False


def test_run_learning_experiment_regressed_is_false_with_no_baseline_data(isolated_data_dir):
    result = run_learning_experiment(lambda: _record("new", True), cycles=1)
    assert result["baseline"]["success_rate"] is None
    assert result["regressed"] is False
