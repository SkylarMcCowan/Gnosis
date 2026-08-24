"""reviewers.*: Phase 11's Multi-Agent Engineering Team, scoped down to
what has real output to review right now - self-improve's applied/dry-run
diffs and Phase 9's generated skills. Not new chat personas (the existing
`AVAILABLE_AGENTS` roster is conversational, unrelated to this); each
reviewer here is a role-flavored model call that looks at a finished
artifact and reports what it sees.

Informational only, always - same stance every review/critic feature in
this project has had (Phase 6's fact-checker, critic, evaluator). No
reviewer's finding ever changes whether a fix gets applied or a proposal
gets written; `release_manager.py`'s recommendation is advisory text for
a human, not a gate. A future phase could change that, but that's a real,
separate decision, not something to slip in quietly here.

Each reviewer prepends exactly one severity tag - [OK], [Minor], or
[Concern] - to its finding, the same convention Phase 6's fact-checker
uses ([Wrong entity], [Unverified title]) for the same reason: a tag is
something `release_manager.py` can check for deterministically, without
a second model call judging the first one's judgment.

Reviewers take an injected `coding_chat_fn(system_prompt, user_prompt) ->
str|None` (matching `_selfimprove_coding_chat`'s shape) - this package
never imports webagent.py.
"""
