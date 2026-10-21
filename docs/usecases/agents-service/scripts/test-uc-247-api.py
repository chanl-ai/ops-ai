"""uc-247 a builder tests an agent on a real chat thread the server marks test, api layer:
docs/usecases/agents-service/test-an-agent-on-a-real-thread.md. platform-service signs the seeded people in and
agents-service verifies their tokens, as the console runs them; the agent answers on the scripted model. No model
call is made."""

from __future__ import annotations

from typing import Any

import httpx
from usecase_harness import bearer, check, data, finish, people_stack, signed_in

AGENT = "ag_branch"


def agent_tasks(agents: httpx.Client, who: dict[str, str]) -> int:
    rows = data(agents.get("/v1/agents", params={"pageSize": 100}, headers=who))["data"]
    return int(next(a for a in rows if a["id"] == AGENT)["tasks24h"])


def thread(agents: httpx.Client, who: dict[str, str], *, test: bool) -> httpx.Response:
    return agents.post("/chat/threads", json={"agentId": AGENT, "kbIds": [], "test": test}, headers=who)


def ask(agents: httpx.Client, who: dict[str, str], tid: str) -> list[str]:
    r = agents.post(
        f"/chat/threads/{tid}/messages",
        json={"content": "What are your branch hours?"},
        headers=who | {"Accept": "text/event-stream"},
        timeout=120,
    )
    return [line for line in r.text.splitlines() if line.startswith("data:")]


with people_stack() as (api, agents):
    james = bearer(signed_in(api, "j.richardson@harborpine.example"), "team_ops")
    ravi = bearer(signed_in(api, "r.menon@harborpine.example"), "team_ops")
    before = agent_tasks(agents, james)

    # 1. A builder starts a test: the server marks the thread test.
    made = thread(agents, james, test=True)
    test_thread: dict[str, Any] = data(made) if made.status_code == 201 else {}
    check(
        "1 James, a builder, starts a test thread and it is marked test",
        test_thread.get("test") is True,
        made.text[:300],
    )

    # 2. A viewer may chat but not test: asking for test is refused and nothing is stored.
    refused = thread(agents, ravi, test=True)
    check("2 Ravi, a viewer, is refused a test thread (403)", refused.status_code == 403, refused.text[:300])
    ravis_tests = data(agents.get("/chat/threads", params={"test": "true"}, headers=ravi))["data"]
    check("2 nothing was stored for Ravi", ravis_tests == [], ravis_tests)

    # 3. The test is answered through the same streamed chat a person gets.
    frames = ask(agents, james, test_thread.get("id", ""))
    check(
        "3 the test reply streams and ends done",
        any('"type":"done"' in f.replace(" ", "") for f in frames),
        frames[-2:],
    )

    # 4. The conversations list leaves the test out; the Test filter lists it, marked.
    chat = data(thread(agents, james, test=False))
    ask(agents, james, chat["id"])
    plain = [t["id"] for t in data(agents.get("/chat/threads", headers=james))["data"]]
    tests = data(agents.get("/chat/threads", params={"test": "true"}, headers=james))["data"]
    check(
        "4 the conversations list shows the chat, not the test",
        chat["id"] in plain and test_thread.get("id") not in plain,
        plain,
    )
    check(
        "4 the Test filter lists the test, marked",
        [t["id"] for t in tests] == [test_thread.get("id")] and tests[0]["test"] is True,
        tests,
    )

    # 5. The agent's tasks in the last day count the chat only.
    check(
        "5 the agent's tasks in the last day count the chat, not the test",
        agent_tasks(agents, james) == before + 1,
        (before, agent_tasks(agents, james)),
    )

finish()
