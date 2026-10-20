"""uc-023 members and roles, api layer: docs/usecases/platform-service/members-and-roles.md."""

from __future__ import annotations

from ops_identity import dev_service_signer, mint_service_token
import secrets

from usecase_harness import check, data, finish, platform

PASSWORD = "northfield-demo"
# Unique per run, so a database a run reuses never answers "already invited".
RUN = secrets.token_hex(3)


def sign_in(api, email: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    token = data(api.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD}))["token"]
    return {"Authorization": f"Bearer {token}"}


def member_id(api, h: dict[str, str], email: str) -> str:  # type: ignore[no-untyped-def]
    return next(m["id"] for m in data(api.get("/v1/settings/members", headers=h))["data"] if m["email"] == email)


with platform() as (api, internal):
    priya = sign_in(api, "p.shah@northfieldbank.com")
    r = api.post(
        "/v1/settings/members/invite",
        headers=priya,
        json={"emails": [f"r.ahmed.{RUN}@northfieldbank.com", f"l.chen.{RUN}@northfieldbank.com"], "role": "admin"},
    )
    invites = {i["email"]: i["token"] for i in data(r)["invites"]} if r.status_code == 200 else {}
    check("two invitations are created", len(data(r)["updated"]) == 2 if r.status_code == 200 else False, r.text[:200])

    # Non-vacuous: Priya is the only active admin (the invitees have not accepted), so her demotion is refused.
    me = member_id(api, priya, "p.shah@northfieldbank.com")
    r = api.post("/v1/settings/members/role", headers=priya, json={"ids": [me], "role": "viewer"})
    check(
        "demoting the only admin is skipped with a reason",
        data(r) == {"updated": [], "skipped": [{"id": me, "reason": "last_admin"}]},
        r.text[:200],
    )

    token = invites.get(f"r.ahmed.{RUN}@northfieldbank.com", "inv_missingtoken")
    r = api.post(f"/v1/invites/{token}/accept", json={"name": "Rami Ahmed"})
    accepted = data(r) if r.status_code == 200 else {}
    check(
        "accepting returns a token that already carries team_ops",
        accepted.get("principal", {}).get("teamIds") == ["team_ops"],
        r.text[:200],
    )

    maya = member_id(api, priya, "m.okafor@northfieldbank.com")
    r = api.post("/v1/settings/members/role", headers=priya, json={"ids": [maya], "role": "viewer"})
    roles = {m["email"]: m["role"] for m in data(api.get("/v1/settings/members", headers=priya))["data"]}
    check(
        "a role change applies",
        data(r)["updated"] == [maya] and roles["m.okafor@northfieldbank.com"] == "viewer",
        r.text[:200],
    )

    rami = {"Authorization": f"Bearer {accepted.get('token', '')}"}
    key = data(api.post("/v1/api-keys", headers=rami, json={"name": "rami-ci", "scopes": ["read"]}))["secret"]
    gone = member_id(api, priya, f"r.ahmed.{RUN}@northfieldbank.com")
    api.post("/v1/settings/members/delete", headers=priya, json={"ids": [gone]})
    r = api.get("/v1/me", headers=rami)
    check("removing a member ends their session", r.status_code == 401, r.status_code)
    service = mint_service_token(dev_service_signer(), service="usecases", audience="platform", tenant_id=None)
    r = internal.post("/v1/auth/introspect", json={"apiKey": key}, headers={"Authorization": f"Bearer {service}"})
    check("removing a member disables the keys they created", r.status_code == 401, r.status_code)

finish()
