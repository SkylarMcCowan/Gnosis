# Gnosis — Code Quality Audit (stubbed/boilerplate/half-baked)

Snapshot audit of the repo as of 2026-08-25, looking specifically for
unfinished work: stubbed-out code, boilerplate copy-pasted but never filled
in, and things that look implemented but have an obvious functional gap.
This is deliberately separate from `TODO.md` (the phased feature roadmap) -
`TODO.md`'s own already-tracked pending items (Phase 17's real on-screen
verification, visual polish pass, "CLI surface not yet in GUI") are NOT
repeated here. Every item below was traced through the actual code, not
guessed at from a comment alone.

**Status: 6 of 7 fixed same-day (724 tests passing, up from 714); #5 is a
deliberate no-op, not a gap left open.**

---

## 🔴 High

### 1. Chat can't answer "what am I subscribed to?" ✅ fixed
A real user query, verbatim: *"give me an update on my subscriptions?"*
Traced end to end - it produces a nonsense web search
(`{"query": "current subscriptions for you"}`) instead of reading
`core.subscriptions.list_subscriptions()`.

Root cause: `_matching_subscription` (`webagent.py:2665-2674`) only fires
when the raw prompt contains a specific subscription's *name or keyword* -
it's built to answer "what's new with Manchester United," not a meta
question about the list itself. No `subscriptions.*` Tool is registered at
all (`webagent.py:7543-7568` lists all 22 registered tools, none touch
`core/subscriptions.py`), and `_select_tool_action`'s planner prompt
(`webagent.py:1631-1637`) never mentions subscriptions as something the
model is allowed to route to.

