"""uc-018 create, edit, publish an agent and chat with it, api layer.

Doc: docs/usecases/agents-service/agent-create-publish-chat.md.
"""

from __future__ import annotations

import secrets

from usecase_harness import TEAM, agents, check, data, finish, models, new_thread, run, sse, state

# The agent names a models-service alias; models-service is the one that says which aliases exist.
with models() as models_url, agents(models_url=models_url) as api:
    name = f"Payee Checker {secrets.token_hex(2)}"
    res = api.post(
        "/v1/agents", json={"name": name, "role": "Checks new payees", "model": "bank-standard"}, headers=TEAM
    )
    agent = data(res)
    check(
        "agent created as a draft (201, not published)",
        res.status_code == 201 and agent["availability"] == "not_published",
        res.text[:200],
    )
    aid = agent["id"]

    # Non-vacuous pair with the chat below: before a publish the agent is not live, so chat refuses it.
    early = api.post("/chat/threads", json={"agentId": aid, "kbIds": []}, headers=TEAM)
    check("chat with the unpublished agent is refused", early.status_code >= 400, early.status_code)

    res = api.patch(
        f"/v1/agents/{aid}",
        json={"instructions": "You check payees. Use lookup_account before you answer.", "toolIds": ["lookup_account"]},
        headers=TEAM,
    )
    edited = data(res)
    # Edits save into the one draft (c-172): before any publish that is still v1.
    check(
        "edit saved into the draft, nothing published",
        (edited["version"], edited["publishedVersion"]) == (1, None),
        res.text[:200],
    )

    turn = data(api.post(f"/v1/agents/{aid}/test", json={"message": "Look up account CHQ-2219"}, headers=TEAM))
    check(
        "test turn on the draft called lookup_account",
        [c["name"] for c in turn["toolCalls"]] == ["lookup_account"],
        turn,
    )

    check(
        "the test turn ran on the agent's alias, bank-standard", turn.get("model") == "bank-standard", turn.get("model")
    )

    # Non-vacuous pair with the publish below: an alias models-service does not serve is refused at publish.
    probe = data(
        api.post(
            "/v1/agents",
            json={"name": f"Alias Probe {secrets.token_hex(2)}", "role": "Probe", "model": "no-such-alias"},
            headers=TEAM,
        )
    )
    refused = api.post(f"/v1/agents/{probe['id']}/publish-requests", json={"version": 1, "note": "probe"}, headers=TEAM)
    check(
        "a publish naming an unknown model alias is refused (422 unknown_model_alias)",
        refused.status_code == 422 and (refused.json().get("error") or {}).get("code") == "unknown_model_alias",
        refused.text[:200],
    )
    api.delete(f"/v1/agents/{probe['id']}", headers=TEAM)

    res = api.post(
        f"/v1/agents/{aid}/publish-requests", json={"version": edited["version"], "note": "first publish"}, headers=TEAM
    )
    review = data(res)
    check(
        "publish request approved under dev auto-approve",
        res.status_code == 201 and review["status"] == "approved",
        res.text[:200],
    )
    graphs = {g["name"] for g in data(api.get("/v1/graphs", headers=TEAM))}
    check("its graph is listed in GET /v1/graphs", f"agent:{aid}" in graphs, sorted(graphs))

    thread = data(api.post("/chat/threads", json={"agentId": aid, "kbIds": []}, headers=TEAM))
    res = api.post(
        f"/chat/threads/{thread['id']}/messages",
        json={"content": "Look up account CHQ-2219"},
        headers={**TEAM, "Accept": "text/event-stream"},
    )
    events = sse(res.text)
    text = "".join(e.get("delta", "") for e in events if e.get("type") == "text")
    tools = [e["call"]["name"] for e in events if e.get("type") == "tool_start"]
    check(
        "chat answered after reading the account",
        "lookup_account" in tools and "found" in text,
        [e["type"] for e in events],
    )

    tid = new_thread(api, f"agent:{aid}")
    code, _ = run(api, tid, {"input": {"message": "Look up account CHQ-2219"}})
    check(
        "a thread on its graph answers",
        code == 200 and state(api, tid)["values"]["reply"] == "Here is what I found.",
        code,
    )

    # Paused: an open conversation takes no new message and no new thread starts, each refused with the reason.
    paused = api.post(f"/v1/agents/{aid}/paused", json={"paused": True}, headers=TEAM)
    refused = api.post(f"/chat/threads/{thread['id']}/messages", json={"content": "And the balance?"}, headers=TEAM)
    no_thread = api.post("/v1/threads", json={"graph": f"agent:{aid}"}, headers=TEAM)
    check(
        "paused: open chat and new threads refused as agent_paused",
        paused.status_code == 200
        and refused.status_code == 409
        and refused.json()["error"]["code"] == "agent_paused"
        and no_thread.status_code == 409,
        (paused.status_code, refused.text[:120], no_thread.status_code),
    )
    api.post(f"/v1/agents/{aid}/paused", json={"paused": False}, headers=TEAM)

    gone = api.delete(f"/v1/agents/{aid}", headers=TEAM)
    after = api.post("/v1/threads", json={"graph": f"agent:{aid}"}, headers=TEAM)
    check(
        "deleted: no new threads on its graph", gone.status_code == 204 and after.status_code == 400, after.status_code
    )

finish()
