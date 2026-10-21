"""uc-134 an agent remembers each person, api layer: docs/usecases/agents-service/agent-remembers-each-person.md.

The agents service on the scripted model under dev auth: each X-Dev-User is a person, keyed by email."""

from __future__ import annotations

from typing import Any

from usecase_harness import agents, check, data, finish, sse

MAYA = {"X-Team-Id": "team_ops", "X-Dev-User": "m.okafor@harborpine.example"}
JAMES = {"X-Team-Id": "team_ops", "X-Dev-User": "j.richardson@harborpine.example"}


def say(api: Any, who: dict[str, str], text: str) -> list[dict[str, Any]]:
    tid = data(api.post("/chat/threads", json={"agentId": "ag_branch", "kbIds": []}, headers=who))["id"]
    res = api.post(
        f"/chat/threads/{tid}/messages",
        json={"content": text},
        headers={**who, "Accept": "text/event-stream"},
        timeout=120,
    )
    if res.status_code != 200:
        raise SystemExit(f"FAIL send: {res.status_code} {res.text[:300]}")
    return sse(res.text)


def searched(events: list[dict[str, Any]]) -> str:
    return str([e["call"].get("output") for e in events if e.get("type") == "tool_end"])


with agents() as api:
    say(api, MAYA, "Hello. My timezone is Eastern.")
    kept = data(api.get("/v1/me/memories?agentId=ag_branch", headers=MAYA))
    check("1 the fact is kept for Maya", [(m["key"], m["value"]) for m in kept] == [("timezone", "Eastern")], kept)

    found = searched(say(api, MAYA, 'call search_memory {"query": "timezone"}'))
    check("2 a new chat finds it with search_memory", "Eastern" in found, found[:300])

    fixed = api.patch(f"/v1/me/memories/{kept[0]['id']}", json={"value": "Pacific"}, headers=MAYA)
    now = data(api.get("/v1/me/memories?agentId=ag_branch", headers=MAYA))
    check(
        "3 a correction replaces it",
        fixed.status_code == 200 and [m["value"] for m in now] == ["Pacific"],
        [m["value"] for m in now],
    )

    check("4 another person sees none of it", data(api.get("/v1/me/memories", headers=JAMES)) == [])

    gone = api.delete(f"/v1/me/memories/{now[0]['id']}", headers=MAYA)
    after = data(api.get("/v1/me/memories", headers=MAYA))
    again = searched(say(api, MAYA, 'call search_memory {"query": "timezone"}'))
    actions = [a["action"] for a in data(api.get("/v1/me/memories/export", headers=MAYA))["audit"]]
    check(
        "5 a forget removes it at once and is recorded",
        gone.status_code == 204 and after == [] and "Pacific" not in again and {"correct", "forget"} <= set(actions),
        {"status": gone.status_code, "after": after, "search": again[:200], "audit": actions},
    )
finish()
