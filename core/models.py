"""Model/LLM integration layer: what models exist, and the one place every
call to the model backend passes through.

Deliberately narrow scope for this first Phase 1 extraction: per-turn model
*selection* (unfiltered/reasoning/coding mode) stays in webagent.py, since
that's session state tied to the REPL, not model configuration. What moves
here is everything about Ollama itself - the import (with its proxy-var
workaround and fallback-to-None), the model registry, and a single chat()
funnel that every call site now goes through instead of calling
`ollama.chat(...)` directly.
"""
import os

from colorama import Fore, Style

from core.exceptions import ModelUnavailableError

# Work around broken proxy environment variables that can prevent ollama/httpx import.
for _proxy_var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_proxy_var, None)

try:
    import ollama
    OLLAMA_IMPORT_ERROR = None
except Exception as e:
    ollama = None
    OLLAMA_IMPORT_ERROR = str(e)
    print(f"{os.linesep}Warning: unable to import ollama: {e}{os.linesep}")

MODELS = {
    'main': 'qwen3.5:4b',         # normal responses - 262K native ctx, already pulled
    'search': 'qwen3.5:2b',       # reasoning responses (fallback to main)
    'unfiltered': 'dolphin-mistral:7b',  # unfiltered/unmoderated responses - a real uncensored
                                  # fine-tune (Dolphin-Mistral 7B, ~4.1GB), not just a smaller
                                  # base model; fits comfortably on a 16GB M1 alongside the rest
                                  # of this app
    'coding': 'qwen2.5-coder:7b',  # coding responses (fallback to main)
    'fast': 'yi:6b',              # internal JSON-decision plumbing (tool routing, research
                                  # planning, fact-check). This is what these calls already ran
                                  # on in the common case before 'main' became a thinking model
                                  # (_selected_model() resolved to 'main' whenever no other mode
                                  # was active), so it's a zero-regression choice, confirmed
                                  # non-thinking. qwen2.5-coder:7b was tried first and
                                  # rejected: live-tested side by side on the exact tool-routing
                                  # prompt, it answered "{"clarify": [...]}" (a spurious
                                  # clarifying-question popup) for an unambiguous question
                                  # ("what is the capital of France?") that yi:6b answered
                                  # correctly with no clarify - see _select_tool_action's
                                  # docstring for the same small-model-escape-hatch failure mode.
}

# Explicit context window per model, merged into every chat() call below. Ollama silently
# defaults to 4096 tokens if nothing sets num_ctx (confirmed via the running llama-server
# process's own -c 4096 flag) - previously nothing here ever set it, so trim_conversation()'s
# own (larger) budget in webagent.py was routinely already past what the model could actually
# see, regardless of model. yi:6b's 4096 is its native ceiling; the others get headroom well
# under their native max, sized for a 16GB machine also running the rest of this app.
MODEL_CONTEXT = {
    'yi:6b': 4096,
    'qwen3.5:4b': 8192,
    'qwen3.5:2b': 8192,
    'qwen2.5-coder:7b': 8192,
    'dolphin-mistral:7b': 8192,
}
DEFAULT_CONTEXT = 4096


def is_available():
    """Whether the ollama client imported successfully."""
    return ollama is not None


def list_installed():
    """Model tags actually pulled in the local Ollama install, for a GUI model
    picker - distinct from MODELS (the role -> tag registry), since a user may
    have other local models pulled that aren't wired to any role. Returns []
    if Ollama isn't available rather than raising, since this is only ever
    used to populate an optional selector."""
    if ollama is None:
        return []
    try:
        response = ollama.list()
    except Exception:
        return []
    models = response.get('models', []) if isinstance(response, dict) else getattr(response, 'models', [])
    names = []
    for m in models:
        name = m.get('model') if isinstance(m, dict) else getattr(m, 'model', None)
        if name:
            names.append(name)
    return names


def chat(model, messages, stream=False, **kwargs):
    """The one place every chat call (streaming or not) passes through.

    Raises ModelUnavailableError (a RuntimeError) consistently when Ollama
    isn't available, rather than each caller improvising its own guard - a
    few call sites in webagent.py had no guard at all before this existed,
    and would have hit a raw AttributeError on None.chat instead of a clear
    error.
    """
    if ollama is None:
        raise ModelUnavailableError("Ollama client is unavailable. Please install and configure ollama.")
    options = dict(kwargs.pop('options', None) or {})
    options.setdefault('num_ctx', MODEL_CONTEXT.get(model, DEFAULT_CONTEXT))
    kwargs['options'] = options
    return ollama.chat(model=model, messages=messages, stream=stream, **kwargs)


def pull_all():
    """Pull every model in MODELS. Returns False if Ollama isn't available."""
    if ollama is None:
        print(f"{Fore.RED}Ollama client is unavailable. Skipping model pull.{Style.RESET_ALL}")
        return False
    for model_key, model_val in MODELS.items():
        print(f"{Fore.CYAN}Pulling model '{model_val}' for key '{model_key}'...{Style.RESET_ALL}")
        ollama.pull(model=model_val)
        print(f"{Fore.GREEN}Model '{model_val}' pulled successfully.{Style.RESET_ALL}")
    return True
