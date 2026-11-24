"""uc-009 self-approval is refused, api layer: docs/usecases/agents-service/self-approval-refused.md."""

from __future__ import annotations

from usecase_harness import (
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    agents,
    bearer,
    check,
    data,
    finish,
    platform,
    signed_in,
    sse,
)

# Platform sign-in, so each person carries their roles: the dev header caller holds every cell and would decide its own
# request. James is a Builder, whose role lacks Approvals · decide; Priya is the team's Admin, whose role has it.
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
JAMES, PRIYA = "j.richardson@harborpine.example", "p.shah@harborpine.example"


with platform() as (people, _internal), agents(env=AUTH) as api:
    james = bearer(signed_in(people, JAMES), "team_ops")
    priya = bearer(signed_in(people, PRIYA), "team_ops")
    thread = data(
        api.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": []}, headers=james)
    )
    res = api.post(
        f"/chat/threads/{thread['id']}/messages",
        json={"content": "Place a 24-hour hold on wire W-88213"},
        headers={**james, "Accept": "text/event-stream"},
    )
    events = sse(res.text)
    widget = next((e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval"), None)
    check("James's request paused on an approval", widget is not None, [e["type"] for e in events])
    assert widget is not None
    url = f"/chat/threads/{thread['id']}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"

    def step_up(who: dict[str, str]) -> str:
        return data(api.post("/v1/auth/step-up", json={"password": "northfield-demo"}, headers=who))["token"]

    own = api.post(url, json={"type": "approve", "stepUpToken": step_up(james)}, headers=james)
    message = (own.json().get("error") or {}).get("message", "")
    check("James approving his own request is refused (403)", own.status_code == 403, own.text[:200])
    check("the refusal says someone else must decide", "someone else" in message, message)
    # Non-vacuous pair: the same approval by another person goes through, so the 403 above is about who, not what.
    other = api.post(url, json={"type": "approve", "stepUpToken": step_up(priya)}, headers=priya)
    check(
        "Priya approving it succeeds (200)",
        other.status_code == 200 and data(other)["state"] == "approved",
        other.text[:200],
    )

finish()
