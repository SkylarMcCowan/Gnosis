"""memory.*: Phase 4/5's memory concepts, built out only as far as there's a
real behavior to attach to. `experience.py` (Phase 5) is the first real
piece - a structured record of what an autonomous action (currently:
run_self_improve_cycle) tried, whether it worked, and what to learn from
it. `episodic.py`/`semantic.py`/`working.py`/`user.py` from the roadmap's
own Phase 4 sketch aren't built - the one concrete Phase 4 bug (the static
user-profile-injection fix) landed directly in webagent.py instead, since
creating a package for a single function would be structure with no other
member yet.
"""
