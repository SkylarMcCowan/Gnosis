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
    'main': 'yi:6b',              # normal responses
    'search': 'qwen3.5:2b',       # reasoning responses (fallback to main)
    'unfiltered': 'yi:6b',        # unfiltered responses (fallback to main)
    'coding': 'qwen2.5-coder:7b',  # coding responses (fallback to main)
}


def is_available():
    """Whether the ollama client imported successfully."""
    return ollama is not None


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
