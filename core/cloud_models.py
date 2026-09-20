"""Cloud chat adapters. Credentials stay in memory or the environment."""
import json
import os

import requests

from core.exceptions import ModelUnavailableError

PROVIDERS = {
    "openai": ("OpenAI", "OPENAI_API_KEY", "OPENAI_MODEL", "https://api.openai.com/v1/chat/completions"),
    "anthropic": ("Claude", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "https://api.anthropic.com/v1/messages"),
}
_connections = {}


def is_cloud(model):
    return isinstance(model, str) and model.partition(":")[0] in PROVIDERS


def settings(provider):
    _, key_env, model_env, _ = PROVIDERS[provider]
    return _connections.get(provider, (os.getenv(key_env, ""), os.getenv(model_env, "")))


def configure(provider, api_key, model):
    if provider not in PROVIDERS:
        raise ValueError("Unknown cloud provider")
    api_key, model = api_key.strip(), model.strip()
    if not api_key or not model:
        raise ValueError("Enter an API key and model ID.")
    _connections[provider] = (api_key, model)
    return f"{provider}:{model}"


def configured_models():
    return [f"{p}:{settings(p)[1]}" for p in PROVIDERS if all(settings(p))]


def _message(text):
    return {"message": {"role": "assistant", "content": text}}


def chat(model, messages, stream=False):
    provider, _, model_id = model.partition(":")
    label, key_env, _, url = PROVIDERS[provider]
    key, _ = settings(provider)
    if not key or not model_id:
        raise ModelUnavailableError(f"Configure {label} in Cloud models or set {key_env}.")
    # Exclude Gnosis metadata such as source annotations from API payloads.
    clean = [{"role": m["role"], "content": m.get("content", "")} for m in messages]
    headers = {"Content-Type": "application/json"}
    body = {"model": model_id, "messages": clean, "stream": stream}
    if provider == "openai":
        headers["Authorization"] = f"Bearer {key}"
    else:
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        body["system"] = "\n\n".join(m["content"] for m in clean if m["role"] == "system")
        body["messages"] = [m for m in clean if m["role"] != "system"]
        body["max_tokens"] = 4096
    try:
        response = requests.post(url, headers=headers, json=body, stream=stream,
                                 timeout=(10, 120))
    except requests.RequestException:
        raise ModelUnavailableError(f"Unable to connect to {label}. Check your connection and try again.") from None
    if not response.ok:
        status = response.status_code
        response.close()
        hint = {401: "Check your API key.", 403: "Check model access and API permissions.",
                404: "Check the model ID.", 429: "Check API quota, billing, or rate limits."}.get(status, "Try again later.")
        raise ModelUnavailableError(f"{label} API error ({status}). {hint}")
    response.encoding = "utf-8"
    if stream:
        return _stream(response, provider, label)
    try:
        data = response.json()
        if provider == "openai":
            return _message(data["choices"][0]["message"].get("content") or "")
        return _message("".join(b.get("text", "") for b in data["content"] if b.get("type") == "text"))
    finally:
        response.close()


def _stream(response, provider, label):
    try:
        for line in response.iter_lines(decode_unicode=True):
            if isinstance(line, bytes):
                line = line.decode("utf-8")
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            event = json.loads(payload)
            if "error" in event or event.get("type") == "error":
                raise ModelUnavailableError(f"{label} interrupted the response. Try again.")
            if provider == "openai":
                choices = event.get("choices", [])
                text = choices[0].get("delta", {}).get("content") if choices else None
            else:
                delta = event.get("delta", {})
                text = delta.get("text") if delta.get("type") == "text_delta" else None
            if text:
                yield _message(text)
    except requests.RequestException:
        raise ModelUnavailableError(f"Connection to {label} interrupted. Try again.") from None
    finally:
        response.close()
