# Cron Task Management

Gnosis can create, edit, list, and remove real entries in the user's system
crontab. There are two interfaces to the same underlying functions:

- `/cron add|edit|list|remove|run` — explicit commands the user types.
- `/job scheduler` — a dedicated agent persona that can create, edit, list,
  and remove tasks **freely and autonomously** from natural language,
  mid-conversation, asking questions first only when it genuinely doesn't
  have enough information yet.

Both call the same `cron_add` / `cron_edit` / `cron_list_entries` /
`cron_remove` / `run_cron_task_now` functions in `webagent.py`, so anything
the Scheduler agent does is exactly as constrained, backed-up, and
inspectable as doing it by hand with `/cron`.

## What a task is allowed to do

A Gnosis-managed cron task can only ever do one of three things:

- Run a saved prompt through the assistant (`chat_response(prompt)`),
- Run one of a fixed whitelist of built-in features: `historian`,
  `historian_preview`, `news`, or `selfimprove` (`CRON_FEATURE_ACTIONS`), or
- Sound an alarm (`_trigger_alarm`) - a real audible + visual alert, not
  generated text (see "Alarms and timers" below).

It can **never** run an arbitrary shell command. This is enforced in
`cron_add` and `_execute_cron_task`, not left to the model's judgment - even
the autonomous Scheduler agent can only produce a directive that these
functions will accept or reject. If asked to schedule a raw shell command,
the Scheduler agent's persona instructs it to refuse and explain why.

This was a deliberate scoping decision: the alternative (arbitrary shell
commands) would mean a locally-run, small language model deciding what
unattended code runs on the user's machine on a schedule, with no code-level
backstop. Restricting tasks to "a prompt through the assistant" or "a named,
already-reviewed feature" keeps the blast radius of a bad model decision
bounded to what those actions can already do.

## The two interfaces

### `/cron` (explicit, human-typed)

- `/cron list` — print every crontab entry, numbered. Gnosis-managed entries
  show their schedule, action, description, and last run status; anything
  else in the crontab (something not created by Gnosis) shows as `(external)`
  with its raw line.
- `/cron add <min> <hour> <day> <month> <weekday> prompt: <text>` or
  `/cron add <min> <hour> <day> <month> <weekday> feature: <name>` — create a
  task. The first five whitespace-separated tokens are the cron schedule; the
  rest of the line is the action, which must start with `prompt:` or
  `feature:`.
- `/cron edit <n> <min> <hour> <day> <month> <weekday> prompt|feature: <text>`
  — change a Gnosis-managed entry `n` in place via `cron_edit`, keeping its
  id and its position in the crontab file. Refuses on a foreign entry, same
  as `/cron run`.
- `/cron remove <n>` — remove entry `n` from the most recent `/cron list`
  numbering. Asks for `y/N` confirmation before writing, since this can
  remove a crontab line Gnosis didn't create (see "Whole-crontab scope"
  below).
- `/cron run <n>` — run a Gnosis-managed entry right now, without waiting for
  its schedule. Refuses on a foreign (`external`) entry — Gnosis doesn't know
  what an unrecognized command actually does and won't execute it outside of
  real cron.

### `/job scheduler` (autonomous, model-driven)

Switching to the Scheduler agent (`switch_agent` in `webagent.py`) makes
`run_scheduler_agent_step` fire on every subsequent message, before the
model's normal reply is generated:

1. `_cron_agent_plan(prompt)` asks the model for a small JSON directive:
   `{"action": "add", "schedule": "...", "type": "prompt"|"feature", "payload": "...", "description": "..."}`,
   `{"action": "edit", "task_id": "...", ...same optional fields...}`,
   `{"action": "remove", "task_id": "..."}`, `{"action": "list"}`, or
   `{"action": "none"}` if the user is just chatting, no scheduling change is
   implied, or there isn't yet enough information to act. The prompt includes
   the current task list (so the model can pick a real `task_id` rather than
   inventing one) and recent conversation history via the existing
   `_planner_history()` helper (already used by the web-research planner).
2. `_cron_agent_execute(action)` validates and actually performs that
   directive through the exact same `cron_add` / `cron_edit` / `cron_remove` /
   `cron_list_entries` functions `/cron` uses, and returns `(acted, message)`.
3. If `acted` is true, `message` - built entirely from real data the
   functions above returned, e.g. `"Done - I've scheduled **Hourly reminder
   to stretch**..."` - is shown to the user **verbatim, as the final reply
   for that turn**. The normal LLM completion is skipped entirely; there is
   no "narrate this" step.

