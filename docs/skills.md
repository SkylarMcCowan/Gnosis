# Skills

Generated from the real skill registry - do not hand-edit; run `python3 scripts/generate_docs.py` instead.


## `conversation.recover`

Recover the active topic and produce a bounded next-step plan when needed.

- Permission: `SAFE`
- Composes: `conversation.inspect`, `task.plan`
- Parameters:
  - `goal`: string, optional

## `knowledge.maintain`

Find related saved knowledge and optionally archive-confirmed removal of one source.

- Permission: `REQUIRES_APPROVAL`
- Composes: `knowledge.related`, `knowledge.forget`
- Parameters:
  - `topic`: string
  - `forget_path`: string, optional
  - `confirm`: boolean, optional

## `repo.change_review`

Inspect repository health and optionally run the restricted project test tool.

- Permission: `RESTRICTED`
- Composes: `repo.inspect`, `test.run`
- Parameters:
  - `run_tests`: boolean, optional

## `research.topic`

Research a topic: reuse existing knowledge if present, otherwise search the web and record findings.

- Permission: `RESTRICTED`
- Composes: `web.search`, `web.fetch`, `knowledge.search`, `knowledge.write`
- Parameters:
  - `topic`: string

## `research.verify`

Verify a research draft against current-turn evidence and expose source-backed findings.

- Permission: `SAFE`
- Composes: `evidence.verify`
- Parameters:
  - `answer_text`: string
  - `user_prompt`: string
  - `evidence`: list[object]
