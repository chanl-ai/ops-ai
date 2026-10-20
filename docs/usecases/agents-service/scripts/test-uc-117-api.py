"""uc-117 a bank's server mints a widget session with the deployment's mint key, the person's chat drafts a wire hold,
and the approval is decided in Human Tasks (the page has no route to decide it), api layer:
docs/usecases/agents-service/widget-mint-and-approve.md. agents-service runs on the scripted model with dev sign-in
(`X-Dev-User`); the page is played by this script with the intranet's Origin. No model call is made."""

from __future__ import annotations

from typing import Any

import httpx
from usecase_harness import agents, check, data, finish, sse

INTRANET = "https://intranet.bank.example"
JAMES = {"X-Team-Id": "team_ops", "X-Dev-User": "j.richardson@northfieldbank.com"}
APPROVER = {"X-Team-Id": "team_ops", "X-Dev-User": "lee@northfieldbank.com"}
HOLD = 'call place_wire_hold {"wireId": "W-1", "hours": 24, "reason": "Unusual payee"}'


def page(token: str) -> dict[str, str]:
    return {"X-Widget-Session": token, "Origin": INTRANET}


def mint(api: httpx.Client, dep: str, auth: dict[str, str], email: str = "asker@bank.example") -> httpx.Response:
    body = {"email": email, "name": email.split("@", maxsplit=1)[0], "origin": INTRANET}
    return api.post(f"/v1/widget-deployments/{dep}/sessions", json=body, headers=auth)


def deployment(api: httpx.Client, name: str) -> dict[str, Any]:
    res = api.post(
        "/v1/widget-deployments", json={"name": name, "agentId": "ag_fraud", "origins": [INTRANET]}, headers=JAMES
    )
    if res.status_code != 201:
        raise SystemExit(f"setup: create deployment answered {res.status_code}: {res.text}")
    return data(res)


def key_for(api: httpx.Client, dep: str) -> tuple[str, str]:
    res = api.post(f"/v1/widget-deployments/{dep}/keys", json={"name": "Intranet server"}, headers=JAMES)
    if res.status_code != 201:
        raise SystemExit(f"setup: create key answered {res.status_code}: {res.text}")
    made = data(res)
    return made["key"]["id"], made["secret"]


def main() -> None:
    with agents() as api:
        dep, other = deployment(api, "Intranet help"), deployment(api, "Branch kiosk")
        key_id, secret = key_for(api, dep["id"])
        _, other_secret = key_for(api, other["id"])
        bearer = {"Authorization": f"Bearer {secret}"}

        # 1. The bank's server mints with the deployment's key; a team key and another deployment's key are refused.
        minted = mint(api, dep["id"], bearer)
        check("1 the deployment's mint key mints a 15-minute session", minted.status_code == 201, minted.text[:200])
        asker = data(minted)["session"]
        team_key = mint(api, dep["id"], {"X-API-Key": "ok_ops.k1", "Authorization": "Bearer ok_ops.k1"})
        check(
            "1 a team API key is refused",
            team_key.status_code == 403 and team_key.json()["error"]["code"] == "widget_key_required",
            team_key.text[:200],
        )
        elsewhere = mint(api, dep["id"], {"Authorization": f"Bearer {other_secret}"})
        check(
            "1 another deployment's key is refused",
            elsewhere.status_code == 403 and elsewhere.json()["error"]["code"] == "widget_key_other_deployment",
            elsewhere.text[:200],
        )

        # 2. The embed app's server reads the public config; it names no team.
        cfg = api.get(f"/v1/widget/{dep['id']}/config", params={"tenant": "local"}, headers={"Origin": INTRANET})
        bare = api.get(f"/v1/widget/{dep['id']}/config", params={"tenant": "local"})
        check("2 without a listed Origin or a mint key the config is refused", bare.status_code == 403, bare.text[:200])
        body = data(cfg) or {}
        check(
            "2 the config names the origins and the agent, and no team",
            cfg.status_code == 200 and body.get("allowedOrigins") == [INTRANET] and "team_ops" not in cfg.text,
            cfg.text[:300],
        )

        # 3. On the first message the page starts the thread and sends; the agent drafts a hold that waits for approval.
        started = api.post(f"/v1/widget/{dep['id']}/threads", headers=page(asker))
        tid = (data(started) or {}).get("id", "")
        sent = api.post(
            f"/v1/widget/{dep['id']}/threads/{tid}/messages",
            json={"content": HOLD},
            headers={**page(asker), "Accept": "text/event-stream"},
        )
        widgets = [e for e in sse(sent.text) if e.get("type") == "widget"]
        check(
            "3 the thread starts with the first message and the hold stops for approval",
            bool(widgets),
            sent.text[-300:],
        )

        # 4. Another person's session cannot read it, and the page has no route to decide it.
        stranger = data(mint(api, dep["id"], bearer, "other@bank.example"))["session"]
        seen = api.get(f"/v1/widget/{dep['id']}/threads/{tid}", headers=page(stranger))
        check("4 another person's session finds no such conversation", seen.status_code == 404, seen.status_code)
        own = api.post(
            f"/v1/widget/{dep['id']}/threads/{tid}/decision", json={"decision": "approved"}, headers=page(asker)
        )
        check(
            "4 the page has no decide route: approvals are Human Tasks'", own.status_code in (404, 405), own.status_code
        )

        # 5. An approver decides in Reviews, after a step-up; the widget conversation resumes and the hold runs.
        # The gate step records the call with output {"status": "awaiting_approval"}; the run after approval does not.
        def holds() -> list[str]:
            view = data(api.get(f"/v1/widget/{dep['id']}/threads/{tid}", headers=page(asker))) or {}
            msgs = view.get("messages", [])
            out = [c for m in msgs for c in m.get("toolCalls") or [] if c["name"] == "place_wire_hold"]
            return [
                "waiting" if (c.get("output") or {}).get("status") == "awaiting_approval" else c["status"] for c in out
            ]

        waiting = holds()
        token = data(api.post("/v1/auth/step-up", json={"password": "northfield-demo"}, headers=APPROVER))["token"]
        approve = {"decision": "approved", "stepUpToken": token}
        decided = api.post(f"/reviews/{tid}/decision", json=approve, headers=APPROVER)
        check("5 an approver decides it in Reviews", decided.status_code == 200, decided.text[:200])
        ran = holds()
        check(
            "5 the page reads the hold as waiting before the approval and run after it",
            waiting == ["waiting"] and ran[-1:] == ["success"],
            {"before": waiting, "after": ran},
        )

        # 6. Revoked, the key mints nothing.
        revoked = api.post(f"/v1/widget-deployments/{dep['id']}/keys/{key_id}/revoke", headers=JAMES)
        after = mint(api, dep["id"], bearer)
        check(
            "6 a revoked key mints nothing",
            revoked.status_code == 200
            and after.status_code == 401
            and after.json()["error"]["code"] == "widget_key_invalid",
            after.text[:200],
        )
    finish()


if __name__ == "__main__":
    main()