### Why the model never narrates a real action (a bug this caught)

The first version of this fed the action's result to the model as a
grounding system message and then let it generate the reply normally, on the
theory that this mirrors `model_directed_web_research`'s "model proposes,
code executes, result is fed back before the model speaks" pattern. In
practice, asked "every hour remind me to stretch between 8am and 5pm", the
real `cron_add` call worked perfectly - correct schedule `0 8-17 * * *`,
correctly tagged and written to the real crontab - but the model's actual
reply to the user fabricated an entire fictional bash script (`if [ "date
+%H" = "8" ] ...`) and claimed to have "added this task to your cron
schedule" via that script, ignoring the accurate grounding fact it had just
been given. The underlying action was correct; what the user was told about
it was not, and the difference matters a lot when the thing being described
is a real, unattended, scheduled action on their machine.

The fix: `_cron_agent_execute` now returns the literal final answer, not a
fact for the model to paraphrase, and both `chat_response` and the terminal
loop skip the LLM call entirely for a turn where a real action was taken.
The persona explicitly documents this division of labor: the model is only
ever shown to the user to ask a clarifying question or to chat about
scheduling in general - by the time an action would be described as done,
either the user already saw the real, code-generated confirmation instead,
or there wasn't enough information yet and the model should be asking, not
claiming. The persona also explicitly forbids inventing shell script or
implementation detail, since no Gnosis task has ever involved one.

The persona still grants **standing permission** to act - it does not ask
"should I go ahead?" once it has enough information; the real action happens
automatically and its accurate confirmation is what the user sees. The only
thing the model is ever asking about is missing or ambiguous information,
never permission, and never describing an action it didn't itself perform
(it never does - the code does).

#### Asking questions before building, across multiple turns

There's no dedicated "ask a question" action in the JSON schema. Instead,
when the planner doesn't yet have both a clear schedule and clear content (a
prompt or one of the named features), it's instructed to return
`{"action": "none"}` and let the model's own natural-language reply (which
runs normally afterward, per the persona's rule to ask rather than guess)
pose the actual clarifying question. Because `_cron_agent_plan` includes
`_planner_history()`, the *next* call sees the original request, the
assistant's question, and the user's answer together, and can build the
complete task from all of it - the answer alone doesn't need to restate
everything. Verified in testing:

```
turn 1: "remind me to drink water"          -> {"action": "none"}
        (assistant asks what time / how often)
turn 2: "every 2 hours during the day, say 8am to 6pm"
        -> {"action": "add", "schedule": "0 8-18 * * *", "type": "prompt",
            "payload": "reminder to drink water", ...}
```

Turn 2's content ("drink water") came entirely from turn 1 - the planner
correctly combined both messages rather than needing everything restated.

**Known limitation:** the schedule above is `8-18` (every hour, 8am–6pm),
not the step syntax `8-18/2` that "every 2 hours" actually calls for -
`_CRON_FIELD_RE` allows `/` so a correct answer would have validated fine,
the model just didn't choose to use it. Precise cron step-syntax translation
depends on the model's cron knowledge, not on the plan/execute architecture;
double-check an unusual cadence in `/cron list` after asking for one.

## Why the planner uses the coding model, not the active chat model

Both `_cron_agent_plan` and Historian's `_historian_classify_topics` (see
`docs/historian.md`) hit the same problem and use the same fix:
`MODELS.get("coding", ...)` rather than `_selected_model()`.

In testing, asking the general chat model (`yi:6b` in this setup) to plan a
new task from "every weekday morning at 7am, give me a quick news summary" -
while an unrelated existing task with schedule `30 8 * * 1-5` was already in
the list - returned that existing task's time and the wrong feature instead
of parsing the actual request. The coding model (`qwen2.5-coder:7b`)
returned the correct `0 7 * * 1-5` / `feature:news` on the same input. Small
local models being more reliable at structured JSON extraction than at
open-ended chat is a recurring theme in this codebase, not specific to cron.

## Alarms and timers

A cron task's `action_type` can be `"alarm"`: instead of generating text
(`"prompt"`) or running a named feature (`"feature"`), it calls
`_trigger_alarm(message)`, which plays a system sound and shows a blocking,
dismissible dialog - a real audible + visual alert, not a log entry someone
has to go read.

### `_trigger_alarm`: rings until dismissed, not once

