# Tools

Generated from the real tool registry - do not hand-edit; run `python3 scripts/generate_docs.py` instead.


## `cron.add`

Create a new scheduled task (prompt, feature, or alarm) in the real system crontab.

- Permission: `REQUIRES_APPROVAL`
- Parameters:
  - `schedule_fields`: list[str] (5 cron fields: minute hour day month weekday)
  - `action_type`: string ('prompt' | 'feature' | 'alarm')
  - `action_payload`: string
  - `description`: string, optional
  - `one_shot`: bool, optional

## `cron.edit`

Update an existing Gnosis-managed crontab entry's schedule/action in place.

- Permission: `REQUIRES_APPROVAL`
- Parameters:
  - `task_id`: string
  - `schedule_fields`: list[str], optional
  - `action_type`: string, optional
  - `action_payload`: string, optional
  - `description`: string, optional
  - `one_shot`: bool, optional

## `cron.list`

List every addressable crontab entry, numbered.

- Permission: `SAFE`

## `cron.remove`

Remove the crontab entry at a given 1-based index (as numbered by cron.list).

- Permission: `REQUIRES_APPROVAL`
- Parameters:
  - `index`: int

## `cron.run`

Run a Gnosis-managed cron task's action right now, without waiting for its schedule.

- Permission: `RESTRICTED`
- Parameters:
  - `task_id`: string

## `fs.read`

Read a file's content from an open sandbox workspace.

- Permission: `SAFE`
- Parameters:
  - `workspace_id`: string
  - `path`: string, relative to the workspace root

## `fs.write`

Write content to a file inside an open sandbox workspace.

- Permission: `RESTRICTED`
- Parameters:
  - `workspace_id`: string
  - `path`: string, relative to the workspace root
  - `content`: string

## `git.diff`

Show the working tree's uncommitted diff (git diff).

- Permission: `SAFE`

## `git.status`

Report the working tree's dirty state (git status --porcelain).

- Permission: `SAFE`

## `knowledge.search`

Search the knowledge base for a topic and return matching (filename, content) pairs.

- Permission: `SAFE`
- Parameters:
  - `topic`: string

## `knowledge.write`

Save content to a named file in the knowledge base.

- Permission: `RESTRICTED`
- Parameters:
  - `filename`: string
  - `content`: string

## `repo.audit`

Summarize the repository: file/line counts, TODO/FIXME findings, large files, tests folder presence.

- Permission: `SAFE`

## `repo.audit_advanced`

Assess README quality, test-suite presence, CI config, and docs health for the repository.

- Permission: `SAFE`

## `sandbox.close`

Close a sandbox workspace, optionally merging specific files back into the real repo.

- Permission: `REQUIRES_APPROVAL`
- Parameters:
  - `workspace_id`: string
  - `merge_back_paths`: list[str], optional - files to copy into the real repo before destroying the workspace

## `sandbox.open`

Open an isolated sandbox workspace and return its session id.

- Permission: `RESTRICTED`

## `shell.sandboxed_run`

Run one allowlisted command (e.g. 'run_tests') inside an isolated workspace.

- Permission: `RESTRICTED`
- Parameters:
  - `command_name`: string (one of sandbox.commands.ALLOWED_COMMANDS's keys)
  - `workspace_id`: string, optional (an already-open session from sandbox.open)

## `test.run`

Run the project's test suite. Returns (passed: bool, output: str).

- Permission: `RESTRICTED`

## `web.fetch`

Fetch a URL and return its extracted page content.

- Permission: `SAFE`
- Parameters:
  - `url`: string

## `web.search`

Search the web for a query and return ranked results.

- Permission: `SAFE`
- Parameters:
  - `query`: string
