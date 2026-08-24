"""docgen.*: Phase 14, scoped to what can be generated *from real,
already-existing structure* rather than written by hand or invented by a
model - a tool/skill reference from the real registries, an architecture
map from each package's own docstring, a command reference from `/help`'s
own real output. Each generator takes its source data injected (a list of
Tool/Skill instances, a dict of docstrings, a help-text string) rather than
importing webagent.py or the registries itself, same DI discipline as
tools/skills/builder - `scripts/generate_docs.py` is what actually wires
real data in.

Deliberately not built, for stated reasons rather than left silently
missing (see TODO.md Phase 14 for the full list): API/function-level
documentation generation (a much larger, separate undertaking - would need
real docstring-coverage analysis across the whole codebase), changelog/
release-note generation (no automatic source better than TODO.md's own
prose already gives), and whole-codebase doc-staleness detection beyond
the freshness check here (`reviewers/documentation.py`, Phase 11, already
reviews individual diffs for clarity - a different, narrower scope than
"is any doc anywhere stale").
"""
