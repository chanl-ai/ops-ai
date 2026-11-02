# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-605 A team runs its agents on its own Azure OpenAI resource, api layer:
docs/usecases/models-service/a-team-connects-azure-openai.md, steps 1-6.

The run's own models-service and the fake Azure (services/models-service/scripts/fake_openai), which answers only the
key in FAKE_OPENAI_API_KEY, sent in `api-key` on the deployment path, with an api-version, and says it runs in Sweden
Central. models-service holds the key as the dev stack's provider key `AZURE_UC605`; calls use agents-service's dev
model key."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx
from usecase_harness import check, fake_openai, finish, models, service_headers

KEY = "azure-uc605-key-0123456789"
os.environ["FAKE_OPENAI_API_KEY"] = KEY
os.environ["FAKE_AZURE_REGION"] = "Sweden Central"
S = service_headers("models")
CALLER = {"Authorization": "Bearer mk_dev_agents", "X-Tenant-Id": "local"}


def sse(raw: str) -> list[dict[str, Any]]:
    """An OpenAI stream's chunks, without its closing `[DONE]`."""
    lines = [ln.removeprefix("data: ") for ln in raw.splitlines() if ln.startswith("data: ")]
    return [json.loads(ln) for ln in lines if ln != "[DONE]"]


def data(r: httpx.Response) -> Any:
    assert r.status_code < 400, f"{r.request.method} {r.request.url.path} answered {r.status_code}: {r.text[:300]}"
    return r.json()["data"]


with fake_openai(Path(tempfile.mkdtemp(prefix="uc605-fake-"))) as fake_v1:
    endpoint = fake_v1.removesuffix("/v1")
    with (
        models({"OPS_MODEL_PROVIDER_KEYS": json.dumps({"AZURE_UC605": KEY})}) as base,
        httpx.Client(base_url=base, timeout=30) as m,
    ):

        def connect(name: str, **fields: str) -> str:
            body = {"name": name, "type": "azure-openai", "baseUrl": endpoint, "keyRef": "AZURE_UC605"}
            body |= {"apiVersion": "2024-10-21", "region": "swedencentral"} | fields
            return data(m.post("/v1/models/providers", json=body, headers=S))["id"]

        def alias(name: str, provider_id: str) -> str:
            v = {"name": name, "providerId": provider_id, "modelId": "claims-gpt4o", "clearedSensitivity": "internal"}
            data(m.post("/v1/models/aliases", json=v, headers=S))
            return name

        def call(name: str, *, stream: bool = False, tools: bool = False) -> httpx.Response:
            ask = "call lookup_claim" if tools else "Summarise claim CLM-77 for the adjuster"
            body: dict[str, Any] = {"model": name, "messages": [{"role": "user", "content": ask}], "stream": stream}
            if tools:
                body["tools"] = [{"type": "function", "function": {"name": "lookup_claim", "parameters": {}}}]
            return m.post("/v1/models/chat/completions", json=body, headers=CALLER)

        def calls(name: str) -> list[dict[str, Any]]:
            return data(m.get("/v1/models/calls", params={"alias": name}, headers=S))["items"]

        def connection(pid: str) -> dict[str, Any]:
            return next(p for p in data(m.get("/v1/models/providers", headers=S)) if p["id"] == pid)

        dated = connect("claims-azure")
        claims = alias("uc605-claims", dated)
        plain = call(claims)
        check(
            "1 the key reaches Azure in its api-key header on the deployment path with the api-version",
            plain.status_code == 200 and bool(plain.json()["choices"][0]["message"]["content"]),
            plain.text[:300],
        )

        streamed = call(claims, stream=True)
        events = sse(streamed.text)
        usage = next((e["usage"] for e in events if e.get("usage")), {})
        row = calls(claims)[0]
        tool_plain = call(claims, tools=True)
        tool_stream = sse(call(claims, stream=True, tools=True).text)
        whole = tool_plain.json()["choices"][0]["message"].get("tool_calls") or []
        deltas = [c for e in tool_stream for ch in e.get("choices") or [] for c in ch["delta"].get("tool_calls") or []]
        check(
            "2 a streamed answer carries its usage, metered as sent, with no Azure annotation; tool calls come back",
            streamed.status_code == 200
            and usage.get("prompt_tokens", 0) > 0
            and (row["inputTokens"], row["outputTokens"]) == (usage["prompt_tokens"], usage["completion_tokens"])
            and "filter_results" not in streamed.text
            and [c["function"]["name"] for c in whole] == ["lookup_claim"]
            and [c["function"]["name"] for c in deltas] == ["lookup_claim"],
            {"usage": usage, "row": row, "whole": whole, "deltas": deltas},
        )

        v1 = call(alias("uc605-claims-v1", connect("claims-azure-v1", apiVersion="v1")))
        check("3 an alias on a v1 connection answers through Azure's v1 path", v1.status_code == 200, v1.text[:300])

        moved = m.put(f"/v1/models/providers/{dated}", json={"baseUrl": endpoint, "keyRef": "AZURE_UC605"}, headers=S)
        kept = connection(dated)
        check(
            "4 a rebind naming only the base URL and key keeps the api-version and region",
            moved.status_code == 200
            and (kept["apiVersion"], kept["region"]) == ("2024-10-21", "swedencentral")
            and call(claims).status_code == 200,
            kept,
        )

        wrong_id = connect("claims-wrong-region", region="eastus")
        wrong_alias = alias("uc605-wrong-region", wrong_id)
        wrong = call(wrong_alias)
        flagged = [(r["outcome"], r["reason"]) for r in calls(wrong_alias)]
        check(
            "5 an answer from another region goes through, flagged on the connection and in the call log",
            wrong.status_code == 200
            and connection(wrong_id)["observedRegion"] == "Sweden Central"
            and flagged == [("ok", "answered from Sweden Central, expected eastus")],
            {"status": wrong.status_code, "flagged": flagged},
        )

        no_region = m.post(
            "/v1/models/providers",
            json={"name": "uc605-no-version", "type": "azure-openai", "baseUrl": endpoint, "region": "eastus"},
            headers=S,
        )
        too_old = m.post(
            "/v1/models/providers",
            json={"name": "uc605-old", "type": "azure-openai", "baseUrl": endpoint, "apiVersion": "2024-02-01"}
            | {"region": "swedencentral"},
            headers=S,
        )
        seen = " ".join(
            [
                m.get("/v1/models/providers", headers=S).text,
                json.dumps(calls(claims)),
                *(r.text for r in (wrong, no_region, too_old, plain, streamed)),
            ]
        )
        check(
            "6 no list, call log, answer or refusal shows the key, and a missing or old api-version is refused",
            KEY not in seen
            and KEY[:12] not in seen
            and no_region.status_code == 400
            and "apiVersion" in no_region.text
            and too_old.status_code == 400
            and "2024-10-21" in too_old.text,
            {"no_region": no_region.text[:200], "too_old": too_old.text[:200]},
        )

finish()
