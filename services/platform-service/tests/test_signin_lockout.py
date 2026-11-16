"""Wrong passwords lock sign-in and step-up, and reset mail is capped, by failure mode: wrong passwords never
lock, or the right one signs in while locked (F1); step-up wrong passwords are not counted with sign-in ones (F2); two
wrong passwords at once count as one (F3); a reset request floods the inbox or answers differently once capped (F4); a
reset, the lock's time passing or a right password does not clear it (F5). The rig's limits are the defaults: five
wrong passwords in fifteen minutes lock for fifteen, and three reset links an hour."""

from __future__ import annotations

import asyncio
import hashlib
import re

import httpx
import sqlalchemy as sa

from ops_platform.store.roles import ensure_builtin_roles
from ops_platform.store.tables import audit_entries, signin_email_failures, signin_lockouts, tenants
from ops_service_kit.ids import new_id, now_iso

from .conftest import DEMO_PASSWORD, SignInRig

WRONG = "not the password at all"
NEW = "a long new password 2"


async def _sign_in(rig: SignInRig, email: str, password: str) -> httpx.Response:
    return await rig.public.post("/v1/auth/sign-in", json={"email": email, "password": password})


async def test_five_wrong_passwords_lock_even_the_right_one_out(signin: SignInRig) -> None:
    email = f"lock@{signin.zone}"
    await signin.person(email)
    codes = [(await _sign_in(signin, email, WRONG)).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 401, 429], codes
    right = await _sign_in(signin, email, DEMO_PASSWORD)
    assert right.status_code == 429 and right.json()["error"]["code"] == "signin_locked", right.text
    assert 840 <= int(right.headers["Retry-After"]) <= 900
    assert "Try again in 15 minutes" in right.json()["error"]["message"]
    async with signin.engine.connect() as c:
        locks = (await c.execute(sa.select(sa.func.count()).where(audit_entries.c.action == "signin.locked"))).scalar()
    assert locks and locks >= 1


async def test_step_up_wrong_passwords_count_with_sign_in_ones(signin: SignInRig) -> None:
    email = f"step@{signin.zone}"
    await signin.person(email)
    auth = {"Authorization": f"Bearer {(await _sign_in(signin, email, DEMO_PASSWORD)).json()['data']['token']}"}
    for _ in range(3):
        assert (await _sign_in(signin, email, WRONG)).status_code == 401
    assert (await signin.public.post("/v1/auth/step-up", json={"password": WRONG}, headers=auth)).status_code == 401
    last = await signin.public.post("/v1/auth/step-up", json={"password": WRONG}, headers=auth)
    assert last.status_code == 429 and last.json()["error"]["code"] == "signin_locked", last.text
    right = await signin.public.post("/v1/auth/step-up", json={"password": DEMO_PASSWORD}, headers=auth)
    assert right.status_code == 429


async def test_wrong_passwords_at_once_each_count(signin: SignInRig) -> None:
    email = f"race@{signin.zone}"
    await signin.person(email)
    await asyncio.gather(*(_sign_in(signin, email, WRONG) for _ in range(5)))
    assert (await _sign_in(signin, email, DEMO_PASSWORD)).status_code == 429


async def test_wrong_passwords_at_once_for_an_unknown_address_each_count(signin: SignInRig) -> None:
    # F3 for the address count alone: an unknown address has no person count to lock it.
    email = f"nobody-race-{signin.zone.split('.')[0]}@{signin.zone}"
    await asyncio.gather(*(_sign_in(signin, email, WRONG) for _ in range(5)))
    assert (await _sign_in(signin, email, WRONG)).status_code == 429


async def test_reset_mail_is_capped_and_answered_the_same(signin: SignInRig) -> None:
    email = f"flood@{signin.zone}"
    await signin.person(email)
    replies = [
        (await signin.public.post("/v1/auth/password/forgot", json={"email": email})).status_code for _ in range(5)
    ]
    assert replies == [204] * 5
    assert len([m for m in signin.mail.sent.values() if m.to == (email,)]) == 3


async def test_a_reset_the_lock_ending_or_a_right_password_clears_it(signin: SignInRig) -> None:
    email = f"clear@{signin.zone}"
    await signin.person(email)
    # A right password before the limit starts the count again.
    for _ in range(4):
        await _sign_in(signin, email, WRONG)
    assert (await _sign_in(signin, email, DEMO_PASSWORD)).status_code == 200
    for _ in range(4):
        assert (await _sign_in(signin, email, WRONG)).status_code == 401
    assert (await _sign_in(signin, email, DEMO_PASSWORD)).status_code == 200
    # Locked, then the lock's time passes.
    for _ in range(5):
        await _sign_in(signin, email, WRONG)
    assert (await _sign_in(signin, email, DEMO_PASSWORD)).status_code == 429
    async with signin.engine.begin() as c:
        await c.execute(signin_lockouts.update().values(locked_until="2000-01-01T00:00:00.000Z"))
        await c.execute(signin_email_failures.update().values(locked_until="2000-01-01T00:00:00.000Z"))
    assert (await _sign_in(signin, email, DEMO_PASSWORD)).status_code == 200
    # Locked again, then a reset link sets a new password and ends the lock.
    for _ in range(5):
        await _sign_in(signin, email, WRONG)
    assert (await signin.public.post("/v1/auth/password/forgot", json={"email": email})).status_code == 204
    sent = [m for m in signin.mail.sent.values() if m.to == (email,)]
    token = re.search(r"/reset-password/(prt_[A-Za-z0-9_-]+)", sent[-1].body)
    assert token
    done = await signin.public.post("/v1/auth/password/reset", json={"token": token.group(1), "password": NEW})
    assert done.status_code == 204, done.text
    assert (await _sign_in(signin, email, NEW)).status_code == 200


