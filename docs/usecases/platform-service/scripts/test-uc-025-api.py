"""uc-025 audit, api layer: docs/usecases/platform-service/audit-log.md."""

from __future__ import annotations

import json
import secrets

from usecase_harness import LOG_DIR, PLATFORM_PORT, check, data, finish, platform

PASSWORD = "northfield-demo"
# Unique per run, so a database a run reuses never answers "already invited".
RUN = secrets.token_hex(3)
# The id the invite is sent with: the audit entry and every log line of that request carry it.
SENT_ID = f"req_uc025_{RUN}"
# platform-service's stdout and stderr; the harness appends, so this run reads from the size it had at start.
LOG = LOG_DIR / f"platform-{PLATFORM_PORT}.log"
START = LOG.stat().st_size if LOG.exists() else 0


def sign_in(api, email: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """A person's headers acting in team_ops: member changes are made in a team."""
    token = data(api.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD}))["token"]
    return {"Authorization": f"Bearer {token}", "X-Team-Id": "team_ops"}


def entry(entries: list[dict], action: str, target: str) -> dict:  # type: ignore[type-arg]
    return next((e for e in entries if e["action"] == action and e["targetId"] == target), {})


with platform() as (api, _):
    priya = sign_in(api, "p.shah@harborpine.example")
    r = api.post(
        "/v1/settings/members/invite",
        headers=priya | {"X-Request-Id": SENT_ID},
        json={"emails": [f"v.okoro.{RUN}@harborpine.example"], "role": "viewer"},
    )
    invite = data(r)["invites"][0]
    api.post(f"/v1/invites/{invite['token']}/accept", json={"name": "Vic Okoro"})
    api.post("/v1/settings/members/role", headers=priya, json={"ids": [invite["memberId"]], "role": "approver"})
    entries = data(api.get("/v1/audit", headers=priya, params={"targetKind": "member", "pageSize": 200}))["data"]

    made = entry(entries, "member.invite", invite["memberId"])
    check(
        "the invite has one entry with actor, request id and target",
        made.get("actor") == "usr_admin" and made.get("requestId", "").startswith("req_"),
        made,
    )
    check(
        "the accept has its entry",
        bool(entry(entries, "member.accept", invite["memberId"])),
        [e["action"] for e in entries][:10],
    )
    check(
        "the role change has its entry",
        bool(entry(entries, "member.role", invite["memberId"])),
        [e["action"] for e in entries][:10],
    )

    api.post("/v1/settings/members/delete", headers=priya, json={"ids": [invite["memberId"]]})
    entries = data(api.get("/v1/audit", headers=priya, params={"action": "member.remove"}))["data"]
    check("the removal has its entry", bool(entry(entries, "member.remove", invite["memberId"])), entries[:3])

    # Non-vacuous: the same read as a viewer (Maya demoted for the purpose) is refused.
    maya_id = next(
        m["id"]
        for m in data(api.get("/v1/settings/members", headers=priya))["data"]
        if m["email"] == "m.okafor@harborpine.example"
    )
    api.post("/v1/settings/members/role", headers=priya, json={"ids": [maya_id], "role": "viewer"})
    r = api.get("/v1/audit", headers=sign_in(api, "m.okafor@harborpine.example"))
    check("a viewer reading the audit is 403", r.status_code == 403, r.status_code)


def parsed(line: str) -> dict | None:  # type: ignore[type-arg]
    try:
        found = json.loads(line)
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


lines = LOG.read_bytes()[START:].decode(errors="replace").splitlines()
rows = [parsed(line) for line in lines]
check(
    "every platform-service log line is one JSON object",
    bool(lines) and all(rows),
    [line[:160] for line, row in zip(lines, rows, strict=True) if not row][:5],
)
invite = [r for r in rows if r and r.get("request_id") == SENT_ID]
check(
    "the invite's log lines carry its request id, tenant local and team team_ops",
    bool(invite) and all((r.get("tenant_id"), r.get("team_id")) == ("local", "team_ops") for r in invite),
    invite[:3],
)

finish()
