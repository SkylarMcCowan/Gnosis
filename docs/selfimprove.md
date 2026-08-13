# Self-Improve (Autonomous)

This document describes the repository's `self-improve` scaffolding and how to control it.

Overview
- The `selfimprove.py` module contains a lightweight controller (`SelfImprove`) that can:
  - propose and create new files
  - run unit tests using the standard library `unittest` discovery
  - show a `git diff` of created changes

Autonomous mode
- The `/selfimprove` command in `webagent.py` can invoke the scaffold. There are two modes:
  - Interactive: propose changes and wait for user approval before writing files or committing.
  - Autonomous: create files and run tests automatically. This repository scaffold supports autonomous operation.

Safety and commit policy
- By default `selfimprove.py` will NOT perform `git commit` or push operations. To enable commits, set the
  environment variable `SELFIMPROVE_ALLOW_COMMITS=1` before running the scaffold. Use this only when you trust
  the autonomous workflow.

Example
- Run `python selfimprove.py` to create a demo utility `reverse_string` and its unit test. The script prints a JSON
  report including created files and test output.

How to enable commits (optional)
```bash
export SELFIMPROVE_ALLOW_COMMITS=1
python -m selfimprove
```

How to enable full-file review in `/selfimprove`
```bash
export SELFIMPROVE_INCLUDE_FULL_FILES=1
```
This enables the workflow to include selected local repository files directly in the model prompt for a fuller code review and update, instead of only a summarized audit.

You can also tune limits with:
- `SELFIMPROVE_MAX_PROMPT_BYTES` (default `800000`)
- `SELFIMPROVE_MAX_FILE_BYTES` (default `150000`)
- `SELFIMPROVE_MAX_FILES` (default `30`)

Notes
- The scaffold is intentionally simple so you can extend it: add feature planning, acceptance criteria, LLM-driven
  code generation, or a review loop. If you want fully autonomous commits and PR creation, I can add a controlled
  commit-and-push path that requires an explicit `--commit` flag.
# /selfimprove Command

Use `/selfimprove` to let the assistant audit its current repository, plan new improvements, verify the plan, develop features, and validate each step before moving to the next.

The workflow is:
1. Audit the repository and identify improvement opportunities.
2. Plan new functions/features with deliverables.
3. Verify the plan for correctness and feasibility.
4. Develop the functions/features.
5. Test and validate the changes before continuing.

This command is intended to let the model bootstrap improvements without extra user direction.
