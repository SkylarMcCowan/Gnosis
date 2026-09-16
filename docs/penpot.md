# Penpot integration

Overview
--------
Gnosis can connect to a self-hosted Penpot instance (https://penpot.app) and
let a model build out real design artifacts - projects, files, boards,
shapes - instead of only describing what a design should look like. There
are two, independent integration paths:

1. **Penpot Studio** (the `🎨 Penpot Studio` pane, `penpot_studio.py`) - a
   chat scoped entirely to Penpot, backed by **Penpot's own official MCP
   server** (help.penpot.app/mcp/) through `core/mcp_client.py`, a generic
   synchronous bridge to the `mcp` Python SDK. This is the "chat with a
   model and it makes the changes" path - see "Penpot Studio" below.
2. **`design.*` tools** (`tools/design/`, implemented in `penpot.py`) - a
   small, hand-rolled set of Tool-registry capabilities (list/create
   project/file, add a board/shape) talking directly to Penpot's backend
   RPC API (`<PENPOT_URL>/api/rpc/command/<name>`). The read-only ones
   (`list_projects`/`list_files`/`get_file`) are available to the model
   during ordinary chat (see webagent.py's `_available_tool_actions()`);
   the mutating ones exist in the registry but aren't wired into any
   chat-triggered path yet (see "Design decision" in that module's
   history) - Penpot Studio is the actual way to get changes made today.

Penpot Studio
-------------
1. In your Penpot instance: **Your account > Integrations > MCP Server**,
   generate a token if you don't have one - it gives you a ready-to-use URL
   like `http://localhost:9001/mcp/stream?userToken=<token>`.
2. Open the `🎨 Penpot Studio` pane, paste that whole URL into the field at
   the top, and hit **Connect**. It's saved locally (`penpot_studio/
   config.json` under Gnosis's own data dir) so you only paste it once.
3. Chat normally - "add a header board with a title" - and the model calls
   Penpot's own MCP tools (`execute_code`, `high_level_overview`,
   `penpot_api_info`, `export_shape`, `import_image` as of this writing;
   discovered live via `list_tools()`, not hardcoded, since Penpot's own
   set can grow) to actually make the change, showing each tool call it
   made above its reply.

This talks to Penpot's **official, first-party** MCP server, not the
third-party `design.*` RPC client below - `execute_code` means the model
writes and runs real code against the open document rather than Gnosis
guessing at Penpot's internal file format itself.

`design.*` tools
----------------
These talk directly to Penpot's own backend RPC API
(`<PENPOT_URL>/api/rpc/command/<name>`), the same API Penpot's own web app
uses - not the browser-only Plugins API, which needs a live Penpot browser
session and can't be driven headlessly from here.

Configuration
-------------
Set both of these environment variables:

```bash
export PENPOT_URL="http://localhost:9001"        # your self-hosted instance's base URL
export PENPOT_ACCESS_TOKEN="<your access token>"  # Penpot > Your account > Access tokens > Generate new token
```

Self-hosted instances must also enable access tokens on the *server* side -
add `enable-access-tokens` to the instance's own `PENPOT_FLAGS` (see
https://help.penpot.app/technical-guide/configuration/), otherwise token
generation in the UI won't be available.

There is no fallback host or token - if either variable is unset, every
`design.*` tool raises a `PenpotError` explaining what's missing, rather
than silently doing nothing.

Quick test
----------
Verify the token and instance are reachable:

```bash
curl -s -H "Authorization: Token ${PENPOT_ACCESS_TOKEN}" \
  "${PENPOT_URL}/api/rpc/command/get-profile"
```

Usage
-----
Gnosis is single-user, so there's no team parameter to pass - every tool
resolves the connected account's default team automatically.

1. `design.list_projects` / `design.create_project` - see or add projects.
2. `design.create_file` - create an empty, single-page file in a project.
3. `design.get_file` - list a file's pages (id, name, shape count); use the
   returned `page_id` for the calls below.
4. `design.add_board` - add a board (artboard/frame) to a page.
5. `design.add_shape` - add a `rect`/`circle`/`text` shape to a page, or
   inside a specific board via its `board_id`.

Notes
-----
- `design.add_board`/`design.add_shape` mutate a file through Penpot's
  `update-file` RPC command, which takes an event-sourced `changes` array.
  That format isn't officially documented beyond Penpot's own source; the
  `add-obj` change (and the `selrect`/`points`/`transform` geometry every
  object needs) mirrors the actively-maintained `zcube/penpot-mcp-server`
  project's verified implementation.
- Only `rect`/`circle`/`text` shapes are supported for now. Extending
  `add_shape()` in `penpot.py` with more shape types or style properties
  (gradients, shadows, strokes) follows the same `add-obj` pattern.
