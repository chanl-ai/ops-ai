"""A read writes no row: every GET a screen calls, as a signed-in admin, sends no INSERT, UPDATE or DELETE to the
database. A signed-out or expired session is still refused on a GET, so the read-only liveness check keeps the gate."""

from __future__ import annotations

from typing import Any

from sqlalchemy import event

from ops_platform.store.tables import sessions

from .conftest import DEMO_PASSWORD, SignInRig

READS = (
    "/v1/me",
    "/v1/teams",
    "/v1/me/permissions",
    "/v1/roles",
    "/v1/settings/members",
    "/v1/settings/members/options",
    "/v1/policies",
    "/v1/team-names",
    "/v1/people-names",
    "/v1/api-keys",
    "/v1/api-key-summaries",
    "/v1/audit",
    "/v1/oauth/grants",
    "/v1/settings/teams",
    "/v1/settings/workspace-teams",
    "/v1/settings/sign-in/providers",
    "/v1/settings/sign-in/secret-names",
    "/v1/settings/sign-in/break-glass",
)
WRITES = ("INSERT", "UPDATE", "DELETE", "MERGE")


async def test_no_get_writes_a_row(signin: SignInRig) -> None:
    sent: list[str] = []

    def seen(_c: Any, _cur: Any, statement: str, *_: Any) -> None:
        if statement.lstrip().upper().startswith(WRITES):
            sent.append(statement.split("\n", 1)[0][:80])

    target = signin.app_engine.sync_engine
    writers: dict[str, list[str]] = {}
    event.listen(target, "before_cursor_execute", seen)
    try:
        for path in READS:
            sent.clear()
            r = await signin.public.get(path, headers=signin.admin)
            assert r.status_code == 200, (path, r.text)
            if sent:
                writers[path] = list(sent)
    finally:
        event.remove(target, "before_cursor_execute", seen)
    assert writers == {}, writers


async def _session(rig: SignInRig, email: str) -> dict[str, str]:
    await rig.person(email)
    r = await rig.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


async def test_a_signed_out_or_expired_session_is_refused_on_a_get(signin: SignInRig) -> None:
    out = await _session(signin, f"leaver@{signin.zone}")
    assert (await signin.public.get("/v1/me", headers=out)).status_code == 200
    assert (await signin.public.post("/v1/auth/sign-out", headers=out)).status_code == 204
    gone = await signin.public.get("/v1/me", headers=out)
    assert gone.status_code == 401, gone.text

    old = await _session(signin, f"idle@{signin.zone}")
    async with signin.engine.begin() as c:
        await c.execute(
            sessions.update().where(sessions.c.tenant_id == signin.tenant).where(
                sessions.c.revoked_at.is_(None)
            ).values(expires_at="2000-01-01T00:00:00+00:00")
        )  # fmt: skip
    expired = await signin.public.get("/v1/me", headers=old)
    assert expired.status_code == 401, expired.text
