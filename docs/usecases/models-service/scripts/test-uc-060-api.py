"""uc-060 an alias reaches the fake OpenAI or the real one by its connection's base URL, api layer.

Doc: docs/usecases/models-service/an-alias-reaches-the-fake-openai.md.
"""

from __future__ import annotations

import json
import secrets
import tempfile
from pathlib import Path
from typing import Any

import httpx
from usecase_harness import TEAM, agents, check, data, fake_openai, finish, free_port, models, service_headers

SERVICE = service_headers("models")
RUNTIME_KEY = "mk_dev_agents"  # models-service's dev seed: agents-service's own key
SYSTEM = "You are Wire Fraud Sentinel, an assistant for Northfield Bank's Fraud Operations team."
HOLD_TOOL = {"type": "function", "function": {"name": "place_wire_hold", "parameters": {"type": "object"}}}
HOLD_ARGS = {"wireId": "W-1001", "action": "hold", "hours": 24}


def ask(api: httpx.Client, text: str, **extra: Any) -> httpx.Response:
    body = {"model": "default", "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]}
    auth = {"Authorization": f"Bearer {RUNTIME_KEY}"}
    return api.post("/v1/models/chat/completions", json={**body, **extra}, headers=auth)


def streamed(res: httpx.Response) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    text, calls, usage = "", [], {}
    for line in res.text.splitlines():
        payload = line.removeprefix("data:").strip()
        if not line.startswith("data:") or payload == "[DONE]":
            continue
        chunk = json.loads(payload)
        usage = chunk.get("usage") or usage
        for choice in chunk.get("choices") or []:
            text += choice["delta"].get("content") or ""
            calls += choice["delta"].get("tool_calls") or []
    return text, calls, usage


folder = Path(tempfile.mkdtemp(prefix="uc-060-"))
rules = [{"when": r"\bhold\b.*W-\d+", "tool": "place_wire_hold", "arguments": HOLD_ARGS}]
(folder / "script.json").write_text(json.dumps({"rules": rules}))

with (
    fake_openai(folder) as fake_url,
    models({"OPS_MODELS_FAKE_OPENAI_URL": fake_url}) as models_url,
    httpx.Client(base_url=models_url, timeout=30) as api,
):
    providers = data(api.get("/v1/models/providers", headers=SERVICE))
    local = [p for p in providers if p["id"] == "openai-local"]
    aliases = {a["name"]: a for a in data(api.get("/v1/models/aliases", headers=SERVICE))}
    check(
        "the dev seed made connection openai-local at the fake's URL and bound default to it",
        [(p["type"], p["baseUrl"]) for p in local] == [("openai-compatible", fake_url)]
        and aliases.get("default", {}).get("providerId") == "openai-local",
        (local, aliases.get("default")),
    )

    plain = ask(api, "Is wire W-1001 still pending?")
    body = plain.json()
    expected = "Wire Fraud Sentinel on default heard: Is wire W-1001 still pending?"
    check(
        "a non-streamed completion on default came from the fake, with usage filled",
        plain.status_code == 200
        and body["choices"][0]["message"]["content"] == expected
        and body["usage"]["prompt_tokens"] > 0
        and body["usage"]["completion_tokens"] > 0,
        plain.text[:300],
    )

    text, _, usage = streamed(ask(api, "Is wire W-1001 still pending?", stream=True))
    check(
        "the streamed completion says the same, ending with a usage chunk",
        text == expected and usage.get("total_tokens", 0) > 0,
        (text, usage),
    )

    tool = ask(api, "Please hold wire W-1001 for a day", tools=[HOLD_TOOL]).json()
    calls = tool["choices"][0]["message"].get("tool_calls") or []
    _, streamed_calls, _ = streamed(ask(api, "Please hold wire W-1001 for a day", tools=[HOLD_TOOL], stream=True))
    check(
        "a request offering the tool gets the script's tool call, streamed and not",
        [(c["function"]["name"], json.loads(c["function"]["arguments"])) for c in calls]
        == [("place_wire_hold", HOLD_ARGS)]
        and [c["function"]["name"] for c in streamed_calls] == ["place_wire_hold"]
        and tool["choices"][0]["finish_reason"] == "tool_calls",
        (tool, streamed_calls),
    )

    # The non-vacuous check: the connection's base URL alone decides where default goes.
    dead = f"http://127.0.0.1:{free_port()}/v1"
    moved = api.put("/v1/models/providers/openai-local", json={"baseUrl": dead}, headers=SERVICE)
    broken = ask(api, "Is wire W-1001 still pending?")
    api.put("/v1/models/providers/openai-local", json={"baseUrl": fake_url}, headers=SERVICE)
    back = ask(api, "Is wire W-1001 still pending?")
    check(
        "rebinding openai-local to a closed port fails default with 502 provider_error; rebinding back restores it",
        moved.status_code == 200
        and data(moved)["baseUrl"] == dead
        and broken.status_code == 502
        and broken.json()["error"]["code"] == "provider_error"
        and back.status_code == 200
        and back.json()["choices"][0]["message"]["content"] == expected,
        (moved.text[:200], broken.text[:200], back.text[:200]),
    )
    scripted = api.put("/v1/models/providers/prov_scripted", json={"baseUrl": dead}, headers=SERVICE)
    check(
        "the scripted connection has no endpoint to rebind (409)",
        scripted.status_code == 409 and scripted.json()["error"]["code"] == "provider_not_rebindable",
        scripted.text[:200],
    )

    # agents-service with no provider key, on its default alias default, through models-service.
    with agents(models_url=models_url, models_key=RUNTIME_KEY) as agents_api:
        name = f"Fake Desk {secrets.token_hex(2)}"
        aid = data(agents_api.post("/v1/agents", json={"name": name, "role": "Answers"}, headers=TEAM))["id"]
        published = agents_api.post(
            f"/v1/agents/{aid}/publish-requests", json={"version": 1, "note": "go"}, headers=TEAM
        )
        turn = agents_api.post(f"/v1/agents/{aid}/test", json={"message": "hello from uc-060"}, headers=TEAM)
        reply = (data(turn) or {}).get("reply", "")
        check(
            "an agent turn runs on default through models-service and the fake answers it",
            published.status_code == 201
            and turn.status_code == 200
            and data(turn)["model"] == "default"
            and reply.endswith("on default heard: hello from uc-060"),
            (published.status_code, turn.text[:300]),
        )
        agents_api.delete(f"/v1/agents/{aid}", headers=TEAM)

    logged = data(api.get("/v1/models/calls", params={"alias": "default"}, headers=SERVICE))["items"]
    check(
        "models-service logged the default calls with provider model default, the failed one as an error",
        {c["providerModel"] for c in logged} == {"default"}
        and sorted({c["outcome"] for c in logged}) == ["error", "ok"],
        [(c["outcome"], c["providerModel"]) for c in logged],
    )

finish()