The first version of this used a passive `display notification` banner,
which auto-dismisses on its own and can't be waited on. Asked for something
that "goes off till the user hits okay" - the actual expectation for an
alarm clock or timer - it was rebuilt around a blocking `display dialog`
instead:

1. The dialog is launched via `subprocess.Popen` (non-blocking from Python's
   side), with a `giving up after <max_seconds>` clause built into the
   AppleScript itself as a safety net.
2. While the dialog process is still running, the alarm sound
   (`afplay _CRON_ALARM_SOUND`) is replayed every `_ALARM_REPLAY_SECONDS`
   (4s) - so the alarm is audible for as long as it's unacknowledged, not
   just once at the start.
3. It stops when the dialog process exits, either because the user clicked
   Dismiss, or because its own `giving up after` ceiling fired
   (`_ALARM_MAX_SECONDS`, 600s/10 minutes by default) - `_trigger_alarm`
   inspects the dialog's stdout (`gave up:true` vs a real button click) and
   reports which one actually happened, rather than claiming success either
   way.

The 10-minute ceiling is a safety net, not an intentional early stop: without
one, an alarm that truly can't be dismissed (see the GUI-session caveat
below) would hold a process open forever, and a *recurring* alarm task could
stack up multiple such stuck processes before any of them ever exits. It
exists to bound that failure mode, not to shorten a normal, acknowledged
alarm.

This is meant as the building block for pomodoro-style timers later: a
pomodoro cycle is really just two of these back to back (a work-duration
timer, then a break-duration timer), reusing this exact ring-until-dismissed
behavior for each edge. Not built yet - noted here as the natural next step.

### `parse_alarm_time` / `set_alarm`: the natural-language entry point

`set_alarm(description, message=None)` is the single reusable function that
turns a time phrase into a real scheduled alarm - callable from `/cron alarm
<time> message: <text>`, from the autonomous Scheduler agent, or directly
from other code. It has two parts:

