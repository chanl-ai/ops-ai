"""uc-028 an agent runs on the model its publisher chose, api layer.

Doc: docs/usecases/agents-service/agent-runs-on-its-model.md.
"""

from __future__ import annotations

import secrets

import httpx
from usecase_harness import TEAM, agents, check, data, finish, models, new_thread, run, service_headers

SERVICE = service_headers("models")
# Two turns spend the key's minute; the third is over its limit.
RATE_LIMIT = 2

with models() as models_url, httpx.Client(base_url=models_url, timeout=30) as admin:
    # agents-service gets a key of its own for this run, so the limit counts only this run's calls.
    key_id = f"purpose:uc-028-{secrets.token_hex(3)}"
    issued = admin.post(
        "/v1/models/keys",
        json={"id": key_id, "kind": "purpose", "budget": "5", "rateLimitPerMinute": RATE_LIMIT},
        headers=SERVICE,
    )
    secret = data(issued)["secret"]

    def calls(**params: str) -> list[dict[str, str]]:
        return data(admin.get("/v1/models/calls", params={"keyId": key_id, **params}, headers=SERVICE))["items"]

    with agents(models_url=models_url, models_key=secret, model_alias="bank-standard") as api:
        name = f"Reasoning Desk {secrets.token_hex(2)}"
        agent = data(
            api.post("/v1/agents", json={"name": name, "role": "Answers", "model": "bank-reasoning"}, headers=TEAM)
        )
        aid = agent["id"]
        published = api.post(f"/v1/agents/{aid}/publish-requests", json={"version": 1, "note": "go"}, headers=TEAM)

        turn = data(api.post(f"/v1/agents/{aid}/test", json={"message": "hello"}, headers=TEAM))
        check(
            "the test turn ran on the agent's alias, bank-reasoning, through models-service",
            published.status_code == 201
            and turn["model"] == "bank-reasoning"
            and turn["reply"] == "scripted reply from scripted-reasoning",
            (published.status_code, turn),
        )
        on_alias = calls(alias="bank-reasoning")
        check(
            "models-service logged it under agents-service's key on bank-reasoning",
            [(c["outcome"], c["providerModel"]) for c in on_alias] == [("ok", "scripted-reasoning")],
            on_alias,
        )

        # A graph run: the record the agents service keeps and models-service's row name the same call.
        tid = new_thread(api, f"agent:{aid}")
        code, events = run(api, tid, {"input": {"message": "hello"}})
        recorded = [e["data"] for e in events if e.get("event") == "model_call"]
        logged = calls(threadId=tid)
        check(
            "the run's record and the call log agree on alias, request hash and tokens",
            code == 200
            and len(recorded) == 1
            and len(logged) == 1
            and recorded[0]["alias"] == logged[0]["alias"] == "bank-reasoning"
            and recorded[0]["requestHash"] == logged[0]["requestHash"]
            # The tokens the run meters are the ones models-service charged, so budgets on both sides agree.
            and (recorded[0]["inputTokens"], recorded[0]["outputTokens"])
            == (logged[0]["inputTokens"], logged[0]["outputTokens"])
            and recorded[0]["inputTokens"] > 0,
            (code, recorded, logged),
        )

        probe = data(
            api.post(
                "/v1/agents",
                json={"name": f"Alias Probe {secrets.token_hex(2)}", "role": "Probe", "model": "no-such-alias"},
                headers=TEAM,
            )
        )
        refused = api.post(f"/v1/agents/{probe['id']}/publish-requests", json={"version": 1, "note": "p"}, headers=TEAM)
        check(
            "a publish naming an unknown alias is refused (422 unknown_model_alias)",
            refused.status_code == 422 and refused.json()["error"]["code"] == "unknown_model_alias",
            refused.text[:200],
        )
        api.delete(f"/v1/agents/{probe['id']}", headers=TEAM)

        over = api.post(f"/v1/agents/{aid}/test", json={"message": "hello again"}, headers=TEAM)
        check(
            "a key over its limit answers the test turn 429 rate_limited",
            over.status_code == 429 and over.json()["error"]["code"] == "rate_limited",
            over.text[:200],
        )
        denied = calls(outcome="denied")
        check(
            "models-service logged one denied call for it, with no retry behind it",
            [c["reason"] for c in denied] == ["rate_limited"],
            denied,
        )
        everything = calls()
        check(
            "every call went to the scripted provider (no real model call)",
            all(c["providerModel"] is None or str(c["providerModel"]).startswith("scripted-") for c in everything),
            [c["providerModel"] for c in everything],
        )
        api.delete(f"/v1/agents/{aid}", headers=TEAM)

finish()