**Fixed**: registered a new `subscriptions.list` SAFE tool
(`tools/subscriptions/list.py`, wrapping `core.subscriptions.list_subscriptions`),
picked up automatically by `_available_tool_actions`, with a
`_summarize_tool_result` branch and the planner prompt extended to mention
subscriptions as an allowed topic (`webagent.py`'s `_select_tool_action`).
Follows `cron.list`'s exact precedent - model-driven selection, no bespoke
regex bypass. Verified end to end: the literal reported prompt now
resolves to `subscriptions.list` and returns the real list instead of a
web search. Tests: `tests/test_tools_subscriptions.py`,
`tests/test_tools_wiring.py`, `tests/test_tool_actions.py`.

### 2. A knowledge-base write failure is silently reported as success ✅ fixed
`record_to_knowledge_base` (`webagent.py:4527-4538`, wired as the
`knowledge.write` tool):
```python
try:
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    events.publish(KNOWLEDGE_UPDATED, filename=safe_filename)
except:
    pass
```
`ResearchTopicSkill.execute` (`skills/research/topic.py:44-45`) calls
`knowledge.write` and, without checking any return value, unconditionally
returns `{"saved": True, "filename": filename}`. If the write fails
(permission error, full disk, bad encoding), the skill still reports the
content as saved under a filename that doesn't exist - and since the
`except: pass` also skips the `KNOWLEDGE_UPDATED` publish, there's no
activity-log trail to catch it after the fact either.

**Fixed**: `record_to_knowledge_base` now catches `OSError` specifically
and returns `True`/`False` instead of swallowing everything and returning
nothing; `ResearchTopicSkill.execute` sets `"saved"` from that real return
value. Confirmed safe: its two other callers (`webagent.py:5386`,
`memory/experience.py:139`) already ignored the return value. Test:
`tests/test_skills_research_topic.py::test_reports_saved_false_when_knowledge_write_actually_fails`.

---

## 🟠 Medium

### 3. Three package docstrings claim "Not implemented yet" for fully-built, wired tools ✅ fixed
All copy-pasted from before these categories existed, never updated:
- `tools/knowledge/__init__.py:1-6` - `knowledge.search`/`knowledge.write`
  are real, registered (`webagent.py:7545-7546`), tested.
- `tools/scheduler/__init__.py:1-4` - all 5 cron tools are real, registered
  (`webagent.py:7550-7554`), used throughout the cron/alarm flows.
- `tools/shell/__init__.py:1-7` - all 4 shell tools are real, registered
  (`webagent.py:7555-7560`), used in the self-improve pipeline.

Actively misleading to anyone reading the package docstring to understand
current state (nearly caused the audit agent to skip past finding #2).

**Fixed**: rewrote all three docstrings to describe what's actually there
(real tools, permissions, registration point) instead of the copy-pasted
"Not implemented yet" text.

### 4. Cron metadata writes fail silently, independent of the real crontab write ✅ fixed
`_save_cron_tasks` (`webagent.py:5970-5973`):
```python
def _save_cron_tasks(tasks):
    try:
        with open(_cron_tasks_path(), "w", encoding="utf-8") as handle:
            json.dump(tasks, handle, indent=2, ensure_ascii=False)
    except OSError:
        pass
```
`cron_add` correctly checks `_write_crontab`'s return value for the *real*
crontab mutation, but then calls `_save_cron_tasks(tasks)` unconditionally
and returns success regardless of whether Gnosis's own metadata (schedule/
description/`last_run` bookkeeping that `cron_list_entries`/`cron_edit`/
`cron_remove` all depend on) actually persisted. Same unchecked-call
pattern repeated at `webagent.py:6296, 6350, 6380, 6420`
(`cron_edit`/`cron_remove`/`run_cron_task_now`). A real cron job can end up
firing on schedule while Gnosis's own record of what it is silently
vanishes.

**Fixed**: `_save_cron_tasks` now returns `True`/`False` and prints a
visible warning on failure, instead of a bare `except OSError: pass`.
Deliberately did NOT restructure the four call sites'
`(id_or_bool, error_or_None)` contracts - the real crontab write is
already correctly checked separately; this just makes a metadata-only
failure visible instead of silently invisible. Test: `tests/test_cron.py`.

### 5. `ToolRegistry.search`/`SkillRegistry.search` are dead in production — no action taken (by design)
`tools/registry.py:51-56`, `skills/registry.py:57-62` - both honestly
documented as "a placeholder for real semantic search later," but repo-wide
grep confirms nothing in `webagent.py`/`core/`/`tools/`/`skills/` calls
`.search(...)` on either registry outside their own dedicated tests. No
real code path today lets a user or the model actually search available
tools/skills by keyword.

**Decision**: left as-is. Inventing a call site now (e.g. wiring into
`_select_tool_action`) would be speculative future-proofing for a catalog
that's currently small enough not to need keyword narrowing - against this
codebase's own stated principle of not building for hypothetical future
requirements. Recorded here so it's a checked, deliberate non-action, not
a forgotten gap.

---

## 🟡 Low

### 6. Bare `except: pass` file I/O with no logging, same family as #2 but lower individual impact ✅ fixed
`webagent.py:4313` (`load_agent_memory`), `4335` (`save_agent_memory`),
`4540` (`record_learning_path`), `4552` (`load_learning_paths`), `4571`
(`search_knowledge_base`), `6895` (agent insight save). Each swallows a
real read/write error with zero logging and no comment explaining why it's
safe - unlike the rest of this codebase, which is otherwise careful to
comment every deliberate silent-failure decision (see e.g.
`core/activity_log.py`'s `clear_activity`'s documented `FileNotFoundError`
catch). Mostly self-heals to an empty default on a read failure, so lower
urgency than #2/#4, but worth a pass to at least log.

**Fixed**: narrowed every bare `except:` above to `except OSError:` (plus
`json.JSONDecodeError` for the two agent-memory sites that parse JSON -
caught a real latent `UnboundLocalError` risk while doing this: both had a
redundant local `import json` shadowing the module-level import, which
would have raised `UnboundLocalError` instead of catching the intended
exception if `open()` itself failed before that local import line ran;
removed the redundant local imports). Added a `Fore.YELLOW` failure
warning on the three *write* paths (`save_agent_memory`,
`record_learning_path`, the agent-insight save - the last one already had
a matching `Fore.GREEN` success print). Left the *read* paths silent (a
missing/corrupt file self-healing to `[]`/`{}` isn't worth a console
warning every time).

### 7. Dead code left over in `webagent_gui.py` from prior implementations ✅ fixed
- `self.search_worker = None` (`webagent_gui.py:585`) - set once in
  `__init__`, never assigned or read anywhere else in the file.
- `import threading` (line 7), `import asyncio` (line 8) - neither is
  referenced anywhere in the 1848-line file.
- `QListWidgetItem` (imported line 33) - confirmed unused as of this
  session's Subscriptions-page rewrite: the old flat `QListWidget` +
  `QListWidgetItem` subscriptions list was replaced with a button-grid
  catalog, and nothing else in the file still uses `QListWidgetItem`.

**Fixed**: all four removed.

---

## Not flagged (checked and ruled out, listed so it isn't re-investigated)

- `MODELS['search'] = 'qwen3.5:2b'` (`core/models.py:32`) looks like a
  possible typo'd model tag - confirmed real and live-tested per
  `TODO.md:740-743`.
- `tools/communication/__init__.py` and the empty
  `skills/{documentation,coding,system_management}/__init__.py` packages
  say "not implemented yet" - accurate, their directories genuinely
  contain nothing else. Not stale.
- No bare `pass`-only/`...`-only function bodies or unconditional
  `NotImplementedError`s exist outside `tools/base.py:83` and
  `skills/base.py:69`, both legitimate `@abstractmethod` markers (AST-
  scanned `webagent.py`, `core/`, `tools/`, `memory/`, `skills/`,
  `builder/`).
- `docs/tools.md`/`docs/architecture.md`/`docs/commands.md` are
  auto-generated and match current code exactly (docs/tools.md's list vs.
  `tools/registry.py`'s 22 registered tools). `docs/feature_inventory.md`
  is an explicitly-dated historical baseline snapshot, not a live claim.
- Every GUI signal/slot connection in `webagent_gui.py` traces to a real,
  matching handler - no no-op or mislabeled button found.
- `tools/live/*.py`'s near-identical ~20-line `Tool` subclasses are an
  intentional dependency-injection pattern (documented in `tools/base.py`'s
  own "HOW TO ADD A NEW TOOL" docstring), not accidental duplication.
- Full test suite collects and passes clean (714 passed, 0 collection
  errors) - no stale test imports or references to removed code.
