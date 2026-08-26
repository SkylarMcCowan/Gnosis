"""subscriptions.* tools: core.subscriptions.list_subscriptions as
`subscriptions.list`.

Exists to close a real, live-reported gap: before this tool existed, a
plain chat question like "what am I subscribed to?" had no path to
core/subscriptions.py's actual data at all - _matching_subscription only
fires when the prompt names a specific subscription (e.g. "how did
Manchester United do"), not a meta-question about the list itself, so the
message fell through to an ordinary web search with no real grounding
("current subscriptions for you" searched on the open web). Registering
this as a SAFE, read-only capability makes it visible to
_available_tool_actions/_select_tool_action the same way cron.list already
is.
"""
