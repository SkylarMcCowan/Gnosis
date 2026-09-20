# Tools

Generated from the real tool registry - do not hand-edit; run `python3 scripts/generate_docs.py` instead.


## `conversation.inspect`

Inspect the active conversation topic, recent user turns, follow-up status, and requested output constraints without exposing the full transcript.

- Permission: `SAFE`

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

## `design.add_board`

Add a board (artboard/frame) to a page in a Penpot file - a container to lay other shapes out on.

- Permission: `RESTRICTED`
- Parameters:
  - `file_id`: string
  - `name`: string
  - `x`: number, optional
  - `y`: number, optional
  - `width`: number, optional
  - `height`: number, optional
  - `page_id`: string, optional (defaults to the file's first page)
  - `fill_color`: string, optional (hex, e.g. '#FFFFFF')

## `design.add_shape`

Add a rectangle, circle, or text shape to a Penpot file's page (or inside a specific board).

- Permission: `RESTRICTED`
- Parameters:
  - `file_id`: string
  - `shape_type`: string ('rect' | 'circle' | 'text')
  - `page_id`: string, optional (defaults to the file's first page)
  - `board_id`: string, optional (nest inside this board's shape id rather than the page root)
  - `x`: number, optional
  - `y`: number, optional
  - `width`: number, optional
  - `height`: number, optional
  - `fill_color`: string, optional (hex, e.g. '#FF0000')
  - `text`: string, optional (only used when shape_type is 'text')
  - `font_size`: number, optional
  - `name`: string, optional

## `design.create_file`

Create a new (empty, single-page) Penpot file inside a project.

- Permission: `RESTRICTED`
- Parameters:
  - `project_id`: string
  - `name`: string

## `design.create_project`

Create a new Penpot project in the connected instance's default team.

- Permission: `RESTRICTED`
- Parameters:
  - `name`: string

## `design.get_file`

Get a Penpot file's pages (id, name, shape count) - use this to find a page_id (or a board's shape id) before calling design.add_board/add_shape.

- Permission: `SAFE`
- Parameters:
  - `file_id`: string

## `design.list_files`

List the files inside a Penpot project.

- Permission: `SAFE`
- Parameters:
  - `project_id`: string

## `design.list_projects`

List the Penpot projects in the connected instance's default team.

- Permission: `SAFE`

## `evidence.verify`

Check a drafted answer against current-turn evidence and report supported, unsupported, conflicting, or wrong-entity claims.

- Permission: `SAFE`
- Parameters:
  - `answer_text`: string
  - `user_prompt`: string
  - `evidence`: list[object]

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

## `knowledge.forget`

Archive and remove a selected saved knowledge source after explicit confirmation.

- Permission: `REQUIRES_APPROVAL`
- Parameters:
  - `path`: string
  - `confirm`: boolean

## `knowledge.related`

Find related saved knowledge with source provenance and retrieval signals.

- Permission: `SAFE`
- Parameters:
  - `topic`: string
  - `limit`: integer, optional

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

## `live.soccer_result`

Get a soccer team's most recent match result (opponent, score, competition, date) and next scheduled fixture if any, covering that team's domestic league plus UEFA Champions League/Europa League. Use for any question about a soccer team's last/next match, score, or fixture.

- Permission: `SAFE`
- Parameters:
  - `team`: string - a soccer team name (e.g. "Manchester United")

## `live.stock_quote`

Get a live stock/share price for a public company: current price, previous close, day's high/low, exchange, and currency, as of right now. Use for any question about a current/today's stock or share price.

- Permission: `SAFE`
- Parameters:
  - `company_or_ticker`: string - a company name (e.g. "Microsoft") or ticker symbol (e.g. "MSFT")

## `live.weather`

Get the current live weather for a place: temperature, feels-like temperature, conditions (clear/rain/snow/etc.), humidity, and wind speed, observed right now - not a multi-hour forecast. Use for any question about current/today's weather.

- Permission: `SAFE`
- Parameters:
  - `location`: string - a city, region, or place name

## `model.status`

Report selected model, availability, context budget, active modes, and recent metrics.

- Permission: `SAFE`

## `repo.audit`

Summarize the repository: file/line counts, TODO/FIXME findings, large files, tests folder presence.

- Permission: `SAFE`

## `repo.audit_advanced`

Assess README quality, test-suite presence, CI config, and docs health for the repository.

- Permission: `SAFE`

## `repo.inspect`

Inspect repository structure, audit findings, documentation, and test readiness.

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

## `subscriptions.list`

List the user's current subscriptions - teams, topics, websites, and weather locations that Gnosis prioritizes in answers over guessing/searching.

- Permission: `SAFE`

## `task.plan`

Turn a goal into a bounded checklist with dependencies and a next action.

- Permission: `SAFE`
- Parameters:
  - `goal`: string
  - `context`: string, optional

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
