"""uc-009 self-approval is refused, api layer: docs/usecases/agents-service/self-approval-refused.md."""

from __future__ import annotations

import os

# requesterMayDecide is open by default (c-186); this use case runs a workspace that switched it off. The dev identity
# carries the policy as a platform token would.
os.environ["OPS_DEV_POLICIES"] = '{"requesterMayDecide": false}'

from usecase_harness import TEAM, agents, check, data, finish, sse

DANA, LEE = "dana@harborpine.example", "lee@harborpine.example"


def as_user(user: str) -> dict[str, str]:
    return {**TEAM, "X-Dev-User": user}


with agents() as api:
    thread = data(
        api.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": ["kb_people"]}, headers=as_user(DANA))
    )
    res = api.post(
        f"/chat/threads/{thread['id']}/messages",
        json={"content": "Place a 24-hour hold on wire W-88213"},
        headers={**as_user(DANA), "Accept": "text/event-stream"},
    )
    events = sse(res.text)
    widget = next((e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval"), None)
    check("Dana's request paused on an approval", widget is not None, [e["type"] for e in events])
    assert widget is not None
    url = f"/chat/threads/{thread['id']}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"

    def step_up(user: str) -> str:
        return data(api.post("/v1/auth/step-up", json={"password": "northfield-demo"}, headers=as_user(user)))["token"]

    own = api.post(url, json={"type": "approve", "stepUpToken": step_up(DANA)}, headers=as_user(DANA))
    message = (own.json().get("error") or {}).get("message", "")
    check("Dana approving her own request is refused (403)", own.status_code == 403, own.text[:200])
    check("the refusal says someone else must decide", "someone else" in message, message)
    # Non-vacuous pair: the same approval by another person goes through, so the 403 above is about who, not what.
    other = api.post(url, json={"type": "approve", "stepUpToken": step_up(LEE)}, headers=as_user(LEE))
    check(
        "Lee approving it succeeds (200)",
        other.status_code == 200 and data(other)["state"] == "approved",
        other.text[:200],
    )

finish()
