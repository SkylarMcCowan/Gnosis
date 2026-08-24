"""core.*: Phase 1's orchestration layer that turned webagent.py from a
monolith into a thin registrant - config (project_root), context (the
shared Context object every module reads/writes instead of a captured
global), command_router (dispatch), orchestrator (the main loop), models
(the Ollama chat() funnel), events (the pub/sub bus, wired for real in
Phase 12), and activity_log (Phase 12's real subscriber for it).
"""
