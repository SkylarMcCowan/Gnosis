"""governance.*: Phase 15, scoped exactly to what was decided in
conversation rather than assumed - three real questions, three explicit
answers:

1. Enforcement only gates *autonomous* callers. A direct, human-typed
   command (e.g. `/cron add`) still goes straight through
   `tools.registry.registry.execute(...)`, completely unchanged - typing
   the command IS the approval. Nothing here touches that path.
2. For an autonomous caller, a `REQUIRES_APPROVAL` (or `RESTRICTED`)
   action is **allowed to proceed** - "the system is for the model to
   control" - but every one is logged clearly via `core.activity_log`, so
   there is always a real, inspectable record of what Gnosis did on its
   own without a human directly behind that specific call.
3. The one thing this doesn't override: `FORBIDDEN`. Nothing autonomous
   ever runs a `FORBIDDEN` action regardless of policy - `FORBIDDEN` is
   supposed to mean never, not "never unless nobody's watching." No tool
   is actually classified `FORBIDDEN` yet, so this is a real ceiling
   with no current occupant, not a currently-active restriction.

`governance/permissions.py`'s `execute_as_autonomous` is the one real
mechanism this phase built. Phase 16's overnight loop is its first real
caller - and Phase 8's "planner-generated tasks" item (deferred there for
exactly the permission-enforcement gap this phase closes) is now
technically unblocked too, though not built here; scope stayed to what
was actually asked for this pass.
"""
