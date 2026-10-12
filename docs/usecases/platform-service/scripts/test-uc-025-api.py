"""uc-025 audit, api layer: docs/usecases/platform-service/audit-log.md."""

from __future__ import annotations

import secrets

from usecase_harness import check, data, finish, platform

PASSWORD = "northfield-demo"
# Unique per run, so a database a run reuses never answers "already invited".
RUN = secrets.token_hex(3)


def sign_in(api, email: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    token = data(api.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD}))["token"]
    return {"Authorization": f"Bearer {token}"}


def entry(entries: list[dict], action: str, target: str) -> dict:  # type: ignore[type-arg]
    return next((e for e in entries if e["action"] == action and e["targetId"] == target), {})


with platform() as (api, _):
    priya = sign_in(api, "p.shah@northfieldbank.com")
    r = api.post(
        "/v1/settings/members/invite",
        headers=priya,
        json={"emails": [f"v.okoro.{RUN}@northfieldbank.com"], "role": "viewer"},
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
        if m["email"] == "m.okafor@northfieldbank.com"
    )
    api.post("/v1/settings/members/role", headers=priya, json={"ids": [maya_id], "role": "viewer"})
    r = api.get("/v1/audit", headers=sign_in(api, "m.okafor@northfieldbank.com"))
    check("a viewer reading the audit is 403", r.status_code == 403, r.status_code)

finish()
