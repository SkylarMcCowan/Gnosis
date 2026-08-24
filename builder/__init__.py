"""builder.*: Phase 9's Self-Generated Tools pipeline - CAPABILITY GAP →
DESIGN → GENERATE → GENERATE TESTS → SANDBOX → RUN TESTS → PROPOSAL.

Scoped down from the roadmap's own diagram in two honest ways:
- No separate CRITIC or BENCHMARK stage. The *trigger* is Phase 6's
  critic (`learning.critic.critique_recent_failures`) - a real recurring
  failure pattern is the capability gap this pipeline designs against.
  There's no second code-quality critic pass over the generated code
  itself, and no real benchmark metric beyond pass/fail - inventing either
  without a concrete need would be scoring theater, not a real signal.
- "Generated code does NOT immediately become production code" (the
  roadmap's own words) is enforced structurally: `proposals.py` is the
  *only* thing this pipeline ever does with a result, pass or fail. Nothing
  here ever calls `tool_registry.register(...)` or `skill_registry.register(...)`.

Safety stance, stated plainly rather than implied: `sandbox.workspace.Workspace`
isolates git-tracked project files via a worktree and blocks real tool
execution during a generated test run (`validator.py`'s injected conftest.py
makes any real `tool_registry.execute()` call raise, regardless of whether
the generated test remembered to fake it). It does **not** provide OS-level
sandboxing - a generated test is still arbitrary Python running as a real
subprocess, and could still do things like touch files outside the
workspace or make network calls. That gap is exactly why nothing generated
here is ever trusted automatically; a human reads it first.

Never imports webagent.py - the model-chat function is injected (matching
`_selfimprove_coding_chat`'s existing shape), same discipline as every
other package built this way.
"""
