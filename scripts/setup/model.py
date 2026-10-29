"""The model answer: OpenAI, Azure OpenAI or the fake. A provider must answer `GET {base}/models/{model}` within 15
seconds: 200 shows the key works at that base URL and the model is there, 401 or 403 that the key is refused, 404 that
the model id or the base URL is wrong. It generates nothing, so no model answers in tokens; a one-token chat call was
tried first and a reasoning model (gpt-5-nano) cannot stop after one token. Azure OpenAI is called as an
OpenAI-compatible base URL with its key as a bearer token (D2). The fake makes no call, and nothing is retried."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from setup.report import Result

ITEM = "model"
OPENAI = "https://api.openai.com/v1"
TIMEOUT_S = 15
PROVIDERS = ("openai", "azure-openai", "fake")


def call(base: str, model: str, key: str) -> tuple[int, str]:
    """GET {base}/models/{model}: the status and, on an error, the provider's message."""
    request = urllib.request.Request(
        f"{base.rstrip('/')}/models/{urllib.parse.quote(model, safe='')}",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as r:
            answer = json.loads(r.read() or b"{}")
            return (r.status, "") if answer.get("id") else (502, "the answer names no model")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            # The provider's message quotes part of the key, so it is not passed on.
            return e.code, "the key was refused"
        try:
            message = str((json.loads(e.read() or b"{}").get("error") or {}).get("message") or "")
        except ValueError:
            message = ""
        if e.code == 404:
            return 404, message[:200] or "no such model at this base URL"
        return e.code, message[:200]
    except (urllib.error.URLError, OSError, ValueError) as e:
        return 0, str(e)[:200]


def check(provider: str, base: str = "", model: str = "", key: str = "") -> Result:
    provider = provider.strip().lower()
    answer = f"{provider}|{base}|{model}|{key[-6:]}"
    if provider == "fake":
        return Result(ITEM, True, "the fake model: no call made", {"DEMO_MODEL": "fake"}, answer=answer)
    if provider not in PROVIDERS:
        return Result(ITEM, False, f"provider is one of {', '.join(PROVIDERS)}, not {provider!r}", answer=answer)
    base = base.strip() or (OPENAI if provider == "openai" else "")
    if not (base and model and key):
        need = [n for n, v in (("base URL", base), ("model id", model), ("API key", key)) if not v]
        return Result(ITEM, False, f"{provider} needs {', '.join(need)}", answer=answer)
    status, message = call(base, model, key)
    secrets = (key,)
    if status != 200:
        why = f"answered {status}" + (f": {message}" if message else "") if status else f"unreachable: {message}"
        return Result(ITEM, False, f"{provider} {model} at {base} {why}", secrets=secrets, answer=answer)
    settings = {"DEMO_MODEL": model, "OPENAI_API_KEY": key}
    if base != OPENAI:
        settings["OPENAI_BASE_URL"] = base
    return Result(
        ITEM, True, f"{provider} {model} at {base}: the key works and the model is there", settings, secrets, answer
    )
