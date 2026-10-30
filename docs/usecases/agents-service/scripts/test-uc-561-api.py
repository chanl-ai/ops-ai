"""uc-561 memory follows a person across a team's agents and they take it back, api layer:
docs/usecases/agents-service/memory-follows-a-person-across-a.md. The dev person chats in one team on the scripted
model, which reads "I prefer ..." and "my <thing> is ..." as memories; the walk checks what another agent of the team
finds, what the same person finds acting in another team, and each way of taking a memory back."""

from __future__ import annotations

from typing import Any

import httpx
from usecase_harness import TEAM, agents, check, data, finish, sse

OTHER = {"X-Team-Id": "team_security"}
MINE = "/v1/me/memories"


def thread(api: httpx.Client, agent: str, headers: dict[str, str]) -> str:
    made = api.post("/chat/threads", json={"agentId": agent, "kbIds": []}, headers=headers)
    check(f"a chat with {agent} starts", made.status_code == 201, made.text[:200])
    return str(data(made)["id"]) if made.status_code == 201 else "missing"


def say(api: httpx.Client, chat: str, text: str, headers: dict[str, str] = TEAM) -> list[dict[str, Any]]:
    sent = api.post(
        f"/chat/threads/{chat}/messages", json={"content": text}, headers={**headers, "Accept": "text/event-stream"}
    )
    check(f"'{text[:40]}' is answered", sent.status_code == 200, sent.text[:200])
    return sse(sent.text) if sent.status_code == 200 else []


