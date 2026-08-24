# Feature inventory (Phase 0 baseline)

Snapshot taken 2026-08-22, before any refactor work. This is the "baseline list of
currently functional commands/features" required by TODO.md Phase 0 — re-run this
kind of audit at the end of each milestone to confirm nothing silently regressed.

## Environment note (fix before relying on `/cron`-scheduled tasks or CI)

`venv/bin/python` is a dangling symlink chain: `venv/bin/python -> python3.12 ->
/opt/homebrew/opt/python@3.12/bin/python3.12`, and that final target no longer exists
on this machine (Homebrew has moved on from 3.12). `webagent.py`'s
`_relaunch_with_project_venv()` checks `os.path.isfile(venv_python)`, which is `False`
for a dangling symlink, so it silently falls back to whatever interpreter launched it —
no crash, but the project's own venv is effectively dead. The system `python3`
(3.14.7, via `/Library/Frameworks/Python.framework`) already has every dependency in
`requirements.txt` installed and is what `pytest`/`python3` resolve to on PATH. Cron
tasks run via `_cron_shell_command()` also fall back to `sys.executable` the same way,
so scheduled tasks aren't broken today — but the venv should be rebuilt (`python3.12`
via a fresh Homebrew formula or `python3.14`) rather than left dangling.

## Slash commands (dispatched in `main()`'s if/elif chain, webagent.py:4665-5161)

`/reason` `/deepthink` `/reindexevidence` `/password` `/job` `/unfiltered` `/coding`
`/tts` `/websearch` `/historian` (`preview`, `--dry-run`) `/cron` (`help`, `list`,
`alarm`, `add`, `edit`, `remove`, `run`) `/askwiki` `/tutor` `/showpath` `/delpath`
`/news` `/ytdl` `/profile` (`persona`) `/persona` `/selfimprove` `/help` `/exit`
`/clear` `/new` `/conversations` `/loadconv` `/voice` `/stopvoice` `/archives`
`/tarot` `/createpath`. Unknown `/x` falls through to a funny-error catch-all
(webagent.py:5144). Source of truth is the in-app `/help` text (webagent.py:5026),
not readme.txt (see discrepancies below).

## Model / LLM integration

`MODELS` dict (webagent.py:235): `main`=yi:6b, `search`=qwen3.5:2b,
`unfiltered`=yi:6b, `coding`=qwen2.5-coder:7b — model selection via
`_selected_model()` (744). Call sites: `stream_response`(727), `chat_response`(811),
`_research_action`(1285), `_deep_think_research_plan`(1330),
`iterative_web_search`(1564), `fact_check_answer`(2218),
`_selfimprove_coding_chat`(2792), `ask_wiki`(3164), `_historian_classify_topics`(3252),
`_cron_agent_plan`(4298), `tutor`(4460), `pull_model`(872, pulls all four).

**Dead code found:** `shared.py` defines its own `MODELS` dict with different model
names (llama3.2, deepseek-r1:14b, llama2-uncensored, nous-hermes2:10.7b) plus a
duplicate `speak_text` — confirmed unused, no file imports `shared`. Also
`utils.py` contains only `reverse_string`, unused outside `tests/test_utils.py`.
Both are safe deletion candidates once someone signs off.

## Major functional areas (function name → line, in webagent.py unless noted)

- **Web search/fetch**: `search_searx`(881), `search_web`(923), `fetch_page_content`(474),
  `search_fallback`(1445), `iterative_web_search`(1538),
  `model_directed_web_research`(1353), `check_search_services`(1420).
- **Web evidence/fact-check**: `score_web_evidence`(1052), `apply_corroboration`(1120),
  `save_web_evidence`(1205), `fact_check_answer`(2191).
- **TTS/voice**: `speak_text`(668), `_speak_with_pyttsx3`(590),
  `_speak_with_macos_say`(615), `stop_tts`(519), `stop_voice`(553),
  `recognize_speech`(840).
