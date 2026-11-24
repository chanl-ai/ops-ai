"""uc-757, api layer: docs/usecases/agents-service/a-builder-writes-a-skill-with.md, steps 1 to 6. A builder leaves
an agent saved before the brief as it is, writes another as a brief, adds what the brief mentions, attaches a skill
with steps, and a chat follows the steps from reply to reply. Platform sign-in (lib/main_chains.py bank_stack), the
scripted model."""

from __future__ import annotations

import json
import time
from typing import Any

from brief_steps import (
    COMPLIANCE_HEADINGS,
    COMPLIANCE_TEXT,
    CONFIRMS,
    SECTION_HEADINGS,
    SECTIONS,
    SECTIONS_ROUTE,
    brief,
    compliance_id,
    compliance_sections,
    confirm_skill,
    freeze_skill,
    headings,
    hold_skill,
    sections_brief,
    with_compliance,
)
from main_chains import ACCOUNT, bank_stack, holds, publish_bank_module
from usecase_harness import agents, as_role, check, data, finish, save_agent, sse

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
    saved = data(save_agent(s.api, old["id"], {"toolIds": [read]}, headers=me))
    check(
        "1 an agent saved before the brief keeps its instructions and gets no brief",
        (saved.get("brief"), saved.get("promptMode"), saved["instructions"]) == (None, None, old["instructions"]),
        {k: saved.get(k) for k in ("brief", "promptMode", "instructions")},
    )

    # 2. A brief writes the prompt, a rename rewrites it, and the instructions cannot be edited beside it.
    agent = data(s.api.post("/v1/agents", json={"name": f"Freeze desk {RUN}", "role": "Freezes accounts"}, headers=me))
    aid = agent["id"]
    patterns = {"thinking": "low", "parallelReads": False}
    written = data(save_agent(s.api, aid, {"brief": brief(read), "patterns": patterns}, headers=me))
    renamed = data(save_agent(s.api, aid, {"name": f"Account freeze desk {RUN}"}, headers=me))
    by_hand = save_agent(s.api, aid, {"instructions": "Do anything."}, headers=me)
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

    # 24. A builder adds Tone and one section of his own. Each is replied with its kind and title, and View prompt
    # shows them in their places with the never rules last, whatever order they were saved in.
    desk = data(s.api.post("/v1/agents", json={"name": f"Sections desk {RUN}", "role": "Freezes accounts"}, headers=me))
    with_sections = data(save_agent(s.api, desk["id"], {"brief": sections_brief(SECTIONS)}, headers=me)) or {}
    replied = (with_sections.get("brief") or {}).get("sections")
    shown = data(s.api.get(f"/v1/agents/{desk['id']}/prompt", headers=me))["text"]
    check(
        "24 a brief saved with Tone and a custom section replies both, and the prompt has them in order, Never last",
        replied == [{**SECTIONS[0]}, {"kind": "tone", "name": "Tone", "text": "Calm and plain."}]
        and headings(shown) == SECTION_HEADINGS
        and shown.rstrip().endswith("- Never promise when a freeze will be lifted."),
        (replied, headings(shown), shown[-80:]),
    )
    # A custom section may not take a fixed heading's name: the save is refused and the stored sections stay.
    taken = save_agent(
        s.api, desk["id"], {"brief": sections_brief([{"kind": "custom", "name": " never ", "text": "Anything."}])}, headers=me
    )
    said = str((taken.json().get("error") or {}).get("message", "")) if taken.status_code >= 400 else ""
    after_refusal = (data(s.api.get(f"/v1/agents/{desk['id']}", headers=me)).get("brief") or {}).get("sections")
    check(
        "24 a custom section named like a fixed heading is refused, naming brief.sections, and nothing is stored",
        code_of(taken) == (422, "validation_failed") and "brief.sections" in said and after_refusal == replied,
        (code_of(taken), said, after_refusal),
    )
    # 25. A brief saved without sections, as every brief before them: no heading is added and it replies none.
    plain = data(s.api.post("/v1/agents", json={"name": f"Plain desk {RUN}", "role": "Freezes accounts"}, headers=me))
    unchanged = data(save_agent(s.api, plain["id"], {"brief": sections_brief()}, headers=me)) or {}
    plain_prompt = data(s.api.get(f"/v1/agents/{plain['id']}/prompt", headers=me))["text"]
    check(
        "25 a brief saved without sections writes the prompt it wrote before them and replies no sections",
        (unchanged.get("brief") or {}).get("sections") == []
        and headings(plain_prompt) == ["# Who you are", "# How to answer", "# Hand off when", "# Never"]
        and plain_prompt.startswith(str(unchanged.get("instructions"))),
        ((unchanged.get("brief") or {}).get("sections", "absent"), headings(plain_prompt)),
    )

    # 29. The list of sections is the workspace's: an admin adds Compliance notes after Tone and renames Tone, a
    # builder adds it to a new agent, and the agent of step 24, saved before the change, keeps the prompt it had.
    admin, viewer = as_role(s.accounts, "admin"), as_role(s.accounts, "viewer")
    listing = data(s.api.get(SECTIONS_ROUTE, headers=admin)) or {}
    changed = s.api.put(SECTIONS_ROUTE, json=with_compliance(listing), headers=admin)
    read_by = {who: compliance_id(data(s.api.get(SECTIONS_ROUTE, headers=h))) for who, h in (("builder", me), ("viewer", viewer))}
    not_theirs = [s.api.put(SECTIONS_ROUTE, json=listing, headers=h).status_code for h in (me, viewer)]
    not_theirs += [s.api.delete(SECTIONS_ROUTE, headers=h).status_code for h in (me, viewer)]
    check(
        "29 an admin adds Compliance notes to the workspace's sections; a builder and a viewer read it and cannot change the list",
        changed.status_code == 200 and all(read_by.values()) and not_theirs == [403] * 4,
        (changed.status_code, changed.text[:200], read_by, not_theirs),
    )
    noted = data(s.api.post("/v1/agents", json={"name": f"Compliance desk {RUN}", "role": "Freezes accounts"}, headers=me))
    saved = save_agent(s.api, noted["id"], {"brief": sections_brief(compliance_sections(read_by["builder"]))}, headers=me)
    names = [(x.get("name"), x.get("text")) for x in ((data(saved) or {}).get("brief") or {}).get("sections") or []]
    noted_prompt = (data(s.api.get(f"/v1/agents/{noted['id']}/prompt", headers=me)) or {}).get("text", "")
    check(
        "29 a brief with Compliance notes has it where the list puts it, after the renamed Tone, with Never last",
        names == [("Compliance notes", COMPLIANCE_TEXT), ("Voice", "Calm and plain.")]
        and headings(noted_prompt) == COMPLIANCE_HEADINGS
        and noted_prompt.rstrip().endswith("- Never promise when a freeze will be lifted."),
        (code_of(saved), names, headings(noted_prompt)),
    )
    kept = data(s.api.get(f"/v1/agents/{desk['id']}", headers=me)) or {}
    kept_prompt = (data(s.api.get(f"/v1/agents/{desk['id']}/prompt", headers=me)) or {}).get("text", "")
    reset = s.api.delete(SECTIONS_ROUTE, headers=admin)
    restored = data(s.api.get(SECTIONS_ROUTE, headers=admin)) or {}
    check(
        "29 the agent saved before the change keeps its prompt, and Reset to default brings the first list back",
        changed.status_code == 200
        and kept.get("instructions") == with_sections.get("instructions")
        and kept_prompt == shown
        and headings(kept_prompt) == SECTION_HEADINGS
        and reset.status_code == 200
        and bool(listing)
        and restored == listing,
        (headings(kept_prompt), reset.status_code, compliance_id(restored)),
    )

    # 20. Two sessions hold the same agent draft: the second save is refused and loses nothing the first saved.
    opened = data(s.api.get(f"/v1/agents/{aid}", headers=me))
    copy = {"baseVersion": opened["version"], "baseDigest": opened["digest"]}
    first = data(s.api.patch(f"/v1/agents/{aid}", json={"skillMenu": "attached", **copy}, headers=me))
    late = s.api.patch(f"/v1/agents/{aid}", json={"skillMenu": "off", **copy}, headers=me)
    unnamed = s.api.patch(f"/v1/agents/{aid}", json={"skillMenu": "off"}, headers=me)
    kept = data(s.api.get(f"/v1/agents/{aid}", headers=me))
    reread = data(save_agent(s.api, aid, {"skillMenu": "team"}, headers=me))
    told = (late.json().get("error") or {}).get("details") or {}
    check(
        "20 an agent save made from a copy another session has since saved is refused, and one naming no copy too",
        first["version"] == opened["version"]
        and first["digest"] != opened["digest"]
        and code_of(late) == (409, "stale_base")
        and bool(told.get("savedBy") and told.get("savedAt"))
        and unnamed.status_code == 400
        and kept["skillMenu"] == "attached"
        and kept["toolIds"] == [read]
        and reread["skillMenu"] == "team",
        (code_of(late), told, unnamed.status_code, kept.get("skillMenu"), kept.get("toolIds")),
    )

    # 21. Two sessions hold the same skill draft, which keeps its number when saved: the second save is refused.
    shared = made(s.api.post("/v1/skills", json=confirm_skill(RUN, "api-shared"), headers=me))
    sid = shared["id"]
    copy = {"baseVersion": shared["version"], "baseDigest": shared["digest"]}
    one = made(s.api.put(f"/v1/skills/{sid}/draft", json={"useWhen": "The first session's wording.", **copy}, headers=me))
    two = s.api.put(f"/v1/skills/{sid}/draft", json={"useWhen": "The second session's wording.", **copy}, headers=me)
    told = (two.json().get("error") or {}).get("details") or {}
    stored = data(s.api.get(f"/v1/skills/{sid}", headers=me))
    check(
        "21 a skill draft save made from a copy another session has since saved is refused under the same number",
        one["version"] == shared["version"]
        and code_of(two) == (409, "stale_base")
        and bool(told.get("savedBy"))
        and stored["content"]["useWhen"] == "The first session's wording.",
        (one.get("version"), code_of(two), told, stored["content"].get("useWhen")),
    )

    # 22. The same race through the text editor's save: two texts sent from one copy, the second refused, the first kept.
    base = {"baseVersion": stored["version"], "baseDigest": stored["digest"]}
    first_text = stored["text"].rstrip() + "\n\nSay the first session's closing line."
    wrote = made(s.api.put(f"/v1/skills/{sid}/draft", json={"source": first_text, **base}, headers=me))
    late = s.api.put(f"/v1/skills/{sid}/draft", json={"source": stored["text"] + "\n\nSay another line.", **base}, headers=me)
    error = late.json().get("error") or {}
    after = data(s.api.get(f"/v1/skills/{sid}", headers=me))
    check(
        "22 a text save made from a copy another text save has replaced is refused, and the first text is kept",
        wrote["version"] == stored["version"]
        and code_of(late) == (409, "stale_base")
        and bool(error.get("message") and (error.get("details") or {}).get("savedBy"))
        and "first session's closing line" in after["text"]
        and "another line" not in after["text"],
        (code_of(late), error, after["text"][-120:]),
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
        checks == ["rule", None, "rule"]
        and got == sorted([("skill", freeze["id"]), ("skill", confirm["id"]), ("tool", write)]),
        (checks, got),
    )
    # A step that changes something is refused without a rule check, and a tool a sentence only names is not the
    # step's tool: the publish check blocks on it.
    body = hold_skill(RUN, "api", read, write)
    bare = {**body, "name": f"Bare hold api {RUN}", "steps": [body["steps"][0], {"do": "Place it.", "use": body["steps"][1]["use"]}]}
    unruled = s.api.post("/v1/skills", json=bare, headers=me)
    named = {**body, "name": f"Named hold api {RUN}", "steps": [{"do": body["steps"][0]["do"]}]}
    only_named = made(s.api.post("/v1/skills", json=named, headers=me))
    stops = [(p["kind"], p["id"]) for p in only_named["publishCheck"]["problems"]]
    check(
        "4 a write step with no rule check is refused, and a tool a sentence only names blocks the publish",
        code_of(unruled) == (400, "write_needs_rule")
        and only_named["content"]["steps"][0].get("use") is None
        and stops == [("bad_step", f"tool:{read}")],
        (code_of(unruled), only_named["content"]["steps"], stops),
    )
    # A second skill, saved the way the console saves one: each step's tool is picked inside its sentence.
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
    # Before any skill is started, the write its steps own is refused: no person is asked and nothing reaches the bank.
    early = s.api.post(
        f"/chat/threads/{thread}/messages",
        json={"content": "call " + write + " " + json.dumps({"accountId": ACCOUNT})},
        headers={**me, **STREAM},
        timeout=120,
    )
    asked_early = [e for e in sse(early.text) if e.get("type") == "widget" and e["widget"].get("kind") == "approval"]
    check(
        "6 a write its skill owns is refused before the skill is started",
        early.status_code == 200 and not asked_early and not holds(s.bank),
        (early.status_code, len(asked_early), len(holds(s.bank))),
    )
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
    confirmed = say(CONFIRMS)
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
    say(CONFIRMS)
    waits = say(f"call {write} {account}")
    refused = decide({"type": "reject", "reason": "Not this account."})
    ends = [(h.get("ended"), h.get("why"), h.get("inReply")) for h in refused.get("history") or []]
    check(
        "6 a rejected write ends the skill as failed, and the record says a person denied it in this reply",
        waits.get("step") == 3
        and refused.get("running") is None
        and ends[-1:] == [("failed", "denied", True)]
        and len(holds(s.bank)) == 1,
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
    last = (blocked_run.get("history") or [{}])[-1]
    why = (last.get("why"), last.get("check"), last.get("meaning"), last.get("atStep"), last.get("inReply"))
    # The ending is final for the reply it happened in: the skill is not started again there.
    again = s.api.post(
        f"/chat/threads/{thread}/messages", json={"content": f"call switch_skill {hold_slug}"}, headers={**me, **STREAM}, timeout=120
    )
    restarted = (last_reply().get("skillRun") or {}).get("running")
    after = s.api.post(
        f"/chat/threads/{thread}/messages", json={"content": f"call {write} {owing}"}, headers={**me, **STREAM}, timeout=120
    )
    reached = [r for r in s.bank.received if r["method"] == "POST" and r["path"] == "/v1/accounts/VISA-5521/holds"]
    asked = [e for e in sse(after.text) if e.get("type") == "widget" and e["widget"].get("kind") == "approval"]
    check(
        "6 a rule on an account that owes money ends the skill as blocked, and the write is not asked for after it",
        on_one.get("step") == 1
        and blocked_run.get("running") is None
        and ends[-1:] == ["blocked"]
        and why == ("check", "result.balance > 0", "The account has nothing to hold.", 1, True)
        and not reached
        and not asked,
        (on_one.get("step"), blocked_run.get("running"), ends, why, len(reached), len(asked)),
    )
    # A new reply may start the skill again: the ending held for its own reply only.
    check("6 the next reply can start the blocked skill again", again.status_code == 200 and (restarted or {}).get("step") == 1, restarted)
    thread = test_chat()
    say(f"call switch_skill {hold_slug}")
    funded = say(f"call {read} {account}")
    check("6 the same read on an account with money goes on to step 2", funded.get("step") == 2, funded)

    # The write that test chat then waits on is a task a reviewer can find and open.
    say(f"call {write} {account}")
    approver = s.who["approver"]
    listed = s.api.get("/reviews", headers=approver)
    opened = s.api.get(f"/reviews/{thread}", headers=approver)
    mine = s.api.get("/reviews", headers=me)
    check(
        "6 the write a test chat waits on is in Human Tasks for the reviewer and the asker, and opens",
        listed.status_code == 200 and thread in listed.text and opened.status_code == 200 and thread in mine.text,
        (listed.status_code, thread in listed.text, opened.status_code, mine.status_code, thread in mine.text),
    )

    # 4, written as text. The guard is a sentence in the skill's text, read into a rule on the read's result: on an
    # account that owes money the run stops at it and holds the write after it. Without the `if not` lines the same
    # run goes on to step 2 and holds nothing.
    guarded = (
        f"Look up the account with @tool:{read}\n"
        "if not result.balance > 0:\n"
        '    stop "The account has nothing to hold."\n'
        f"Place a hold on the account with @tool:{write}"
    )
    texted = made(
        s.api.post(
            "/v1/skills",
            json={
                "name": f"Hold as text api {RUN}",
                "ownerTeam": "team_ops",
                "useWhen": "The caller asks for a hold on an account.",
                "instructions": "",
                "source": guarded,
            },
            headers=me,
        )
    )
    made(s.api.post(f"/v1/skills/{texted['id']}/publish-requests", json={"note": "use case"}, headers=me))
    made(s.api.post(f"/v1/agents/{aid}/references", json={"kind": "skill", "id": texted["id"]}, headers=me))
    thread = test_chat()
    say("call switch_skill " + json.dumps({"slug": texted["slug"]}))
    say(f"call {read} {owing}")
    stopped = last_reply().get("skillRun") or {}
    held = [(h.get("skillId"), h.get("tools")) for h in stopped.get("holds") or []]
    check(
        "4 a guard written in a skill's text stops the run on the read's result and holds the write after it",
        stopped.get("running") is None and held == [(texted["id"], [write])],
        (stopped.get("running"), held, [h.get("ended") for h in stopped.get("history") or []]),
    )

# 6, continued. A step that asks another agent, on the dev stack, where the team's default agent may ask a specialist.
# The hand-off is one more tool a skill owns: refused before the skill starts, and run as its step.
DEV = {"X-Team-Id": "team_ops", "X-Dev-User": "m.okafor@harborpine.example"}
with agents() as api:
    asks = {
        "name": f"Ask the dispute desk {RUN}",
        "ownerTeam": "team_ops",
        "useWhen": "The caller asks whether a card charge can be disputed.",
        "instructions": "",
        "steps": [
            {
                "do": "Ask the dispute desk with @agent:ag_dispute.",
                "use": {"kind": "agent", "id": "ag_dispute"},
                "check": {"text": 'result.status == "answered"'},
                "ifNot": {"action": "exit", "exit": "failed"},
            }
        ],
    }
    unruled = api.post("/v1/skills", json={**asks, "steps": [{k: v for k, v in asks["steps"][0].items() if k in ("do", "use")}]}, headers=DEV)
    skill = made(api.post("/v1/skills", json=asks, headers=DEV))
    made(api.post(f"/v1/skills/{skill['id']}/publish-requests", json={"note": "use case"}, headers=DEV))
    made(api.post("/v1/agents/ag_branch/references", json={"kind": "skill", "id": skill["id"]}, headers=DEV))
    held = data(api.get("/v1/agents/ag_branch", headers=DEV))
    made(api.post("/v1/agents/ag_branch/publish-requests", json={"version": held["version"], "note": "go"}, headers=DEV))
    api.put("/v1/chat/default-agent", json={"agentId": "ag_branch"}, headers=DEV)
    chat = data(api.post("/chat/threads", json={"agentId": "ag_branch", "kbIds": []}, headers=DEV))["id"]

    def said(text: str) -> list[tuple[str, Any]]:
        res = api.post(f"/chat/threads/{chat}/messages", json={"content": text}, headers={**DEV, **STREAM}, timeout=120)
        if res.status_code != 200:
            raise SystemExit(f"FAIL chat: {res.status_code} {res.text[:300]}")
        ended = [e["call"] for e in sse(res.text) if e.get("type") == "tool_end"]
        return [(c["name"], (c.get("output") or {}).get("status")) for c in ended]

    question = 'call agent__ag_dispute {"question": "Can I dispute a card charge?"}'
    early = said(question)
    said("call switch_skill " + json.dumps({"slug": skill["slug"]}))
    as_step = said(question)
    record = [m for m in data(api.get(f"/chat/threads/{chat}", headers=DEV))["messages"] if m.get("role") == "assistant"][-1]
    ends = [h.get("ended") for h in (record.get("skillRun") or {}).get("history") or []]
    check(
        "6 a step that asks another agent needs a rule, is refused before its skill starts, and runs as its step",
        code_of(unruled) == (400, "write_needs_rule")
        and "agent:ag_dispute" in held["toolIds"]
        and ("agent__ag_dispute", "answered") not in early
        and ("agent__ag_dispute", "answered") in as_step
        and ends[-1:] == ["done"],
        (code_of(unruled), held["toolIds"], early, as_step, ends),
    )

    # The same for a workflow a step starts: Card Dispute Resolver holds the dispute email workflow as a tool.
    starts = {
        "name": f"Start the dispute email {RUN}",
        "ownerTeam": "team_ops",
        "useWhen": "The caller wants a charge reversed by email.",
        "instructions": "",
        "steps": [
            {
                "do": "Start it with @workflow:dispute_email.",
                "use": {"kind": "workflow", "id": "dispute_email"},
                "check": {"text": 'result.status == "waiting_review"'},
                "ifNot": {"action": "exit", "exit": "failed"},
            },
            {"do": "Tell the caller a person will review it."},
        ],
    }
    bare = [{k: v for k, v in starts["steps"][0].items() if k in ("do", "use")}, starts["steps"][1]]
    unruled = api.post("/v1/skills", json={**starts, "steps": bare}, headers=DEV)
    skill = made(api.post("/v1/skills", json=starts, headers=DEV))
    made(api.post(f"/v1/skills/{skill['id']}/publish-requests", json={"note": "use case"}, headers=DEV))
    made(api.post("/v1/agents/ag_dispute/references", json={"kind": "skill", "id": skill["id"]}, headers=DEV))
    held = data(api.get("/v1/agents/ag_dispute", headers=DEV))
    made(api.post("/v1/agents/ag_dispute/publish-requests", json={"version": held["version"], "note": "go"}, headers=DEV))
    chat = data(api.post("/chat/threads", json={"agentId": "ag_dispute", "kbIds": []}, headers=DEV))["id"]
    email = {"sender": "r.osei@example.test", "subject": "Charged twice", "body": "I was charged twice for order 4411."}
    start = "call workflow__dispute_email " + json.dumps(email)
    early = said(start)
    said("call switch_skill " + json.dumps({"slug": skill["slug"]}))
    as_step = said(start)
    record = [m for m in data(api.get(f"/chat/threads/{chat}", headers=DEV))["messages"] if m.get("role") == "assistant"][-1]
    on = ((record.get("skillRun") or {}).get("running") or {}).get("step")
    check(
        "6 a step that starts a workflow needs a rule, is refused before its skill starts, and runs as its step",
        code_of(unruled) == (400, "write_needs_rule")
        and "workflow:dispute_email" in held["toolIds"]
        and ("workflow__dispute_email", "waiting_review") not in early
        and ("workflow__dispute_email", "waiting_review") in as_step
        and on == 2,
        (code_of(unruled), held["toolIds"], early, as_step, on),
    )
finish()
