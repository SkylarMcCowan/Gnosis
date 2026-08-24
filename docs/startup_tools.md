# Startup Tool Guide

This document explains the main tools and capabilities the assistant can use in this repository.

## Available tools

- **Web Search**
  - Search mode is on by default; the assistant decides per message whether a real-time web search is actually needed.
  - Search results are attached to the prompt and should be treated as authoritative context for answering questions.

- **Local Repository Parsing**
  - The assistant can inspect local files from the repository when file content is explicitly included in the prompt.
  - Use local file content when reviewing repository structure, code, or documentation.

- **TODO Roadmap Guidance**
  - The repository uses `TODO.md` as a self-improvement roadmap.
  - This file should be read and used to identify priorities and planned improvements during `/selfimprove` and related workflows.

- **Knowledge Base**
  - The assistant has access to saved local knowledge base artifacts under `knowledge_base/`.
  - These can be used to recall previous analysis results, summaries, and helpful context.

- **Wikipedia Integration**
  - The `/askwiki` command can fetch Wikipedia content and use it as context for answers.

- **Self-Improve Workflow**
  - The `/selfimprove` command (and the `feature: selfimprove` cron action) audits the repo, picks one small fix, writes it with a test, runs the test suite, and either leaves it staged for review or reverts it on failure — see `docs/selfimprove.md`.
  - It should always consult the repository audit and may consult `TODO.md` for context when generating improvements.

## Guidance for the assistant

- Prefer local context over generic assumptions when repository data is available.
- Use `TODO.md` as a prioritized roadmap for self-improvement tasks.
- Be explicit about which tools were used in your reasoning when responding to a prompt.
- If local file content is not available, still answer based on the repository audit and user instructions.
