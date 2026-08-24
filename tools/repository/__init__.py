"""repo.* tools: introspecting the codebase itself (file counts, TODOs,
large files, test presence). Not in the roadmap's original tools/ sketch
(web/, filesystem/, shell/, scheduler/, knowledge/, communication/) - added
because Phase 2's own checklist lists "Repository/code-analysis becomes a
tool" and "Advanced audit tool" as goals, and audit_repository() is pure
Python file-walking, not a shell/subprocess concern, so it didn't fit
tools/shell/ the way git.status/git.diff/test.run do.
"""
