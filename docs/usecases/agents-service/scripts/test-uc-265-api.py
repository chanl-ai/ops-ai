"""uc-265 personal data is masked in an agent's replies, stored messages and workflow step output, api layer.

Doc: docs/usecases/agents-service/personal-data-masked.md. ai_steps_stack (platform-service, models-service on the
fake OpenAI, agents service, worker). The fake model answers with an SSN's last four, an email, a phone and an account
number; the agent's redactPii is on by default.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from ai_steps_stack import OPS, ai_stack, definition, publish, run
from usecase_harness import bearer, check, data, finish, save_agent, signed_in, sse

SAID = "Ann Lee, SSN ending 6789, email ann.lee@example.com, phone (902) 555-0147, account 4401235567."
RAW = ("6789", "ann.lee@example.com", "555-0147", "4401235567")


def ask(api: httpx.Client, agent: str, question: str) -> tuple[str, str]:
    """The streamed reply and the reply as the thread stored it."""
    tid = data(api.post("/chat/threads", json={"agentId": agent, "kbIds": []}, headers=OPS))["id"]
    res = api.post(
        f"/chat/threads/{tid}/messages",
        json={"content": question},
        headers={**OPS, "Accept": "text/event-stream"},
        timeout=120,
    )
    streamed = "".join(str(e.get("delta", "")) for e in sse(res.text) if e.get("type") == "text")
    stored = [m for m in data(api.get(f"/chat/threads/{tid}", headers=OPS))["messages"] if m["role"] == "assistant"]
    return streamed, str(stored[-1]["content"]) if stored else ""


# Priya Shah, the team's admin, on the agents service's dev sign-in: a second person to James, who asks.
PRIYA = {"X-Dev-User": "Priya Shah", "X-Team-Id": "team_ops"}


def approved(api: httpx.Client, asked: httpx.Response) -> httpx.Response:
    """Priya approves the publish James asked for; the version goes live on approval."""
    return api.post(
        f"/v1/publish-requests/{data(asked).get('id', 'pr_x')}/decision", json={"decision": "approved"}, headers=PRIYA
    )


def shows(text: str) -> list[str]:
    return [r for r in RAW if r in text]


# Named as personal data by their field, as the fake bank names them: ssnLast4, accountIds and accountNumber.
NAMED = ("4471", "CHQ-1003", "BUS-7781", "4401235567")


def named(text: str) -> list[str]:
    return [r for r in NAMED if r in text]


with ai_stack("uc265") as (api, people):
    # Reviews are optional: Priya, the team's admin, turns them on for its agents, so redaction off waits for her.
    priya = bearer(signed_in(people, "p.shah@harborpine.example"), "team_ops")
    on = people.put("/v1/policies/publishReview", json={"value": {"agents": "always"}}, headers=priya)
    check("0 Priya turns publish review on for the team's agents", on.status_code == 200, on.text[:200])
    made: dict[str, Any] = data(
        api.post("/v1/agents", json={"name": "PII Probe", "role": "Answers about customers"}, headers=OPS)
    )
    aid = made["id"]
    first = api.post(f"/v1/agents/{aid}/publish-requests", json={"version": made["version"], "note": "first"}, headers=OPS)
    live = approved(api, first)
    check("0b Priya approves the first publish", live.status_code == 200, f"{first.text[:200]} {live.text[:300]}")

    streamed, stored = ask(api, aid, "UC265-PII who is Ann?")
    check(
        "1 the reply streams with the SSN's last four, email, phone and account masked",
        streamed and not shows(streamed) and "Ann Lee" in streamed,
        streamed,
    )
    check("2 the stored message is masked the same way", stored == streamed, stored)

    schema = {"type": "object", "required": ["summary"], "properties": {"summary": {"type": "string"}}}
    step = {
        "id": "sum",
        "type": "ops.ai.agent",
        "typeVersion": 1,
        "parameters": {
            "agent": aid,
            "prompt": "Summarise the customer.",
            "input": {"text": "$.input.body"},
            "outputSchema": schema,
        },
    }
    publish(
        api,
        definition(
            "uc265_summary",
            [step],
            [("start", "payload", "sum"), ("sum", "ok", "end_done"), ("sum", "error", "end_failed")],
        ),
    )
    done = run(api, "uc265_summary", "UC265-STEP Priya Natarajan")
    summary = str(((done["byNode"].get("sum") or {}).get("output") or {}).get("summary"))
    check(
        "3 the agent step's output is masked and keeps the name",
        "Priya Natarajan" in summary and not shows(summary),
        summary,
    )

    # Values named as personal data that no pattern finds in the value alone: a last four, lettered account ids and a
    # number-typed account number. They are masked by their field's name.
    tid = data(api.post("/chat/threads", json={"agentId": aid, "kbIds": []}, headers=OPS))["id"]
    res = api.post(
        f"/chat/threads/{tid}/messages",
        json={"content": "UC265-RECORD show Ann's record"},
        headers={**OPS, "Accept": "text/event-stream"},
        timeout=120,
    )
    events = sse(res.text)
    ended = [e for e in events if e.get("type") in ("tool_end", "part")]
    streamed = json.dumps(events)
    kept = json.dumps(data(api.get(f"/chat/threads/{tid}", headers=OPS))["messages"])
    check(
        "5 a tool result's ssnLast4, accountId and number-typed accountNumber show masked in chat, streamed and stored",
        bool(ended)
        and all(not named(t) and "[SSN]" in t and "[account]" in t and "Ann Lee" in t for t in (streamed, kept)),
        {"types": [e.get("type") for e in events], "ended": ended[:2], "kept": kept[:900]},
    )

    ids_schema = {
        "type": "object",
        "required": ["name", "ssnLast4", "accountIds", "accountNumber"],
        "properties": {
            "name": {"type": "string"},
            "ssnLast4": {"type": "string"},
            "accountIds": {"type": "array", "items": {"type": "string"}},
            "accountNumber": {"type": "number"},
        },
    }
    publish(
        api,
        definition(
            "uc265_ids",
            [{**step, "parameters": {**step["parameters"], "outputSchema": ids_schema}}],
            [("start", "payload", "sum"), ("sum", "ok", "end_done"), ("sum", "error", "end_failed")],
        ),
    )
    done = run(api, "uc265_ids", "UC265-IDS Ann Lee")
    read = json.dumps(done.get("byNode", {}).get("sum") or {})
    check(
        "6 the run's page masks the step's ssnLast4, accountIds and number-typed accountNumber and keeps the name",
        done.get("status") == "succeeded" and not named(read) and "[SSN]" in read and "Ann Lee" in read,
        read[:600],
    )
    frames = api.get(f"/v1/runs/{done.get('id')}/events", params={"follow": "false"}, headers=OPS, timeout=60).text
    # A step's events say it started and ended; its values are read from the run's page, so none of them is in a frame.
    check(
        "7 the run's events for the step carry none of the named values",
        '"node": "sum"' in frames and '"phase": "end"' in frames and not named(frames),
        [line for line in frames.splitlines() if '"sum"' in line],
    )

    agent = data(api.get(f"/v1/agents/{aid}", headers=OPS))
    off = save_agent(
        api,
        aid,
        {"guardrails": {**agent["guardrails"], "redactPii": False}, "note": "off"},
        headers=OPS,
    )
    asked = api.post(
        f"/v1/agents/{aid}/publish-requests", json={"version": data(off)["version"], "note": "off"}, headers=OPS
    )
    waits = data(asked).get("status") == "pending"
    went = approved(api, asked)
    check(
        "4a turning redactPii off waits for review, then goes live when Priya approves",
        waits and went.status_code == 200 and data(went).get("status") == "approved",
        f"{asked.text[:200]} {went.text[:200]}",
    )
    plain, _ = ask(api, aid, "UC265-PII who is Ann?")
    check("4 with redactPii off the reply is as the model wrote it", plain == SAID, plain)

finish()
