"""planning.*: Phase 7's Autonomous Planner, built as far as there's a
real decision point for a planner to sit in front of - currently one:
run_self_improve_cycle's candidate selection, which used to accept
whatever single candidate the model proposed with zero awareness of
whether that exact goal had already failed repeatedly.

`planner.py` (`is_stuck_goal`) is the only file built. `goals.py`/
`priorities.py`/`task_queue.py`/`scheduler.py` from the roadmap's own
sketch each need a real multi-goal backlog to operate on - something to
rank, queue, or schedule *across* - and none exists: there is exactly one
goal proposed at a time in the whole codebase today, not a pool of
competing candidates. Building those now would mean inventing a queue
with nothing real to put in it.
"""
