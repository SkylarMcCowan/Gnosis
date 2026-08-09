# Gnosis AI Assistant — Agent Instructions

## Purpose
This repository contains a Python-based multi-agent AI assistant. The main entry point is `webagent.py`; the GUI entry point is `webagent_gui.py`.

## Key files
- `webagent.py` — main chat/agent runtime, command parser, agent switching, prompt handling, and memory management
- `webagent_gui.py` — PyQt6 GUI wrapper around the same chat/backend logic
- `run_gui.sh` — convenience launcher for the GUI
- `requirements.txt` — project dependencies, including `ollama`, `trafilatura`, `PyQt6`, `requests`, `yt-dlp`, and voice packages
- `agent_knowledge/` — persona knowledge base for each specialized agent
- `agent_memory/` — persistent conversation memory files per agent
- `knowledge_base/` — saved knowledge artifacts and wiki/web search captures
- `user_details.log` — editable user profile data used by the assistant

## Run commands
- `python webagent.py` — start the main assistant in terminal mode
- `./run_gui.sh` or `./venv/bin/python webagent_gui.py` — start the GUI
- `pip install -r requirements.txt` — install dependencies
- `python -m venv venv` and `source venv/bin/activate` — recommended environment setup

The GUI exposes the same assistant backend with model toggles, web search mode, agent selection, and text streaming.

Optional features depend on additional packages:
- `SpeechRecognition` enables voice input
- `edge-tts` enables text-to-speech
- `duckduckgo-search` enables live DuckDuckGo search
- `yt-dlp` enables YouTube downloads

## Agent system
Specialized agent personas are selected by `/job` and are defined in `webagent.py` under `AVAILABLE_AGENTS`.

Valid agent keys:
- `research` — Research Synthesizer
- `philosophy` — Philosophy Bridge
- `space` — Space Consciousness
- `ethics` — Ethics Advisor
- `creative` — Creative Connector
- `tutor` — Master Tutor
- `fact_checker` — Fact Checker
- `comedian` — Digital Comedian
- `debugger` — Code Debugger
- `counselor` — Digital Counselor

### Agent switching
- `/job <agent_name>` — switch to one specialized persona
- `/job default` — return to default assistant mode
- `/job agent1,agent2` — activate multi-agent collaboration

## Commands and modes
The assistant supports a command-driven interface in `webagent.py`.

General commands:
- `/help` — show command help
- `/exit` — save state and quit
- `/clear` — reset conversation history
- `/profile` — print current user profile
- `/voice` / `/stopvoice` — toggle live speech input
- `/tts` — toggle text-to-speech output
- `/websearch` — toggle web search mode
- `/reason` — toggle reasoning mode
- `/coding` — toggle coding mode
- `/unfiltered` — toggle unfiltered response mode

Feature commands:
- `/archives [topic]` — search the local `knowledge_base`
- `/askwiki [query]` — fetch Wikipedia content and answer the query
- `/historian` — summarize topics from `knowledge_base`
- `/tutor [topic]` — generate a learning path for the topic
- `/showpath [topic]` — display saved learning paths
- `/delpath [topic]` — delete a saved learning path
- `/news` — fetch latest news headlines (if available)
- `/password [-N]` — generate N secure passwords
- `/ytdl <url>` — download a YouTube video to `~/Downloads`
- `/tarot` — perform a Tree of Life Tarot reading

## Behavior guidance for agents
- Preserve the existing persona and knowledge base structure inside `agent_knowledge/`.
- Avoid rewriting the persona definitions in `webagent.py`; those are the canonical prompts.
- When editing, keep command behavior consistent with the current parser in `webagent.py`.
- Prefer minimal changes to `readme.txt`; it is the main user-facing documentation.

## Notes for AI assistance
- The project is Python-based and does not use a standard `README.md`; the user-facing docs are in `readme.txt`.
- `ollama` is used for model interaction, so runtime behavior depends on the local LLM setup.
- `webagent.py` contains the majority of the application logic, so use it as the primary source of truth for behavior and commands.
- The GUI is a thin interface layer; changes to command handling should be made in `webagent.py`.

## Suggested next customization
- Create a dedicated prompt or skill file for the `/job` persona system so developer-facing agents can quickly understand when to use each persona and how to add new ones.