- `parse_alarm_time(description)` is a **deterministic, regex-based parser**
  with no LLM call - a fast, dependency-free building block, not a
  conversational feature. It recognizes:
  - Relative durations ("in 12 minutes", "12 mins", "2 hours") → a
    **one-shot** alarm at `now() + duration`, expressed as a specific
    minute/hour/day-of-month/month with weekday left as `*`. Cron has no
    year field, so that alone doesn't guarantee it fires only once - the
    `one_shot` flag is what does that (see below). Durations under a minute
    are rejected outright: cron can't schedule anything closer than that.
  - Absolute clock times, with an optional day pattern ("3am Monday through
    Friday", "every day at 9pm", "weekends at 10am", "every Monday at
    7:30am") → a recurring schedule. No day pattern at all recurs daily.
  - Hour ranges ("8am - 5pm Monday-Friday", "between 8am and 5pm") → fires
    **once per hour** across that range (cron's bare hour-range syntax,
    `H1-H2`), not once at the start time.
  - A bare hour with no am/pm (and not in an unambiguous 24-hour form like
    `15:00`) is rejected, asking for clarification rather than guessing which
    12-hour half was meant - the same "ask, don't guess" default used
    elsewhere in the cron code.
- `set_alarm` calls `parse_alarm_time`, then `cron_add(..., action_type="alarm",
  one_shot=<from the parser>)` - the exact same underlying mechanism as any
  other cron task.

**A real bug this design caught:** the first version of `parse_alarm_time`
only ever extracted a single clock time, with no concept of an hour range.
Asked (via `/cron alarm 8am - 5pm Monday -friday message: stretch!`) to set
an hourly reminder across a range, it silently parsed only "8am" and dropped
"5pm" entirely, producing a task that fired once a day instead of hourly -
wrong, but not obviously wrong; the confirmation message looked entirely
plausible. Range detection (`_ALARM_TIME_RANGE_RE`, matching both `"X - Y"`/
`"X to Y"` and `"between X and Y"` phrasing) was added specifically because
this was caught on a real request against the real crontab, and the
already-created task was corrected in place with `cron_edit` afterward.
Worth remembering: a parser that returns *a* plausible answer instead of an
error on unhandled phrasing can fail silently in exactly this way - test
against the specific phrasing a request actually used, not just the cases
the parser was designed around.

### One-shot self-removal

`cron_add`/`cron_edit` accept a `one_shot` flag, persisted on the task in
`cron/tasks.json`. `run_cron_task_now` - which both `/cron run` and the real
`--cron-task` headless path call - checks this flag right after a task
finishes running and, if set, removes the task from both the crontab and the
manifest via the same `cron_remove` used for a manual `/cron remove`. This is
what makes a relative-duration timer ("in 12 minutes") actually one-shot: the
schedule fields alone (a specific minute/hour/day/month) would otherwise
fire again on the same calendar date next year, since cron has no year field.

### A real, separate risk: cron vs. the GUI session

Diagnosing why a test alarm produced no visible sound or dialog surfaced two
distinct concerns, worth keeping separate:

1. **This assistant's own tool-execution shell** appears not to be attached
   to a real GUI session at all: a diagnostic blocking `display dialog` call
   returned a fabricated-looking `button returned:OK` in well under a
   second - no human clicked anything that fast. This means testing
   `_trigger_alarm` *from inside this assistant* can't reliably confirm
   whether it works for real; a result of "success" from here isn't
   trustworthy evidence either way. Test it by running it directly in a real
   Terminal window instead.
2. **Separately, and regardless of the above:** processes launched by
   traditional `cron` (as opposed to a per-user `launchd` LaunchAgent) are, on
   modern macOS, often not part of the logged-in user's GUI session bootstrap
   namespace at all - a real, independent reason `display dialog`/`display
   notification` can silently fail to render anything when triggered by a
   genuine, unattended cron firing, even outside any coding-agent sandbox. If
   alarms consistently work when run directly but not when actually triggered
   by cron, this is why, and the fix is to run alarm-type tasks via a
   `launchd` LaunchAgent instead of plain crontab - a larger change than
   anything implemented so far, not yet built.

## The `selfimprove` feature

`selfimprove` (and `/selfimprove`, its interactive twin - both call the same
`run_self_improve_cycle()`) is the riskiest entry in the feature whitelist
because it writes to the repository's own source files, not just to
`knowledge_base/`. Its safety mechanics are enforced in code, the same
"code enforces the boundary, not model judgment" principle as the rest of
this system:

- **Clean-tree precondition, doubling as a mutex.** It refuses to run at all
  unless `git status --porcelain` is empty. This means a run's own
  (uncommitted, by design) output blocks the *next* run until a human commits
  or discards it - nightly runs can never pile changes on top of each other.
  The report distinguishes "blocked: still awaiting review of last run's
  change" from "blocked: unrelated uncommitted work" by checking whether the
  dirty paths match what the previous run touched (recorded in
  `knowledge_base/selfimprove_reports/.last_run.json`).
- **One small, scoped change per run.** A single coding-model call proposes
  exactly one target file - which must already exist, be tracked by git, be a
  `.py` file, and be under an 80KB size cap (full-file rewrite is the whole
  strategy, and that's only reliable at local-model scale for a bounded
  file). `webagent.py` and `webagent_gui.py` are denylisted by name as
  defense-in-depth, on top of being excluded by size anyway.
- **Full-file replacement, not a diff.** Small local models routinely emit
  diffs with wrong line numbers/context that fail to apply; the model is
  asked for the complete new file content instead, parsed strictly from a
  `### {relpath}` + fenced-block convention, with the header checked against
  the expected path rather than accepting the first `###`-prefixed block found.
- **No fix without a passing test.** A second, separate coding-model call
  must produce a real test (containing an actual assertion against something
  imported from the fixed module, checked via `ast`, not just `assert True`)
  before anything is written to disk. `python -m unittest discover` must
  then both exit 0 *and* report `Ran N tests` with `N > 0` - a 0-tests
  "pass" is treated as a failure, since that was the exact vacuous-pass bug
  in the validator this replaced.
- **Sandboxed, never auto-commit.** Everything from candidate-fix generation
  through compiling and testing happens inside an isolated `git worktree`
  (`sandbox/workspace.py`'s `Workspace`), not the live checkout. A compile
  or test failure means nothing more than destroying that throwaway
  workspace - there is no revert logic to get wrong, because the live repo
  was never touched. A success calls `workspace.merge_back(...)`, copying
  exactly the changed files into the live repo as an **uncommitted**
  working-tree change - a human always reviews `git diff` and commits by
  hand; the pipeline itself never runs `git commit` or `git push`.
- **Won't retry a goal that's already stuck.** If the exact same
  `"Fix <file>: <issue>"` goal has failed repeatedly in recent history
  (`learning/critic.py`'s failure-pattern detection), it's skipped instead
  of being proposed again unchanged (`planning/planner.py`'s `is_stuck_goal`).

Every run - blocked, no-candidate, reverted, or applied - writes a dated
report to `knowledge_base/selfimprove_reports/`, and is also recorded as a
structured Experience (`memory/experience.py`) that `/learning` and
`/report` read from. See `docs/selfimprove.md` for dry-run mode
(`/selfimprove preview`) and the engineering-team review panel appended to
every applied/dry-run report.

## Crontab safety mechanics

- **Full-crontab scope, by design.** Unlike a stricter "only ever touch a
  tagged block" design, Gnosis here can list and remove *any* crontab entry,
  including ones it didn't create (shown as `external` in `/cron list`).
  This was an explicit choice to let `/cron` (and the Scheduler agent) be a
  real management interface for the whole crontab, not just Gnosis's own
  corner of it. The trade-off: `/cron remove` on the wrong index can delete
  someone else's job, which is why it always asks for confirmation and always
  backs up first.
- **Every write is backed up first.** `_write_crontab` saves the crontab's
  current contents to `cron/backups/<timestamp>.crontab` before replacing it,
  every single time - both for `/cron add`/`remove` and for anything the
  Scheduler agent does. If something goes wrong, the previous state is on
  disk.
- **Gnosis entries are tagged, not guessed at.** Every task Gnosis creates is
  preceded by a `# gnosis:<8-hex-id> <description>` comment line
  (`_cron_marker_line`). `_parse_crontab_entries` treats that comment plus
  the schedule line immediately after it as one removable unit; a schedule
  line with no such comment above it is a `foreign` entry. This is how
  `/cron list` can label ownership and how removal knows to take both lines
  together for a Gnosis entry but just the one line for a foreign one.
- **The manifest (`cron/tasks.json`) is the source of truth for what a task
  *does*.** The crontab line itself only carries a task id
  (`--cron-task <id>`); the actual prompt text or feature name lives in the
  manifest, keyed by id. This avoids shell-escaping an arbitrary user prompt
  directly into a crontab line, and lets a task's `last_run` /
  `last_status` be tracked without touching the crontab at all. It also means
  `cron_edit` can change *what* a task does (prompt text, feature) by only
  rewriting the manifest - the crontab line only needs to change when the
  *schedule* changes, and even then only its leading 5 fields are rewritten;
  the command portion (still `--cron-task <same id>`) is left untouched, so
  the task keeps its id and its position in the file across edits.

## How a task actually runs unattended

The crontab line Gnosis writes (`_cron_shell_command`) is:

```
cd <project dir> && <venv python> <path to webagent.py> --cron-task <id> >> cron/logs/<id>.log 2>&1
```

At the bottom of `webagent.py`, `if __name__ == "__main__":` checks for
`--cron-task <id>` *before* calling `main()` and, if present, calls
`_run_headless_cron_task(id)` instead of starting the interactive REPL. That
headless path creates a default user profile if needed, calls
`run_cron_task_now(id)` (the same function `/cron run` uses), prints the
result, and exits with a non-zero code on failure - all without ever
starting `main()`'s `input()` loop, which would hang forever with no
terminal attached.

`run_cron_task_now` updates the task's `last_run`/`last_status` in the
manifest and appends a timestamped block to `cron/logs/<id>.log` itself, in
addition to the shell-level `>> ... 2>&1` redirect in the crontab line. The
shell redirect is there specifically to catch catastrophic failures (e.g. an
import error) that happen before Gnosis's own logging code ever runs;
day-to-day, this means the log file can contain both raw process output
(potentially including ANSI color codes from `print()` calls, since nothing
strips them for a redirected-to-file run) and Gnosis's own clean per-run
summary block. Nothing is lost, but expect the raw portion to look a little
noisy if viewed with a plain `cat`.

## Testing without touching the real crontab

None of this was validated against the real system crontab. Testing used a
fake `crontab` executable (a short shell script backed by a plain text file
instead of the real `crontab -l`/`crontab -` mechanism) placed earlier on
`PATH`, against a sandboxed copy of `webagent.py`. That covered: schedule and
feature/prompt validation, add, list (including a foreign entry mixed in),
remove (confirming the foreign entry survives untouched), edit (schedule-only,
action-only, and confirming the crontab command line and task id never
change), headless `--cron-task` execution, and the autonomous planner across
single- and multi-turn requests. That's the safe way to exercise this code
again in the future - never point it at a real crontab you care about until
you're confident in a change.
