"""uc-085 an agent keeps its guardrails, api layer: docs/usecases/agents-service/agent-guardrails-blocked-topics.md.

The banker demo stack (fake OpenAI behind models-service). Each model request a turn makes is a row in
model_call_records with its response; a classification is the `final_result` call, an answer is text, so "the
answering model was never called" is read from what the model returned rather than from the reply alone."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from usecase_harness import chat, check, data, demo, finish, pg_url, turn_text

ADVISOR = "ag_advisor"
GUARDRAIL = "gr_no_investment_advice"
SKILL = "sk_hardship_triage"
HARDSHIP = "My client lost her job and cannot make this month's mortgage payment. What can we do?"
BLOCKED = "Should my client buy Harbor & Pine shares?"
ALLOWED = "What does Priya Natarajan have with us?"
# Unpinned and re-run: the non-vacuous check that step 2 depends on the pin, not on the question.
UNPINNED = os.environ.get("UC085_UNPINNED") == "1"


def model_calls(tid: str) -> list[str]:
    """What each model request of the thread returned, in order: "classify" or "answer"."""

    async def go() -> list[Any]:
        engine = create_async_engine(pg_url())
        async with engine.connect() as c:
            q = sa.text("select response from model_call_records where thread_id = :t order by created_at")
            rows = (await c.execute(q, {"t": tid})).scalars().all()
        await engine.dispose()
        return list(rows)

    out: list[str] = []
    for r in asyncio.run(go()):
        parts = r.get("parts") or []
        out.append("classify" if any(p.get("tool_name") == "final_result" for p in parts) else "answer")
    return out


def journal(tid: str, kind: str) -> list[dict[str, Any]]:
    """The thread's run-event log entries of one type: the run journal."""

    async def go() -> list[Any]:
        engine = create_async_engine(pg_url())
        async with engine.connect() as c:
            q = sa.text("select data from thread_events where thread_id = :t and type = :k order by seq")
            rows = (await c.execute(q, {"t": tid, "k": kind})).scalars().all()
        await engine.dispose()
        return list(rows)

    return asyncio.run(go())


def done(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next((e["message"] for e in events if e.get("type") == "done"), {})


with demo() as d:
    api = d.api
    advisor = data(api.get(f"/v1/agents/{ADVISOR}"))
    pins = advisor["guardrailPins"]
    g = data(api.get(f"/v1/guardrails/{GUARDRAIL}"))
    check(
        "1 the seeded guardrail is published and pinned on the advisor",
        g["publishedVersion"] == 1 and [(p["guardrailId"], p["version"]) for p in pins] == [(GUARDRAIL, 1)],
        pins,
    )
    message = g["config"]["message"]
    if UNPINNED:
        data(api.delete(f"/v1/agents/{ADVISOR}/skills/{SKILL}"))
        v = data(api.patch(f"/v1/agents/{ADVISOR}", json={"guardrailPins": []}))["version"]
        data(api.post(f"/v1/agents/{ADVISOR}/publish-requests", json={"version": v}))

    tid, events = chat(api, ADVISOR, BLOCKED)
    calls, hit = model_calls(tid), done(events).get("guardrail")
    check(
        "2 a blocked question gets the guardrail's message and the answering model is never called",
        turn_text(events) == message and calls == ["classify"],
        {"text": turn_text(events)[:120], "calls": calls},
    )
    check(
        "2 the turn names the guardrail, its version and the topic",
        hit
        == {"guardrailId": GUARDRAIL, "version": 1, "name": g["name"], "topic": "investment advice", "when": "before"},
        hit,
    )

    tid, events = chat(api, ADVISOR, ALLOWED)
    calls = model_calls(tid)
    check(
        "3 an allowed question is answered, with its tool reads, between a check of the question and of the answer",
        "Priya" in turn_text(events)
        and calls[0] == calls[-1] == "classify"
        and calls[1:-1].count("answer") == len(calls) - 2 >= 1
        and not done(events).get("guardrail"),
        {"text": turn_text(events)[:120], "calls": calls},
    )

    skills = data(api.get(f"/v1/agents/{ADVISOR}/skills"))
    tid, events = chat(api, ADVISOR, HARDSHIP)
    loaded = done(events).get("skills") or []
    logged = journal(tid, "skill_loaded")
    check(
        "4 a hardship question is answered by the always-on skill, and the turn records it",
        [(p["skillId"], p["pinnedVersion"], p["loading"]) for p in skills["pins"]] == [(SKILL, 1, "always")]
        and [(x["skillId"], x["version"], x["matched"]) for x in loaded] == [(SKILL, 1, "Always on")]
        and "hardship request form" in turn_text(events),
        {
            "pins": skills["pins"],
            "loaded": loaded,
            "journal": logged,
            "text": turn_text(events)[:120],
            "calls": model_calls(tid),
        },
    )

    d.stop_provider()
    tid, events = chat(api, ADVISOR, ALLOWED)
    err = next((e for e in events if e.get("type") == "error"), {})
    check(
        "5 with the classifier unreachable the turn fails closed as guardrail_unavailable",
        err.get("code") == "guardrail_unavailable" and model_calls(tid) == [],
        {"error": err, "text": turn_text(events)[:120]},
    )

finish()