- **Agent personas**: `AVAILABLE_AGENTS`(2229), `switch_agent`(2445),
  `setup_multi_agent_collaboration`(2483), `job_command`(2536),
  `suggest_agent_for_context`(4550). Persona text lives in `sys_msgs.py`;
  agent-to-agent helpers (`call_agent_json`, `ask_user_question`) live in
  `agent_dialogue.py`.
- **Agent memory**: `load_agent_memory`(2350), `save_agent_memory`(2372),
  `get_relevant_agent_memory`(2422).
- **User profile**: `load_user_profile`(1667), `save_user_profile`(1701),
  `update_user_notes_softly`(1932).
- **Knowledge base**: `record_to_knowledge_base`(2565), `search_knowledge_base`(2608).
- **Tutor**: `tutor`(4454), `create_learning_path`(4426), `show_learning_path`(4431),
  `delete_learning_path`(4447).
- **Cron/scheduler**: `cron_add`(4026), `cron_edit`(4067), `cron_remove`(4130),
  `run_cron_task_now`(4175), `_cron_agent_execute`(4318), `set_alarm`(3985),
  `parse_alarm_time`(3904), `run_scheduler_agent_step`(4405). Mutates the real
  system crontab via `crontab -l`/`crontab -` — anything testing this must fake
  `_read_crontab`/`_write_crontab` (see `tests/conftest.py::no_real_crontab`).
- **Historian**: `historian`(3580), `historian_clean_knowledge_base`(3299),
  `historian_merge_conversations`(3444), `historian_clean_agent_memory`(3528).
- **Self-improve**: `run_self_improve_cycle`(3015), `perform_self_improve`(3120),
  `audit_repository`(2627).
- **News**: entirely in `news.py` (`news_command`); webagent.py only imports and
  dispatches it.
- **Code review**: entirely in `code_review.py` — only `webagent_gui.py` calls it,
  the CLI never does.
- **Tarot**: entirely in `tarot.py`, lazily imported at webagent.py:5129.

## webagent_gui.py

Does not duplicate logic — imports `webagent`, `agent_dialogue`, `code_review` and
calls webagent's real functions/state (`chat_response`, `job_command`,
`AVAILABLE_AGENTS`, `tts_mode`, `unfiltered_mode`, ...). It's a PyQt6 wrapper plus its
own diff/folder code-review dialogs, using `code_review.py` directly — a path the CLI
never exercises.

## Docs vs. code discrepancies (fix in Phase 14 — Documentation Automation)

- `readme.txt:122` documents `/collab research ethics creative` — **does not exist**.
  The real syntax is `/job agent1,agent2,agent3` (comma-separated, webagent.py:2536).
- `readme.txt`'s command table is missing most commands: `/job`, `/websearch`,
  `/cron*`, `/unfiltered`, `/coding`, `/selfimprove`, `/askwiki`, `/tutor`,
  `/showpath`, `/delpath`, `/ytdl`, `/archives`, `/persona`, `/profile`,
  `/historian`, `/reindexevidence`, `/voice`, `/tts`, `/new`, `/conversations`,
  `/loadconv`, `/createpath`.
- `AGENTS.md`'s command/agent list matches `AVAILABLE_AGENTS` and is mostly accurate,
  but also omits `/reindexevidence`, `/new`, `/conversations`, `/loadconv`, `/createpath`.

## Test coverage as of this snapshot

`tests/` — `test_utils.py` (pre-existing) plus new Phase 0 suites: `test_smoke.py`
(import/launch, live Ollama connectivity, mocked basic conversation),
`test_agents.py` (persona switching, multi-agent `/job`), `test_memory_and_knowledge.py`
(agent memory round-trip + 20-entry cap, knowledge base round-trip/search),
`test_cron.py` (add/edit/remove/run-now, alarm time parsing — all against a faked
crontab, never the real one), `test_tutor.py` (learning path create/show/delete),
`test_tts.py` (stop_tts/stop_voice, system audio calls mocked out). 30 tests, all
passing. Not yet covered: `/websearch` and `/deepthink` research pipeline,
`/historian`, `/selfimprove`, `/ytdl`, `/tarot`, `/askwiki`, conversation
save/load, real speech recognition — tracked as open Phase 0 items in TODO.md.
