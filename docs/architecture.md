# Architecture

Generated from each package's own docstring - do not hand-edit; run `python3 scripts/generate_docs.py` instead.


## `builder/`

builder.*: Phase 9's Self-Generated Tools pipeline - CAPABILITY GAP → DESIGN → GENERATE → GENERATE TESTS → SANDBOX → RUN TESTS → PROPOSAL.

## `core/`

core.*: Phase 1's orchestration layer that turned webagent.py from a monolith into a thin registrant - config (project_root), context (the shared Context object every module reads/writes instead of a captured global), command_router (dispatch), orchestrator (the main loop), models (the Ollama chat() funnel), events (the pub/sub bus, wired for real in Phase 12), and activity_log (Phase 12's real subscriber for it).

## `docgen/`

docgen.*: Phase 14, scoped to what can be generated *from real, already-existing structure* rather than written by hand or invented by a model - a tool/skill reference from the real registries, an architecture map from each package's own docstring, a command reference from `/help`'s own real output. Each generator takes its source data injected (a list of Tool/Skill instances, a dict of docstrings, a help-text string) rather than importing webagent.py or the registries itself, same DI discipline as tools/skills/builder - `scripts/generate_docs.py` is what actually wires real data in.

## `governance/`

governance.*: Phase 15, scoped exactly to what was decided in conversation rather than assumed - three real questions, three explicit answers:

## `learning/`

learning.*: Phase 6's Learning Engine, built as far as there's a real feedback loop to learn from - currently just one: `run_self_improve_cycle`, instrumented by Phase 5's Experience System. `evaluator.py` (recent performance), `critic.py` (failure-pattern detection), `reflection.py` (cross-experience lesson aggregation), and `experiments.py` (a batch runner that compares a fresh window of runs against history) all operate purely on `memory.experience`'s recorded dicts - none of them import webagent.py.

## `memory/`

memory.*: Phase 4/5's memory concepts, built out only as far as there's a real behavior to attach to. `experience.py` (Phase 5) is the first real piece - a structured record of what an autonomous action (currently: run_self_improve_cycle) tried, whether it worked, and what to learn from it. `episodic.py`/`semantic.py`/`working.py`/`user.py` from the roadmap's own Phase 4 sketch aren't built - the one concrete Phase 4 bug (the static user-profile-injection fix) landed directly in webagent.py instead, since creating a package for a single function would be structure with no other member yet.

## `observability/`

observability.*: Phase 13, built on top of what Phase 5/6/12 already record - not a new data-collection layer, a set of real queries over data that already exists (memory/experience.py's Experience log, core/activity_log.py's event log). "Agent performance," "Generated-tool success," "Generated-skill success," and "Learning outcomes" from this phase's own checklist aren't duplicated here at all - `learning/evaluator.py`'s `evaluate_recent_performance` and `learning/reflection.py`'s `consolidated_lessons` already answer them (just call either with `agent="tool-generator"` for the generated-skill case); re-implementing the same query under a different name here would be duplication, not a new capability.

## `planning/`

planning.*: Phase 7's Autonomous Planner, built as far as there's a real decision point for a planner to sit in front of - currently one: run_self_improve_cycle's candidate selection, which used to accept whatever single candidate the model proposed with zero awareness of whether that exact goal had already failed repeatedly.

## `reviewers/`

reviewers.*: Phase 11's Multi-Agent Engineering Team, scoped down to what has real output to review right now - self-improve's applied/dry-run diffs and Phase 9's generated skills. Not new chat personas (the existing `AVAILABLE_AGENTS` roster is conversational, unrelated to this); each reviewer here is a role-flavored model call that looks at a finished artifact and reports what it sees.

## `sandbox/`

sandbox.*: Phase 10's Autonomous Workspace / Sandbox - an isolated git worktree (`workspace.py`'s `Workspace`) that risky operations run inside of, plus a small, fixed command allowlist (`commands.py`) rather than arbitrary shell execution.

## `skills/`

skills.*: Gnosis's Skill registry (Phase 3) - named compositions of already-registered Tools (see skills/base.py's "HOW TO ADD A NEW SKILL"), registered once at webagent.py import time. Never imports webagent.py itself.

## `tools/`

tools.*: Gnosis's Tool registry (Phase 2) - named, invokable-by-name capabilities constructed with their real implementation injected (see tools/base.py's "HOW TO ADD A NEW TOOL"), registered once at webagent.py import time. Never imports webagent.py itself.
