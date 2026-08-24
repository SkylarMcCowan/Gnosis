"""sandbox.*: Phase 10's Autonomous Workspace / Sandbox - an isolated git
worktree (`workspace.py`'s `Workspace`) that risky operations run inside
of, plus a small, fixed command allowlist (`commands.py`) rather than
arbitrary shell execution.

Scoped to what has a real reason to exist right now, not the full roadmap
sketch:
- Built: isolated workspace, filesystem boundary (the workspace's own
  directory), a fixed command allowlist, resource limits (wall-clock
  timeout + POSIX address-space limit), process cleanup, git isolation
  (via `git worktree`, not a full repo copy), and automatic rollback (the
  worktree is destroyed on exit unless explicitly merged back).
- Not built: network permissions. There's no practical way to sandbox
  network egress from a plain subprocess without OS-level firewall rules
  or a network namespace, which is a different, much larger undertaking
  than an application-level workspace boundary - not attempted rather
  than faked.
- Not built: `experiments/`, `generated_tools/`, `generated_skills/`,
  `patches/`, `test_results/`, `artifacts/`, `proposals/` subdirectories
  from the roadmap's own sketch - `runs/` (one directory per `Workspace`)
  is the only one with a real consumer today (self-improve, and the new
  `shell.sandboxed_run` tool this unblocks). The others are Phase 9's
  concern once self-generated tools/skills are themselves real.

Never imports webagent.py - same discipline as tools/skills/memory/learning.
"""
