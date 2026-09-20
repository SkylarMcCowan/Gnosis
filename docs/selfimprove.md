# Self-Improve

`/selfimprove` (and the identically-behaved `feature: selfimprove` cron
action) runs a real, end-to-end cycle: it picks exactly one small, concrete
improvement to an existing Python file, writes the fix and a test for it,
runs the test suite, and either leaves the change staged for human review or
discards it automatically on failure. It never commits or pushes.

Both entry points call the same function, `run_self_improve_cycle(dry_run=False)`
in `webagent.py`:

1. **Preflight** — requires a clean `git status --porcelain`. This also acts
   as a mutex: an applied change that hasn't been reviewed/committed yet
   blocks the next run instead of piling changes on top of it.
2. **Audit** the repository and optionally read `TODO.md` for context (not a
   hard restriction — the model can also act on anything the audit surfaces).
3. **Select one candidate** — a coding-model call proposes a single target
   file, which must already exist, be tracked by git, be a `.py` file, and
   be under an 80KB size cap. If that exact goal ("Fix `<file>`: `<issue>`")
   has already failed repeatedly in recent history, it's skipped rather than
   retried unchanged (`planning/planner.py`'s `is_stuck_goal`, backed by
   `learning/critic.py`'s failure-pattern detection).
4. **Everything from here on happens inside an isolated sandbox** —
   `sandbox/workspace.py`'s `Workspace`, a real `git worktree` checked out
   from the live repo's current commit. The live checkout is never touched
   until step 7, and on any failure there's nothing to revert: the workspace
   is simply destroyed.
5. **Generate the fix** — a full-file replacement (not a diff), plus a
   companion unit test that must contain a real assertion against the fixed
   module, not just `assert True`. Both are written inside the workspace.
6. **Compile-check and run the test suite** inside the workspace.
   `python -m unittest discover` must exit 0 *and* report `Ran N tests` with
   `N > 0`.
7. **On success**, `workspace.merge_back(...)` copies exactly the changed
   files into the live repo — still uncommitted, staged for review. **On
   failure**, nothing happens to the live repo at all; the workspace is
   destroyed with it. Either way, an "engineering team" review panel
   (Security/Performance/Documentation Reviewer, plus a deterministic
   Release Manager recommendation — see `reviewers/`) runs over the real
   diff and is appended to the report. These reviews are informational only
   and never change the outcome.
8. **Every outcome is recorded as a structured Experience**
   (`memory/experience.py`) — goal, tools used, success (`True`/`False`/
   `None` for "never attempted," e.g. blocked), and a short lesson. `/learning`
   reports on this history; `/report` reports on it alongside search/tool/
   task metrics.

Every run also writes a dated markdown report to
`knowledge_base/selfimprove_reports/`.

## Dry-run / preview mode

`/selfimprove preview` (alias `/selfimprove --dry-run`, matching
`/historian`'s existing alias convention) runs every real step identically —
candidate selection, fix generation, compiling, running the actual test
suite, the review panel — inside the same isolated workspace. The only
difference is the last step: it never calls `merge_back()`, and the report
shows the verified `git diff` instead of "changed files, staged for review."
Not a simulation — the fix is genuinely built and genuinely tested; the live
repo is just never written to.

## Related commands

- `/learning` — self-improve's recent success rate, detected failure
  patterns, and consolidated lessons (`learning/evaluator.py`, `critic.py`,
  `reflection.py`).
- `/generate` — a related but distinct pipeline: looks for a *recurring*
  capability gap (via the same critic) and, if one exists, designs and
  sandbox-tests a brand new *Skill* to address it, always writing a
  proposal (`gnosis_workspace/proposals/`) rather than a fix to an existing
  file. Never auto-registered.
- `/report` — cross-cutting observability: task completion, search quality,
  tool usage, and self-improve/tool-generation performance
  (`observability/metrics.py`).

## Environment variables

Self-improve itself takes no environment variables or CLI flags of its own.
The one environment variable the whole app reads is `SEARXNG_URL` (default
`https://search.lozdev.com`), used by web search generally, not
self-improve specifically.

## Safe usage notes

- Self-improve **never commits or pushes** — every applied change sits
  uncommitted until a human reviews `git diff` and commits by hand.
- File size is capped (`_SELFIMPROVE_MAX_TARGET_BYTES`, 80KB) — an oversized
  candidate is rejected outright, never truncated into a prompt.
- The sandbox (`sandbox/workspace.py`) isolates git-tracked project files
  via a worktree; it is **not** OS-level sandboxing — a generated test is
  still real Python running as a real subprocess. That's exactly why
  `/generate`'s output is never trusted automatically.
- See `docs/cron.md`'s "The `selfimprove` feature" section for the full
  cron-scheduling safety mechanics, and for how to schedule it nightly via
  `/cron add <schedule> feature: selfimprove`.

## Nightly knowledge learning

The unattended knowledge-learning pipeline is separate from code repair. See
[nightly_learning.md](nightly_learning.md) for the idle-aware macOS schedule,
source-backed study notes, persistent retrieval index, and recovery controls.
