"""shell/git/test tools: `git.status`/`git.diff` (git_status.py/git_diff.py,
SAFE - read-only), `test.run` (test_run.py, RESTRICTED - runs the real test
suite), and `shell.sandboxed_run` (sandboxed_run.py, RESTRICTED - runs a
command inside a sandbox workspace). Registered in webagent.py's
`_register_tools()` and used throughout the self-improve pipeline.
"""
