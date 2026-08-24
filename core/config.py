"""Where Gnosis keeps its on-disk data: one place owning the project root,
so every data directory (agent_memory, knowledge_base, conversations,
tutor_paths, cron) resolves through a single, overridable function instead
of each call site computing `os.path.dirname(__file__)` on its own.

Deliberately excludes anything about locating the *running script* itself
(the venv relaunch in webagent.py, or the real path cron's shell command
must invoke) - those must always resolve to this real checkout regardless of
any override below, so they stay computed locally from webagent.py's own
`__file__`.
"""
import os

_default_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_root_override = None


def project_root():
    return _root_override or _default_root


def path(*parts):
    return os.path.join(project_root(), *parts)
