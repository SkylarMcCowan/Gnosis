"""fs.* tools: reading/writing files bounded to an open sandbox.open
session's own workspace directory (sandbox/files.py), never the live
project tree directly - Phase 2's "Filesystem access becomes a tool" item,
unblocked by Phase 10's sandbox exactly the way that entry said it would
be. Path-traversal protected: a relative path that would resolve outside
the session's workspace root is refused.
"""