def remembered(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    done = next((e for e in events if e.get("type") == "done"), {})
    return list(done.get("message", {}).get("remembered") or [])


def found(events: list[dict[str, Any]]) -> str:
    return str([e["call"].get("output") for e in events if e.get("type") == "tool_end"])


def listed(api: httpx.Client, headers: dict[str, str] = TEAM) -> list[str]:
    return [str(m["value"]) for m in data(api.get(MINE, headers=headers))]


with agents() as api:
    first = thread(api, "ag_branch", TEAM)
    saved = remembered(say(api, first, "Hello there, I prefer short bullet points."))
    check(
        "the reply says it remembered the preference, in use, as new",
        [(m.get("value"), m.get("status"), m.get("decision")) for m in saved]
        == [("short bullet points", "active", "new")],
        saved,
    )
    again = remembered(say(api, thread(api, "ag_dispute", TEAM), "As I said before, I prefer short bullet points."))
    check(
        "said again to another agent, it is confirmed, not saved twice",
        [m.get("decision") for m in again] == ["same"],
        again,
    )
    check("My memory lists it once", listed(api) == ["short bullet points"], listed(api))
    search = 'call search_memory {"query": "bullet points"}'
    check(
        "another agent in the team finds it",
        "short bullet points" in found(say(api, thread(api, "ag_dispute", TEAM), search)),
    )
    elsewhere = say(api, thread(api, "ag_dispute", OTHER), search, OTHER)
    check(
        "the same person acting in another team finds nothing",
        "short bullet points" not in found(elsewhere),
        found(elsewhere),
    )
    check("and their memory there is empty", listed(api, OTHER) == [], listed(api, OTHER))

    say(api, thread(api, "ag_branch", TEAM), "Noted for later: my timezone is Eastern.")
    moved = remembered(say(api, thread(api, "ag_branch", TEAM), "I moved, so my timezone is Pacific."))
    check("a changed value replaces the old one", [m.get("decision") for m in moved] == ["replaces"], moved)
    check("only the new value is listed", sorted(listed(api)) == ["Pacific", "short bullet points"], listed(api))
    say(api, thread(api, "ag_branch", TEAM), "As before, my timezone is Pacific.")
    clash = remembered(say(api, thread(api, "ag_branch", TEAM), "Actually my timezone is Mountain."))
    check(
        "changing a confirmed memory in their own words replaces it",
        [(m.get("status"), m.get("decision")) for m in clash] == [("active", "replaces")],
        clash,
    )
    check("and only the new value is listed", "Mountain" in listed(api) and "Pacific" not in listed(api), listed(api))

    preference = str(saved[0]["id"]) if saved else "missing"
    check(
        "Undo takes back what a reply remembered",
        api.post(f"{MINE}/{preference}/undo", headers=TEAM).status_code == 204,
    )
    check("it is no longer listed", "short bullet points" not in listed(api), listed(api))
    gone = say(api, thread(api, "ag_dispute", TEAM), search)
    check("nor found by an agent", "short bullet points" not in found(gone), found(gone))
    reloaded = data(api.get(f"/chat/threads/{first}", headers=TEAM))["messages"]
    shown = [r for m in reloaded for r in m.get("remembered") or []]
    check(
        "the first reply now shows it forgotten, without its text",
        [(r.get("status"), r.get("value")) for r in shown] == [("forgotten", None)],
        shown,
    )

    zone = next((m for m in data(api.get(MINE, headers=TEAM)) if m["value"] == "Mountain"), {"id": "missing"})
    check("forget", api.delete(f"{MINE}/{zone['id']}", headers=TEAM).status_code == 204)
    check("Undo within 30 days puts it back", api.post(f"{MINE}/{zone['id']}/undo", headers=TEAM).status_code == 204)
    check("it is listed again", "Mountain" in listed(api), listed(api))
    check("erase", api.post(f"{MINE}/{zone['id']}/erase", headers=TEAM).status_code == 204)
    check(
        "an erased memory cannot be taken back", api.post(f"{MINE}/{zone['id']}/undo", headers=TEAM).status_code == 404
    )
    check("and is listed nowhere", "Mountain" not in listed(api), listed(api))

    asked = remembered(say(api, thread(api, "ag_branch", TEAM), "Remember that I prefer plain answers without tables."))
    check(
        "'remember that' saves one memory, as new",
        [(m.get("value"), m.get("decision")) for m in asked] == [("plain answers without tables", "new")],
        asked,
    )
    repeated = remembered(
        say(api, thread(api, "ag_dispute", TEAM), "Remember that I prefer plain answers without tables.")
    )
    check("asked again, it is the same memory", [m.get("decision") for m in repeated] == ["same"], repeated)
    kept = [m for m in data(api.get(MINE, headers=TEAM)) if "tables" in str(m["value"])]
    check(
        "My memory lists it once, as asked for, not as corrected",
        [(m["value"], m["source"]) for m in kept] == [("plain answers without tables", "asked")],
        kept,
    )
    changed = remembered(say(api, thread(api, "ag_branch", TEAM), "Remember that I prefer answers with a short table."))
    check(
        "a changed preference replaces the old one, even when the model calls it the same",
        [(m.get("value"), m.get("decision")) for m in changed] == [("answers with a short table", "replaces")],
        changed,
    )
    preferences = [m["value"] for m in data(api.get(MINE, headers=TEAM)) if m["kind"] == "preference"]
    check("only the new preference is listed", preferences == ["answers with a short table"], preferences)
    numbered = remembered(say(api, thread(api, "ag_branch", TEAM), "Remember that I prefer short numbered summaries."))
    check(
        "13 'remember that' keeps short numbered summaries",
        [m.get("value") for m in numbered] == ["short numbered summaries"],
        numbered,
    )
    switched = remembered(
        say(
            api,
            thread(api, "ag_branch", TEAM),
            "Actually, change that: I prefer short bullet-point summaries, not numbered ones.",
        )
    )
    check(
        "14 changing it in chat replaces it, with no question left waiting",
        [(m.get("value"), m.get("status"), m.get("decision")) for m in switched]
        == [("short bullet-point summaries", "active", "replaces")],
        switched,
    )
    kept = [m["value"] for m in data(api.get(MINE, headers=TEAM)) if m["kind"] == "preference"]
    check("14 only the new preference is listed", kept == ["short bullet-point summaries"], kept)
    summary = say(api, thread(api, "ag_branch", TEAM), "Give me a summary of my day.")
    reply = str(next((e for e in summary if e.get("type") == "done"), {}).get("message", {}).get("content", ""))
    check("15 the next summary uses bullet points", reply.startswith("- "), reply)

finish()
