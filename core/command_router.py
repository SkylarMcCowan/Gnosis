"""Generic command dispatch for the REPL loop.

Deliberately has zero knowledge of what any actual command does - webagent.py
registers its own handler functions against an instance of this. That's what
keeps this reusable and unit-testable in isolation, and it's what avoids a
circular import: this module never imports webagent.py, webagent.py imports
this one and hands it callables bound to its own functions/context.

Two ways to register a handler:
  - register(patterns, handler): exact, case-insensitive match against the
    whole prompt. `patterns` is a string or an iterable of strings, so one
    handler can own several literal spellings (e.g. "/historian" and
    "/historian preview").
  - register_prefix(prefix, handler): case-insensitive prefix match, for a
    command that takes a free-form argument (e.g. "/job ethics"). The
    handler receives the full original prompt and is responsible for
    parsing its own arguments out of it, matching how these commands always
    worked before extraction.

Exact matches are checked first (an O(1) dict lookup), so a command that
also happens to be a prefix of another registered prefix is never
ambiguous - "/cron" (exact) and "/cron add" (prefix) coexist safely because
"/cron" is never itself registered as a prefix.
"""


class CommandRouter:
    def __init__(self):
        self._exact = {}
        self._prefixes = []  # [(prefix, handler), ...], checked in registration order

    def register(self, patterns, handler):
        if isinstance(patterns, str):
            patterns = (patterns,)
        for pattern in patterns:
            self._exact[pattern.lower()] = handler

    def register_prefix(self, prefix, handler):
        self._prefixes.append((prefix.lower(), handler))

    def dispatch(self, prompt):
        """Run the handler for `prompt` if one matches. Returns True if
        something handled it, False if nothing matched (the caller is then
        free to fall back to its own default behavior)."""
        lowered = prompt.lower()
        handler = self._exact.get(lowered)
        if handler is not None:
            handler(prompt)
            return True
        for prefix, handler in self._prefixes:
            if lowered.startswith(prefix):
                handler(prompt)
                return True
        return False
