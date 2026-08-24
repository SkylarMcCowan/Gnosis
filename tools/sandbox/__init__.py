"""sandbox.* tools: open/close a sandboxed Workspace session by name, so
fs.read/fs.write/shell.sandboxed_run can operate on the *same* isolated
copy across several separate tool calls instead of each getting its own
throwaway workspace. See sandbox/sessions.py for the session registry
these wrap.
"""
