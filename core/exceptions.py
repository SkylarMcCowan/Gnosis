"""Small typed-exception hierarchy for errors Gnosis's own code raises
deliberately, as opposed to letting a third-party library's exception
(requests, subprocess, json) propagate untyped. Currently just one type,
used by core/models.py; more get added here as later phases need to
distinguish failure modes (e.g. Phase 15's governance work catching a
permission violation specifically, rather than any old exception).
"""


class GnosisError(Exception):
    """Base class for every error type Gnosis itself defines."""


class ModelUnavailableError(GnosisError, RuntimeError):
    """The configured model backend (e.g. Ollama) isn't available to serve
    a request. Also a RuntimeError, since that's what callers already
    catch/expect from before this hierarchy existed."""


class ChatCancelled(GnosisError):
    """A user stopped a turn; propagate through progress callbacks as control flow."""
