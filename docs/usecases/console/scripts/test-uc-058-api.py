"""uc-058 another person's chat stays private, api layer: docs/usecases/console/chat-read-only-for-others.md.
platform-service signs the seeded people in; agents-service and kb-service verify its tokens, on the scripted model.
James (builder) chats with a new agent once; Maya (reviewer) and Priya (admin), his teammates, then ask for that chat
through every route that names a thread: the chat route, the thread list, its state, its runs, the run's events and
the team's event stream. The chat route says only that it is not theirs; each other route answers 404 or leaves the
chat out. James reads it through all of them, the control that
the routes and ids are right."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import httpx
from usecase_harness import PLATFORM_INTERNAL_PORT, PLATFORM_PORT, agents, check, data, every_page, finish, kb, platform

PASSWORD = "northfield-demo"
JAMES = "j.richardson@harborpine.example"
MAYA = "m.okafor@harborpine.example"
PRIYA = "p.shah@harborpine.example"


def sign_in(api: httpx.Client, email: str) -> dict[str, str]:
    r = api.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD})
    if r.status_code != 200:
        raise SystemExit(f"setup: sign-in as {email} answered {r.status_code} {r.text[:200]}")
    return {"Authorization": f"Bearer {data(r)['token']}", "X-Team-Id": "team_ops"}


def made(r: httpx.Response, what: str) -> Any:
    """James's setup: anything but 2xx stops the run, so a 404 later is never read off dead setup."""
    if not r.is_success:
        raise SystemExit(f"setup: {what} answered {r.status_code} {r.text[:300]}")
    return data(r) if r.content else None


def streamed(r: httpx.Response) -> set[str]:
    """The thread ids an SSE answer names."""
    return {json.loads(line[5:]).get("threadId", "") for line in r.text.splitlines() if line.startswith("data:")}


with platform() as (api, _), tempfile.TemporaryDirectory(prefix="usecase-kb-") as files:
    auth = {
        "OPS_AUTH_MODE": "platform",
        "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
        "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
    }
    with kb(Path(files), env=auth) as know, agents(kb_url=str(know.base_url).rstrip("/"), env=auth) as svc:
        james, maya, priya = sign_in(api, JAMES), sign_in(api, MAYA), sign_in(api, PRIYA)
        agent = made(svc.post("/v1/agents", json={"name": "Helper 058", "role": "Answers questions"}, headers=james), "agent")
        made(
            svc.post(f"/v1/agents/{agent['id']}/publish-requests", json={"version": agent["version"]}, headers=james),
            "publish",
        )
        thread = made(svc.post("/chat/threads", json={"agentId": agent["id"], "kbIds": []}, headers=james), "chat")["id"]
        turn = svc.post(
            f"/chat/threads/{thread}/messages",
            json={"content": "Hello from James 058"},
            headers={**james, "Accept": "text/event-stream"},
        )
        if not turn.is_success:
            raise SystemExit(f"setup: chat turn answered {turn.status_code} {turn.text[:300]}")
        runs = made(svc.get(f"/v1/threads/{thread}/runs", headers=james), "James's runs")
        run = runs[0]["runId"] if runs else "run_none"
        reads = {
            "state": f"/v1/threads/{thread}/state",
            "runs": f"/v1/threads/{thread}/runs",
            "run events": f"/v1/threads/{thread}/runs/{run}/events?follow=false",
        }

        owner = {name: svc.get(url, headers=james).status_code for name, url in reads.items()}
        check("James reads his chat through every thread route (200)", set(owner.values()) == {200}, owner)
        for who, headers in (("Maya, a reviewer", maya), ("Priya, a team admin", priya)):
            sealed = svc.get(f"/chat/threads/{thread}", headers=headers)
            check(
                f"{who}, opens James's chat and reads only that it is not theirs",
                sealed.status_code == 200 and data(sealed) == {"id": thread, "readable": False},
                sealed.text[:200],
            )
            got = {name: svc.get(url, headers=headers).status_code for name, url in reads.items()}
            check(f"{who}, gets 404 on James's chat state, runs and run events", set(got.values()) == {404}, got)
            listed = {t["threadId"] for t in every_page(svc, "/v1/threads", headers=headers)}
            check(f"{who}, does not see James's chat in the thread list", thread not in listed, sorted(listed)[:5])
            events = streamed(svc.get("/v1/events?follow=false", headers=headers))
            check(f"{who}, does not see James's chat in the team's event stream", thread not in events, sorted(events))
        # Non-vacuous pair: the same list and stream for James name the chat, so its absence above is about who asks.
        mine = {t["threadId"] for t in every_page(svc, "/v1/threads", headers=james)}
        check("James's own thread list and event stream name the chat", thread in mine and thread in streamed(
            svc.get("/v1/events?follow=false", headers=james)
        ), sorted(mine)[:5])

finish()
