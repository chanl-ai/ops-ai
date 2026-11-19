"""uc-757, api layer: docs/usecases/agents-service/a-builder-writes-a-skill-with.md, steps 1 to 6. A builder leaves
an agent saved before the brief as it is, writes another as a brief, adds what the brief mentions, attaches a skill
with steps, and a chat follows the steps from reply to reply. Platform sign-in (lib/main_chains.py bank_stack), the
scripted model."""

from __future__ import annotations

import json
import time
from typing import Any

from brief_steps import brief, confirm_skill, freeze_skill, hold_skill
from main_chains import ACCOUNT, bank_stack, holds, publish_bank_module
from usecase_harness import check, data, finish, sse

RUN = int(time.time())
STREAM = {"Accept": "text/event-stream"}


def code_of(res: Any) -> tuple[int, str]:
    try:
        return res.status_code, str(res.json().get("error", {}).get("code", ""))
    except ValueError:
        return res.status_code, ""


def made(res: Any) -> dict[str, Any]:
    """The created record; a refused create stops the script as setup."""
    if res.status_code not in (200, 201):
        raise SystemExit(f"FAIL setup: {res.status_code} {res.text[:400]}")
    return data(res)


with bank_stack() as s:
    me = s.who["builder"]
    _, read, write = publish_bank_module(s.gw, RUN, approval=True, team=me, security=s.who["security"])
    time.sleep(31)  # agents-service keeps each tenant's tool list for 30 seconds

    # 1. An agent saved before the brief keeps its prompt when something else is saved.
    old = data(s.api.post("/v1/agents", json={"name": f"Old desk {RUN}", "role": "Answers the team"}, headers=me))
    saved = data(s.api.patch(f"/v1/agents/{old['id']}", json={"toolIds": [read]}, headers=me))
    check(
        "1 an agent saved before the brief keeps its instructions and gets no brief",
        (saved.get("brief"), saved.get("promptMode"), saved["instructions"]) == (None, None, old["instructions"]),
        {k: saved.get(k) for k in ("brief", "promptMode", "instructions")},
    )

    # 2. A brief writes the prompt, a rename rewrites it, and the instructions cannot be edited beside it.
    agent = data(s.api.post("/v1/agents", json={"name": f"Freeze desk {RUN}", "role": "Freezes accounts"}, headers=me))
    aid = agent["id"]
    patterns = {"thinking": "low", "parallelReads": False}
    written = data(s.api.patch(f"/v1/agents/{aid}", json={"brief": brief(read), "patterns": patterns}, headers=me))
    renamed = data(s.api.patch(f"/v1/agents/{aid}", json={"name": f"Account freeze desk {RUN}"}, headers=me))
    by_hand = s.api.patch(f"/v1/agents/{aid}", json={"instructions": "Do anything."}, headers=me)
    check(
        "2 a brief writes the prompt, a rename rewrites it, and editing the instructions beside it is refused",
        written["promptMode"] == "brief"
        and written["instructions"].startswith(f"# Who you are\nYou are Freeze desk {RUN}.")
        and f"You are Account freeze desk {RUN}." in renamed["instructions"]
        and renamed["patterns"] == patterns
        and code_of(by_hand) == (422, "brief_owns_prompt"),
        (written.get("promptMode"), renamed["instructions"][:80], renamed.get("patterns"), code_of(by_hand)),
    )

    # 3. The brief mentions a tool the agent lacks: the publish is refused naming the field, and the insert fixes it.
    version = renamed["version"]
    blocked = data(s.api.get(f"/v1/agents/{aid}/publish-check", params={"version": version}, headers=me))
    refused = s.api.post(f"/v1/agents/{aid}/publish-requests", json={"version": version}, headers=me)
    problem = (blocked.get("problems") or [{}])[0]
    added = data(s.api.post(f"/v1/agents/{aid}/references", json={"kind": "tool", "id": read}, headers=me))
    again = data(s.api.post(f"/v1/agents/{aid}/references", json={"kind": "tool", "id": read}, headers=me))
    check(
        "3 a brief that mentions a tool the agent lacks cannot publish, and adding the tool once fixes it",
        blocked["canRequest"] is False
        and (problem.get("kind"), problem.get("id"), (problem.get("position") or {}).get("field"))
        == ("missing_reference", f"tool:{read}", "brief.howToAnswer")
        and code_of(refused) == (422, "cannot_publish")
        and [(i["kind"], i["id"]) for i in added["added"]] == [("tool", read)]
        and again["added"] == []
        and again["agentVersion"] == added["agentVersion"],
        (blocked, code_of(refused), added, again),
    )

    # 4. A skill with steps is saved, published and added to the agent with the skill and the tool it needs.
    confirm = made(s.api.post("/v1/skills", json=confirm_skill(RUN, "api"), headers=me))
    made(s.api.post(f"/v1/skills/{confirm['id']}/publish-requests", json={"note": "use case"}, headers=me))
    freeze = made(s.api.post("/v1/skills", json=freeze_skill(RUN, "api", read, write, confirm["id"]), headers=me))
    made(s.api.post(f"/v1/skills/{freeze['id']}/publish-requests", json={"note": "use case"}, headers=me))
    checks = [(st.get("check") or {}).get("by") for st in freeze["content"]["steps"]]
    brought = data(s.api.post(f"/v1/agents/{aid}/references", json={"kind": "skill", "id": freeze["id"]}, headers=me))
    got = sorted((i["kind"], i["id"]) for i in brought["added"])
    check(
        "4 a skill with steps is published and adding it brings the skill it runs and the tool it needs",
        checks == ["rule", None, None]
        and got == sorted([("skill", freeze["id"]), ("skill", confirm["id"]), ("tool", write)]),
        (checks, got),
    )
    # A second skill, written the way the console writes one: each step's tool is named inside its sentence.
    hold = made(s.api.post("/v1/skills", json=hold_skill(RUN, "api", read, write), headers=me))
    made(s.api.post(f"/v1/skills/{hold['id']}/publish-requests", json={"note": "use case"}, headers=me))
    made(s.api.post(f"/v1/agents/{aid}/references", json={"kind": "skill", "id": hold["id"]}, headers=me))
    now = data(s.api.get(f"/v1/agents/{aid}", headers=me))
    clear = data(s.api.get(f"/v1/agents/{aid}/publish-check", params={"version": now["version"]}, headers=me))
    sent = s.api.post(f"/v1/agents/{aid}/publish-requests", json={"version": now["version"]}, headers=me)
    review = data(sent) or {}
    if review.get("status") == "pending":
        # A brief's never rules are reviewed by a second person before they go live.
        decided = s.api.post(
            f"/v1/publish-requests/{review['id']}/decision", json={"decision": "approved"}, headers=s.who["approver"]
        )
        check("setup: the approver approves the agent's publish", decided.status_code == 200, decided.text[:300])
    live = data(s.api.get(f"/v1/agents/{aid}", headers=me))
    check(
        "5 the agent publishes once nothing is missing, and says what it uses",
        clear == {"canRequest": True, "problems": []}
        and sent.status_code == 201
        and live["publishedVersion"] == now["version"]
        and live["uses"] == {"tools": 2, "knowledgeBases": 0, "skills": 3, "agents": 0, "workflows": 0},
        (clear, sent.status_code, sent.text[:200], live.get("uses")),
    )

    # 6. A chat starts the skill and each reply goes on from the step the last one reached.
    thread = data(s.api.post("/chat/threads", json={"agentId": aid, "kbIds": []}, headers=me))["id"]

    used: list[list[Any]] = []
    sent: list[dict[str, Any]] = []

    def say(text: str) -> dict[str, Any]:
        res = s.api.post(
            f"/chat/threads/{thread}/messages", json={"content": text}, headers={**me, **STREAM}, timeout=120
        )
        if res.status_code != 200:
            raise SystemExit(f"FAIL chat: {res.status_code} {res.text[:300]}")
        sent[:] = sse(res.text)
        reply = last_reply()
        used.append([k.get("skillId") for k in reply.get("skills") or []])
        return (reply.get("skillRun") or {}).get("running") or {}

    def last_reply() -> dict[str, Any]:
        messages = data(s.api.get(f"/chat/threads/{thread}", headers=me))["messages"]
        return [m for m in messages if m.get("role") == "assistant"][-1]

    def decide(action: dict[str, Any]) -> dict[str, Any]:
        """A second person decides the write the last reply stopped on; the reply's running-skill record after it."""
        card = next(e["widget"] for e in sent if e["type"] == "widget" and e["widget"]["kind"] == "approval")
        url = f"/chat/threads/{thread}/messages/{sent[0]['messageId']}/widgets/{card['id']}/actions"
        approver = s.who["approver"]
        if action["type"] == "approve":
            step_up = s.accounts.post("/v1/auth/step-up", json={"password": "northfield-demo"}, headers=approver)
            action = {**action, "stepUpToken": data(step_up)["token"]}
        res = s.api.post(url, json=action, headers=approver)
        if res.status_code != 200:
            raise SystemExit(f"FAIL decision: {res.status_code} {res.text[:300]}")
        return last_reply().get("skillRun") or {}

    account = json.dumps({"accountId": ACCOUNT})
    slug = json.dumps({"slug": freeze["slug"]})
    started = say(f"call switch_skill {slug}")
    read_done = say(f"call {read} {account}")
    idle = say("What does a freeze do?")
    confirmed = say("call step_done {}")
    paused = say(f"call {write} {account}")
    trail = [
        (started.get("step"), bool(started.get("sub"))),
        (read_done.get("step"), (read_done.get("sub") or {}).get("step")),
        (idle.get("step"), (idle.get("sub") or {}).get("step")),
        (confirmed.get("step"), bool(confirmed.get("sub"))),
        (paused.get("step"), bool(paused.get("sub"))),
    ]
    # The reply that starts the skill lists it among its skills, which the test panel counts.
    listed = freeze["id"] in used[0]
    # Non-vacuous: the third reply calls nothing, and the fourth still finds the skill inside step 2. With the record
    # not carried between replies, every reply starts with no skill running and the trail is empty.
    check(
        "6 each reply goes on from the step the last one reached, and the write waits for a person on step 3",
        trail == [(1, False), (2, 1), (2, 1), (3, False), (3, False)] and not holds(s.bank) and listed,
        (trail, len(holds(s.bank)), used[0]),
    )

    # The write is approved: the same reply goes on from step 3, the freeze reaches the bank and the skill ends done.
    after = decide({"type": "approve"})
    ends = [h.get("ended") for h in after.get("history") or []]
    check(
        "6 an approved write goes on from the step it waited on, and the skill ends as done",
        after.get("running") is None and ends[-1:] == ["done"] and len(holds(s.bank)) == 1,
        (after.get("running"), ends, len(holds(s.bank))),
    )

    # A model that reaches for load_skill starts the same steps: a second chat, started that way, goes on from step 1.
    thread = data(s.api.post("/chat/threads", json={"agentId": aid, "kbIds": []}, headers=me))["id"]
    loaded = say(f"call load_skill {slug}")
    went_on = say(f"call {read} {account}")
    check(
        "6 loading the skill starts it at step 1, and the next reply goes on to step 2",
        (loaded.get("step"), went_on.get("step")) == (1, 2) and freeze["id"] in used[-2],
        (loaded, went_on.get("step"), used[-2]),
    )

    # In that chat the write is rejected: the skill ends as failed and nothing more reaches the bank.
    say("call step_done {}")
    waits = say(f"call {write} {account}")
    refused = decide({"type": "reject", "reason": "Not this account."})
    ends = [h.get("ended") for h in refused.get("history") or []]
    check(
        "6 a rejected write ends the skill as failed",
        waits.get("step") == 3 and refused.get("running") is None and ends[-1:] == ["failed"] and len(holds(s.bank)) == 1,
        (waits.get("step"), refused.get("running"), ends, len(holds(s.bank))),
    )

    # A skill whose steps name their tools inside the sentence, on the agent page's test chat. On an account that
    # owes money the rule ends the skill as blocked in the reply that read it, and the write stays out of reach in
    # the reply after; on an account with money the same read goes on to step 2.
    def test_chat() -> str:
        return str(data(s.api.post("/chat/threads", json={"agentId": aid, "kbIds": [], "test": True}, headers=me))["id"])

    owing = json.dumps({"accountId": "VISA-5521"})
    hold_slug = json.dumps({"slug": hold["slug"]})
    thread = test_chat()
    on_one = say(f"call switch_skill {hold_slug}")
    say(f"call {read} {owing}")
    blocked_run = last_reply().get("skillRun") or {}
    ends = [h.get("ended") for h in blocked_run.get("history") or []]
    after = s.api.post(
        f"/chat/threads/{thread}/messages", json={"content": f"call {write} {owing}"}, headers={**me, **STREAM}, timeout=120
    )
    reached = [r for r in s.bank.received if r["method"] == "POST" and r["path"] == "/v1/accounts/VISA-5521/holds"]
    asked = [e for e in sse(after.text) if e.get("type") == "widget" and e["widget"].get("kind") == "approval"]
    check(
        "6 a rule on an account that owes money ends the skill as blocked, and the write is not asked for after it",
        on_one.get("step") == 1 and blocked_run.get("running") is None and ends[-1:] == ["blocked"] and not reached and not asked,
        (on_one.get("step"), blocked_run.get("running"), ends, len(reached), len(asked)),
    )
    thread = test_chat()
    say(f"call switch_skill {hold_slug}")
    funded = say(f"call {read} {account}")
    check("6 the same read on an account with money goes on to step 2", funded.get("step") == 2, funded)

    # The write that test chat then waits on is a task a reviewer can find and open.
    say(f"call {write} {account}")
    approver = s.who["approver"]
    listed = s.api.get("/reviews", headers=approver)
    opened = s.api.get(f"/reviews/{thread}", headers=approver)
    routes = [s.api.get(path, headers=approver).status_code for path in ("/v1/tasks", "/v1/publish-requests")]
    check(
        "6 the write a test chat waits on is listed in Human Tasks and opens for a reviewer",
        listed.status_code == 200 and thread in listed.text and opened.status_code == 200,
        (listed.status_code, thread in listed.text, opened.status_code, routes),
    )
finish()