async def test_an_unknown_email_is_answered_exactly_as_a_known_one(signin: SignInRig) -> None:
    # F6: an unknown address answered 401 forever while a known one locked, which told an attacker
    # which addresses have accounts. Both now get the same answers, wrong password after wrong password.
    known = f"known@{signin.zone}"
    await signin.person(known)
    unknown = f"nobody-{signin.zone.split('.')[0]}@{signin.zone}"
    seen: dict[str, list[tuple[int, str]]] = {}
    for email in (known, unknown):
        replies = [await _sign_in(signin, email, WRONG) for _ in range(6)]
        seen[email] = [(r.status_code, r.json()["error"]["code"]) for r in replies]
    assert seen[known] == seen[unknown], seen
    assert [code for code, _ in seen[unknown]] == [401, 401, 401, 401, 429, 429], seen


async def test_the_table_keeps_no_address_and_no_plain_hash_of_one(signin: SignInRig) -> None:
    # F7: the per-address count is keyed with the service's secret, so the table cannot confirm an address.
    email = f"keyed@{signin.zone}"
    await _sign_in(signin, email, WRONG)
    async with signin.engine.connect() as c:
        keys = [r[0] for r in (await c.execute(sa.select(signin_email_failures.c.email_hash))).all()]
    assert keys and email not in keys and hashlib.sha256(email.encode()).hexdigest() not in keys, keys


async def test_a_count_from_before_the_window_starts_again(signin: SignInRig) -> None:
    # F8: wrong passwords spread past the fifteen-minute window add up to a lock.
    email = f"window@{signin.zone}"
    await signin.person(email)
    for _ in range(4):
        assert (await _sign_in(signin, email, WRONG)).status_code == 401
    async with signin.engine.begin() as c:
        await c.execute(signin_lockouts.update().values(first_failed_at="2000-01-01T00:00:00.000Z"))
        await c.execute(signin_email_failures.update().values(first_failed_at="2000-01-01T00:00:00.000Z"))
    codes = [(await _sign_in(signin, email, WRONG)).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 401, 429], codes


async def test_one_address_in_two_workspaces_has_one_count(signin: SignInRig) -> None:
    # F9: sign-in names no workspace, so an address two workspaces hold is refused, and counted once per attempt
    # in one count for the address, not once per workspace; no person is locked, so nothing is audited.
    email = f"twice@{signin.zone}"
    other = new_id("ten")
    async with signin.engine.begin() as c:
        await c.execute(
            tenants.insert().values(id=other, name=other, status="active", allowed_domains=[], created_at=now_iso())
        )
        await ensure_builtin_roles(c, other, at=now_iso())
    people = [await signin.person(email), await signin.person(email, tenant=other)]
    f = signin_email_failures.c
    async with signin.engine.connect() as c:
        before = set((await c.execute(sa.select(f.email_hash))).scalars())
    codes = [(await _sign_in(signin, email, DEMO_PASSWORD)).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 401, 429], codes
    async with signin.engine.connect() as c:
        added = (await c.execute(sa.select(f.locked_until).where(f.email_hash.not_in(before)))).scalars().all()
        held = (await c.execute(sa.select(sa.func.count()).where(signin_lockouts.c.user_id.in_(people)))).scalar()
        audited = (await c.execute(sa.select(sa.func.count()).where(audit_entries.c.target_id.in_(people)))).scalar()
    assert len(added) == 1 and added[0] and added[0] > now_iso(), added
    assert (held, audited) == (0, 0)


async def test_a_lock_writes_one_audit_entry_naming_the_person(signin: SignInRig) -> None:
    # F10: a lock goes unrecorded, or is recorded once per wrong password after it.
    email = f"audited@{signin.zone}"
    user = await signin.person(email)
    codes = [(await _sign_in(signin, email, WRONG)).status_code for _ in range(7)]
    assert codes == [401, 401, 401, 401, 429, 429, 429], codes
    a = audit_entries.c
    q = sa.select(a.tenant_id, a.team_id, a.actor, a.target_kind, a.detail).where(
        a.action == "signin.locked", a.target_id == user
    )
    async with signin.engine.connect() as c:
        found = (await c.execute(q)).all()
    assert len(found) == 1, found
    tenant, team, actor, kind, detail = found[0]
    assert (tenant, team, actor, kind) == (signin.tenant, None, user, "user")
    assert sorted(detail) == ["failures", "until"] and detail["failures"] == 5, detail
