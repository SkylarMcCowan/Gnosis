# Conversation Management

This document describes how conversations are saved, loaded, and trimmed in this project.

Location
- Conversations are stored in the repository root `conversations/` as JSON files (one file per save).

File naming
- When saved automatically the code generates a sanitized timestamp-based filename. You can also provide a name when saving in future enhancements.

Commands (CLI)
- `/new` — start a new conversation; optionally saves the current conversation before resetting.
- `/conversations` — list saved conversation files (newest first).
- `/loadconv <index|filename>` — load a saved conversation by 1-based index (from `/conversations`) or by filename.
- `/saveconv <name>` — (TBD) planned: explicit named save command.

Trimming / Context window
- To avoid unbounded growth of the in-memory context, `trim_conversation(max_messages=80, max_chars=20000)` is called before model calls.
- Trimming preserves the seed/system message (if present) and retains the most recent messages up to the configured limits.

.gitignore
- The repository ignores the `conversations/` directory. If you track saved conversations accidentally, remove them from git with:

```bash
git rm --cached conversations/*.json
git commit -m "Remove tracked conversation files from repo"
```

Notes and UX
- Saved conversation files are simple JSON arrays of message objects. Load restores the array into the in-memory `assistant_convo` buffer.
- The assistant trims context prior to streaming to the LLM and before iterative web searches.
- If you want a named-save UX, I can implement `/saveconv <name>` and a confirmation prompt before overriding the current `assistant_convo`.

Troubleshooting
- If a command like `/new` is reported as unknown, ensure your local `webagent.py` includes the updated command routing and that the process has been restarted.

Contact
- Ask here if you want the explicit `/saveconv` implementation or automatic metadata in saved files (timestamp, message count, summary).
