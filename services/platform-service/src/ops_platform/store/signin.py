"""Sign-in data: a workspace's providers and domains, provider identities, sign-in flows, password credentials and
reset tokens (migration 0010).

A domain listed on a provider is this workspace's claim, with a token it publishes in DNS; it routes sign-in and makes
people only once verified (0017, c-195). Another workspace's pending claim blocks nobody, and the unique index on
verified domains decides between two workspaces verifying the same one.

The lookups that come before the tenant is known (an email domain, a flow by its state or handoff hash, a reset by
its token hash) call the SECURITY DEFINER functions of 0010 in `system_tx`; everything after runs in `tenant_tx`. Each
single-use thing (a flow's answer, its handoff, a reset token) is spent by a conditional update, so two requests racing
on one cannot both win. A first SSO sign-in finds or makes the person inside one transaction, and the unique index on
(provider, subject) decides a race between two first sign-ins.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy import Row
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.ids import new_id
from ops_store import Guarantee

from .audit import record
from .roles import mirror_membership
from .tables import (
    members,
    password_credentials,
    password_resets,
    sessions,
    signin_domains,
    signin_email_failures,
    signin_flows,
    signin_identities,
    signin_lockouts,
    signin_providers,
    teams,
    users,
)
from .tenancy import RESET_LOOKUP, SIGNIN_LOCKOUT, SIGNIN_LOOKUP, TenantDb
from .workspace import default_team_in, security_team_in

PASSWORD = "password"


@dataclass(frozen=True)
class DomainClaim:
    """A domain this workspace listed: the token it publishes as a TXT record, and when that record was seen."""

    domain: str
    provider_id: str
    token: str
    verified_at: str | None


@dataclass(frozen=True)
class Provider:
    id: str
    tenant_id: str
    kind: str
    label: str
    enabled: bool
    config: dict[str, Any]
    jit_team_id: str | None
    jit_role: str | None
    domains: list[str] = field(default_factory=list[str])
    claims: list[DomainClaim] = field(default_factory=list[DomainClaim])

    @property
    def verified_domains(self) -> set[str]:
        return {c.domain for c in self.claims if c.verified_at}


@dataclass(frozen=True)
class DomainHit:
    """What an email domain signs in to: its workspace, the SSO provider the domain names, and whether that workspace
    allows a password."""

    tenant_id: str
    provider_id: str
    kind: str
    label: str
    enabled: bool
    password_enabled: bool


@dataclass(frozen=True)
class Flow:
    id: str
    tenant_id: str
    provider_id: str
    purpose: str
    browser_hash: str
    verifier: str | None
    nonce: str | None
    request_id: str | None
    next_path: str | None
    session_id: str | None
    user_id: str | None
    created_at: str
    expires_at: str


@dataclass(frozen=True)
class SsoPerson:
    """Who a provider's answer resolved to, and whether they were made by this sign-in."""

    user_id: str
    created: bool


class DomainTakenError(Exception):
    """Another workspace has verified the domain."""


class DomainListedError(Exception):
    """The domain is on another provider of this workspace."""


class SignInStore:
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION, Guarantee.RLS})

    def __init__(self, db: TenantDb, *, security_team: str) -> None:
        self.db = db
        self.security_team = security_team

    # ── Providers and domains ──

    async def domain(self, domain: str) -> DomainHit | None:
        q = sa.text(
            "SELECT tenant_id, provider_id, kind, label, enabled, password_enabled FROM platform_signin_domain(:d)"
        )
        async with self.db.system_tx(SIGNIN_LOOKUP) as c:
            row = (await c.execute(q, {"d": domain.strip().lower()})).first()
        return (
            DomainHit(str(row[0]), str(row[1]), str(row[2]), str(row[3]), bool(row[4]), bool(row[5])) if row else None
        )

    async def providers(self, tenant_id: str) -> list[Provider]:
        async with self.db.tenant_tx(tenant_id) as c:
            return await _providers(c)

    async def provider(self, tenant_id: str, provider_id: str) -> Provider | None:
        async with self.db.tenant_tx(tenant_id) as c:
            found = await _providers(c, provider_id)
        return found[0] if found else None

    async def password_allowed(self, tenant_id: str) -> bool:
        """A workspace with no enabled provider signs in by password, so turning its only SSO provider off never locks
        everyone out; once any provider is enabled, only an enabled password row allows it. Read inside the caller's
        own check, never cached."""
        async with self.db.tenant_tx(tenant_id) as c:
            kinds = (await c.execute(sa.select(signin_providers.c.kind, signin_providers.c.enabled))).all()
        return _password_on(kinds)

    async def save_provider(self, p: Provider, *, actor: str, at: str, request_id: str) -> None:
        """Creates or replaces the provider and its domains, audited, in one transaction."""
        values = {
            "kind": p.kind,
            "label": p.label,
            "enabled": p.enabled,
            "config": p.config,
            "jit_team_id": p.jit_team_id,
            "jit_role": p.jit_role,
            "updated_at": at,
        }
        try:
            async with self.db.tenant_tx(p.tenant_id) as c:
                done = await c.execute(signin_providers.update().where(signin_providers.c.id == p.id).values(**values))
                if done.rowcount == 0:
                    await c.execute(
                        signin_providers.insert().values(id=p.id, tenant_id=p.tenant_id, created_at=at, **values)
                    )
                await _keep_claims(c, p, at)
                await record(
                    c,
                    tenant_id=p.tenant_id,
                    team_id=None,
                    actor=actor,
                    action="signin.provider_saved",
                    target_kind="signin_provider",
                    target_id=p.id,
                    request_id=request_id,
                    detail={"kind": p.kind, "enabled": p.enabled, "domains": sorted(p.domains)},
                )
        except IntegrityError as e:
            if "ux_signin_domains_verified" in str(e.orig):
                raise DomainTakenError from e
            raise

    async def verified_elsewhere(self, tenant_id: str, domains: Sequence[str]) -> bool:
        """Whether another workspace has verified any of these domains, read through the pre-tenant lookup."""
        for d in domains:
            hit = await self.domain(d)
            if hit is not None and hit.tenant_id != tenant_id:
                return True
        return False

    async def claim(self, tenant_id: str, domain: str) -> DomainClaim | None:
        async with self.db.tenant_tx(tenant_id) as c:
            row = (
                await c.execute(
                    sa.select(
                        signin_domains.c.domain,
                        signin_domains.c.provider_id,
                        signin_domains.c.token,
                        signin_domains.c.verified_at,
                    ).where(signin_domains.c.domain == domain.strip().lower())
                )
            ).first()
        return DomainClaim(str(row[0]), str(row[1]), str(row[2]), row[3]) if row else None

    async def mark_verified(self, tenant_id: str, domain: str, *, actor: str, at: str, request_id: str) -> None:
        """Marks this workspace's claim verified, audited. DomainTakenError when another workspace verified it first;
        the DNS answer is read before, outside the transaction."""
        try:
            async with self.db.tenant_tx(tenant_id) as c:
                await c.execute(
                    signin_domains.update()
                    .where(signin_domains.c.domain == domain, signin_domains.c.verified_at.is_(None))
                    .values(verified_at=at)
                )
                await record(
                    c,
                    tenant_id=tenant_id,
                    team_id=None,
                    actor=actor,
                    action="signin.domain_verified",
                    target_kind="signin_domain",
                    target_id=domain,
                    request_id=request_id,
                    detail={},
                )
        except IntegrityError as e:
            if "ux_signin_domains_verified" in str(e.orig):
                raise DomainTakenError from e
            raise

    async def delete_provider(self, tenant_id: str, provider_id: str, *, actor: str, at: str, request_id: str) -> bool:
        async with self.db.tenant_tx(tenant_id) as c:
            await c.execute(signin_flows.delete().where(signin_flows.c.provider_id == provider_id))
            await c.execute(signin_identities.delete().where(signin_identities.c.provider_id == provider_id))
            await c.execute(signin_domains.delete().where(signin_domains.c.provider_id == provider_id))
            gone = await c.execute(signin_providers.delete().where(signin_providers.c.id == provider_id))
            if gone.rowcount != 1:
                return False
            await record(
                c,
                tenant_id=tenant_id,
                team_id=None,
                actor=actor,
                action="signin.provider_deleted",
                target_kind="signin_provider",
                target_id=provider_id,
                request_id=request_id,
                detail={},
            )
        return True

    async def team_exists(self, tenant_id: str, team_id: str) -> bool:
        async with self.db.tenant_tx(tenant_id) as c:
            return (await c.execute(sa.select(teams.c.id).where(teams.c.id == team_id))).first() is not None

    # ── Passwords ──

    async def password_hash(self, tenant_id: str, user_id: str) -> str | None:
        q = sa.select(password_credentials.c.hash).where(password_credentials.c.user_id == user_id)
        async with self.db.tenant_tx(tenant_id) as c:
            return (await c.execute(q)).scalar()

    async def set_password(self, tenant_id: str, user_id: str, encoded: str, *, at: str) -> None:
        async with self.db.tenant_tx(tenant_id) as c:
            await _set_password(c, tenant_id, user_id, encoded, at)

    # ── Wrong passwords (c-196) ──

    async def locked_until(self, tenant_id: str, user_id: str, *, now: str) -> str | None:
        """When the person's lock ends, while it lasts; None when they are not locked."""
        async with self.db.tenant_tx(tenant_id) as c:
            until = (
                await c.execute(sa.select(signin_lockouts.c.locked_until).where(signin_lockouts.c.user_id == user_id))
            ).scalar()
        return str(until) if until and str(until) > now else None

    async def count_failure(
        self,
        tenant_id: str,
        user_id: str,
        *,
        at: str,
        window_start: str,
        max_failures: int,
        lock_until: str,
        request_id: str,
    ) -> bool:
        """Counts one wrong password in a single upsert, so two at once count as two; a count from before
        `window_start` starts again at one. Reaching `max_failures` locks the person until `lock_until`, audited, and
        starts the count again. Returns whether this wrong password locked them."""
        t = signin_lockouts
        stale = t.c.first_failed_at < window_start
        async with self.db.tenant_tx(tenant_id) as c:
            row = (
                await c.execute(
                    insert(t)
                    .values(tenant_id=tenant_id, user_id=user_id, failures=1, first_failed_at=at)
                    .on_conflict_do_update(
                        index_elements=[t.c.tenant_id, t.c.user_id],
                        set_={
                            "failures": sa.case((stale, 1), else_=t.c.failures + 1),
                            "first_failed_at": sa.case((stale, at), else_=t.c.first_failed_at),
                        },
                    )
                    .returning(t.c.failures)
                )
            ).scalar_one()
            if row < max_failures:
                return False
            await c.execute(
                t.update().where(t.c.user_id == user_id).values(locked_until=lock_until, failures=0, first_failed_at=at)
            )
            await record(
                c,
                tenant_id=tenant_id,
                team_id=None,
                actor=user_id,
                action="signin.locked",
                target_kind="user",
                target_id=user_id,
                request_id=request_id,
                detail={"until": lock_until, "failures": row},
            )
        return True

    async def email_locked_until(self, email_hash: str, *, now: str) -> str | None:
        """When sign-in for this address stops refusing, while it is locked; None when it is not."""
        t = signin_email_failures
        async with self.db.system_tx(SIGNIN_LOCKOUT) as c:
            until = (await c.execute(sa.select(t.c.locked_until).where(t.c.email_hash == email_hash))).scalar()
        return str(until) if until and str(until) > now else None

    async def count_email_failure(
        self, email_hash: str, *, at: str, window_start: str, max_failures: int, lock_until: str
    ) -> bool:
        """Counts one wrong password for an address in one upsert, as `count_failure` does for a person, whether or
        not the address has an account. Returns whether this one locked it."""
        t = signin_email_failures
        stale = t.c.first_failed_at < window_start
        async with self.db.system_tx(SIGNIN_LOCKOUT) as c:
            failures = (
                await c.execute(
                    insert(t)
                    .values(email_hash=email_hash, failures=1, first_failed_at=at)
                    .on_conflict_do_update(
                        index_elements=[t.c.email_hash],
                        set_={
                            "failures": sa.case((stale, 1), else_=t.c.failures + 1),
                            "first_failed_at": sa.case((stale, at), else_=t.c.first_failed_at),
                        },
                    )
                    .returning(t.c.failures)
                )
            ).scalar_one()
            if failures < max_failures:
                return False
            await c.execute(
                t.update()
                .where(t.c.email_hash == email_hash)
                .values(locked_until=lock_until, failures=0, first_failed_at=at)
            )
        return True

    async def clear_email_failures(self, email_hash: str) -> None:
        async with self.db.system_tx(SIGNIN_LOCKOUT) as c:
            await c.execute(signin_email_failures.delete().where(signin_email_failures.c.email_hash == email_hash))

    async def clear_failures(self, tenant_id: str, user_id: str) -> None:
        async with self.db.tenant_tx(tenant_id) as c:
            await c.execute(signin_lockouts.delete().where(signin_lockouts.c.user_id == user_id))

    async def resets_since(self, tenant_id: str, user_id: str, since: str) -> int:
        """Reset links sent to the person since `since`."""
        async with self.db.tenant_tx(tenant_id) as c:
            q = sa.select(sa.func.count()).where(
                password_resets.c.user_id == user_id, password_resets.c.created_at >= since
            )
            return int((await c.execute(q)).scalar_one())

    async def open_reset(self, tenant_id: str, user_id: str, *, token_hash: str, at: str, expires_at: str) -> None:
        async with self.db.tenant_tx(tenant_id) as c:
            await c.execute(
                password_resets.insert().values(
                    id=new_id("prs"),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    token_hash=token_hash,
                    created_at=at,
                    expires_at=expires_at,
                )
            )

    async def use_reset(self, token_hash: str, encoded: str, *, at: str, request_id: str) -> tuple[str, str] | None:
        """Spends the reset token, sets the new password and ends every session of the person, in one transaction.
        Returns (tenant, user), or None when the token is unknown, used or expired."""
        async with self.db.system_tx(RESET_LOOKUP) as c:
            row = (
                await c.execute(sa.text("SELECT id, tenant_id FROM platform_password_reset(:h)"), {"h": token_hash})
            ).first()
        if row is None:
            return None
        reset_id, tenant_id = str(row[0]), str(row[1])
        async with self.db.tenant_tx(tenant_id) as c:
            # The workspace may have turned passwords off since the link was sent.
            kinds = (await c.execute(sa.select(signin_providers.c.kind, signin_providers.c.enabled))).all()
            if not _password_on(kinds):
                return None
            spent = await c.execute(
                password_resets.update()
                .where(
                    password_resets.c.id == reset_id,
                    password_resets.c.used_at.is_(None),
                    password_resets.c.expires_at > at,
                )
                .values(used_at=at)
            )
            if spent.rowcount != 1:
                return None
            user_id = str(
                (
                    await c.execute(sa.select(password_resets.c.user_id).where(password_resets.c.id == reset_id))
                ).scalar_one()
            )
            await _set_password(c, tenant_id, user_id, encoded, at)
            # A new password ends a lock from wrong ones (c-196).
            await c.execute(signin_lockouts.delete().where(signin_lockouts.c.user_id == user_id))
            await c.execute(
                sessions.update()
                .where(sessions.c.user_id == user_id, sessions.c.revoked_at.is_(None))
                .values(revoked_at=at)
            )
            await record(
                c,
                tenant_id=tenant_id,
                team_id=None,
                actor=user_id,
                action="auth.password_reset",
                target_kind="user",
                target_id=user_id,
                request_id=request_id,
                detail={},
            )
        return tenant_id, user_id

    # ── Flows ──

    async def open_flow(
        self,
        *,
        tenant_id: str,
        provider_id: str,
        purpose: str,
        state_hash: str,
        browser_hash: str,
        at: str,
        expires_at: str,
        verifier: str | None = None,
        nonce: str | None = None,
        request_id: str | None = None,
        next_path: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        flow_id = new_id("flw")
        async with self.db.tenant_tx(tenant_id) as c:
            await c.execute(
                signin_flows.insert().values(
                    id=flow_id,
                    tenant_id=tenant_id,
                    provider_id=provider_id,
                    purpose=purpose,
                    state_hash=state_hash,
                    browser_hash=browser_hash,
                    verifier=verifier,
                    nonce=nonce,
                    request_id=request_id,
                    next_path=next_path,
                    session_id=session_id,
                    user_id=user_id,
                    created_at=at,
                    expires_at=expires_at,
                )
            )
        return flow_id

    async def flow_by_state(self, state_hash: str) -> Flow | None:
        return await self._flow("platform_signin_flow", state_hash)

    async def flow_by_handoff(self, handoff_hash: str) -> Flow | None:
        return await self._flow("platform_signin_handoff", handoff_hash)

    async def _flow(self, function: str, value: str) -> Flow | None:
        async with self.db.system_tx(SIGNIN_LOOKUP) as c:
            row = (await c.execute(sa.text(f"SELECT id, tenant_id FROM {function}(:v)"), {"v": value})).first()
        if row is None:
            return None
        cols = signin_flows.c
        q = sa.select(
            cols.id,
            cols.tenant_id,
            cols.provider_id,
            cols.purpose,
            cols.browser_hash,
            cols.verifier,
            cols.nonce,
            cols.request_id,
            cols.next_path,
            cols.session_id,
            cols.user_id,
            cols.created_at,
            cols.expires_at,
        ).where(cols.id == str(row[0]))
        async with self.db.tenant_tx(str(row[1])) as c:
            found = (await c.execute(q)).first()
        return Flow(*found) if found else None

    async def answer(self, flow: Flow, *, user_id: str, handoff_hash: str, at: str) -> bool:
        """Records who the provider vouched for and the handoff code, once, while the flow lives."""
        q = (
            signin_flows.update()
            .where(signin_flows.c.id == flow.id, signin_flows.c.answered_at.is_(None), signin_flows.c.expires_at > at)
            .values(user_id=user_id, handoff_hash=handoff_hash, answered_at=at)
        )
        async with self.db.tenant_tx(flow.tenant_id) as c:
            return (await c.execute(q)).rowcount == 1

    async def take(self, flow: Flow, *, browser_hash: str, at: str) -> bool:
        """Spends the handoff, once, for the browser that started the flow, while the flow lives."""
        q = (
            signin_flows.update()
            .where(
                signin_flows.c.id == flow.id,
                signin_flows.c.used_at.is_(None),
                signin_flows.c.answered_at.is_not(None),
                signin_flows.c.browser_hash == browser_hash,
                signin_flows.c.expires_at > at,
            )
            .values(used_at=at)
        )
        async with self.db.tenant_tx(flow.tenant_id) as c:
            return (await c.execute(q)).rowcount == 1

    # ── People behind an SSO answer ──

    async def linked(self, tenant_id: str, provider_id: str, subject: str) -> str | None:
        """The active person a provider subject is linked to."""
        q = (
            sa.select(signin_identities.c.user_id)
            .join(users, users.c.id == signin_identities.c.user_id)
            .where(
                signin_identities.c.provider_id == provider_id,
                signin_identities.c.subject == subject,
                users.c.status == "active",
            )
        )
        async with self.db.tenant_tx(tenant_id) as c:
            return (await c.execute(q)).scalar()

    async def resolve(
        self,
        p: Provider,
        *,
        subject: str,
        email: str,
        name: str,
        at: str,
        request_id: str,
        groups: tuple[str, ...] = (),
    ) -> SsoPerson | None:
        """The person this provider subject is: the one it is linked to; else the workspace's person with that email,
        now linked; else, when the provider gives new people a role, a new person in its JIT team (or the workspace's
        default team, c-202) with that role. A person is linked or made only for an email on one of the provider's
        domains. Then each of the provider's group mappings the person's groups match adds the mapped membership they
        lack. None: nobody may sign in as this answer."""
        try:
            return await self._resolve(
                p, subject=subject, email=email, name=name, at=at, request_id=request_id, groups=groups
            )
        except IntegrityError:
            # Another first sign-in for this subject or email committed between our read and our insert.
            found = await self.linked(p.tenant_id, p.id, subject)
            return SsoPerson(found, False) if found else None

    async def _resolve(
        self,
        p: Provider,
        *,
        subject: str,
        email: str,
        name: str,
        at: str,
        request_id: str,
        groups: tuple[str, ...],
    ) -> SsoPerson | None:
        async with self.db.tenant_tx(p.tenant_id) as c:
            person = await self._person(c, p, subject=subject, email=email, name=name, at=at, request_id=request_id)
            if person is not None:
                await self._join_groups(c, p, person.user_id, email, groups, at=at, request_id=request_id)
        return person

    async def _person(
        self, c: AsyncConnection, p: Provider, *, subject: str, email: str, name: str, at: str, request_id: str
    ) -> SsoPerson | None:
        row = (
            await c.execute(
                sa.select(signin_identities.c.id, signin_identities.c.user_id, users.c.status)
                .join(users, users.c.id == signin_identities.c.user_id)
                .where(signin_identities.c.provider_id == p.id, signin_identities.c.subject == subject)
            )
        ).first()
        if row is not None:
            if row[2] != "active":
                return None
            await c.execute(signin_identities.update().where(signin_identities.c.id == row[0]).values(last_used_at=at))
            return SsoPerson(str(row[1]), False)
        if email.rpartition("@")[2] not in p.verified_domains:
            return None
        existing = (
            await c.execute(sa.select(users.c.id, users.c.status).where(sa.func.lower(users.c.email) == email.lower()))
        ).first()
        created = False
        jit_team = (p.jit_team_id or await default_team_in(c, p.tenant_id)) if p.jit_role else None
        if existing is not None:
            if existing[1] != "active":
                return None
            user_id = str(existing[0])
        elif jit_team and p.jit_role:
            user_id, created = new_id("usr"), True
            await c.execute(
                users.insert().values(
                    id=user_id, tenant_id=p.tenant_id, email=email, name=name, status="active", created_at=at
                )
            )
            await self._add_member(
                c, p, user_id, email, team=jit_team, role=p.jit_role, at=at, request_id=request_id, why="jit"
            )
        else:
            return None
        await c.execute(
            signin_identities.insert().values(
                id=new_id("sid"),
                tenant_id=p.tenant_id,
                provider_id=p.id,
                subject=subject,
                user_id=user_id,
                created_at=at,
                last_used_at=at,
            )
        )
        return SsoPerson(user_id, created)

    async def _join_groups(
        self,
        c: AsyncConnection,
        p: Provider,
        user_id: str,
        email: str,
        groups: tuple[str, ...],
        *,
        at: str,
        request_id: str,
    ) -> None:
        """Adds the membership of each group rule the person's groups match, when they have none in that team yet.
        A membership already there keeps its role; losing a group removes nothing (provisioning's job, c-155)."""
        settings: dict[str, Any] = p.config.get("groups") or {}
        rules: list[dict[str, Any]] = settings.get("map") or []
        held = set(groups)
        for rule in rules:
            team, role = str(rule["team"]), str(rule["role"])
            if str(rule["group"]) not in held:
                continue
            current = (
                await c.execute(
                    sa.select(members.c.id, members.c.status).where(
                        members.c.team_id == team, members.c.user_id == user_id
                    )
                )
            ).first()
            if current is not None and current[1] == "active":
                continue
            active_team = (
                await c.execute(sa.select(teams.c.id).where(teams.c.id == team, teams.c.status == "active"))
            ).first()
            if active_team is None:
                continue
            if current is not None:
                await c.execute(members.delete().where(members.c.id == current[0]))
            await self._add_member(
                c, p, user_id, email, team=team, role=role, at=at, request_id=request_id, why="group"
            )

    async def _add_member(
        self,
        c: AsyncConnection,
        p: Provider,
        user_id: str,
        email: str,
        *,
        team: str,
        role: str,
        at: str,
        request_id: str,
        why: str,
    ) -> None:
        member_id = new_id("mem")
        await c.execute(
            members.insert().values(
                id=member_id,
                tenant_id=p.tenant_id,
                team_id=team,
                user_id=user_id,
                email=email,
                role=role,
                status="active",
                created_at=at,
                updated_at=at,
            )
        )
        await mirror_membership(
            c,
            tenant_id=p.tenant_id,
            team_id=team,
            user_id=user_id,
            member_role=role,
            security_team=await security_team_in(c, p.tenant_id, self.security_team),
            granted_by=f"signin:{p.id}",
            at=at,
        )
        await record(
            c,
            tenant_id=p.tenant_id,
            team_id=team,
            actor=user_id,
            action="member.jit" if why == "jit" else "member.group",
            target_kind="member",
            target_id=member_id,
            request_id=request_id,
            detail={"email": email, "role": role, "provider": p.id},
        )


async def _providers(c: AsyncConnection, provider_id: str | None = None) -> list[Provider]:
    q = sa.select(signin_providers).order_by(signin_providers.c.created_at, signin_providers.c.id)
    if provider_id is not None:
        q = q.where(signin_providers.c.id == provider_id)
    rows = (await c.execute(q)).mappings().all()
    claims: dict[str, list[DomainClaim]] = {}
    listed = sa.select(
        signin_domains.c.domain, signin_domains.c.provider_id, signin_domains.c.token, signin_domains.c.verified_at
    ).order_by(signin_domains.c.domain)
    for d, pid, token, verified_at in (await c.execute(listed)).all():
        claims.setdefault(str(pid), []).append(DomainClaim(str(d), str(pid), str(token), verified_at))
    return [
        Provider(
            id=str(r["id"]),
            tenant_id=str(r["tenant_id"]),
            kind=str(r["kind"]),
            label=str(r["label"]),
            enabled=bool(r["enabled"]),
            config=dict(r["config"] or {}),
            jit_team_id=r["jit_team_id"],
            jit_role=r["jit_role"],
            domains=[x.domain for x in claims.get(str(r["id"]), [])],
            claims=claims.get(str(r["id"]), []),
        )
        for r in rows
    ]


async def _keep_claims(c: AsyncConnection, p: Provider, at: str) -> None:
    """Makes the provider's claims the listed domains: a new one gets a token and waits for verification, one this
    workspace already holds keeps its token and verification, and one no longer listed goes. A domain on another of
    the workspace's providers is refused."""
    listed = sorted({d.strip().lower() for d in p.domains})
    held = {
        str(d): str(pid)
        for d, pid in (
            await c.execute(
                sa.select(signin_domains.c.domain, signin_domains.c.provider_id).where(
                    signin_domains.c.domain.in_(listed)
                )
            )
        ).all()
    }
    await c.execute(
        signin_domains.delete().where(signin_domains.c.provider_id == p.id, signin_domains.c.domain.not_in(listed))
    )
    for d in listed:
        if d not in held:
            await c.execute(
                signin_domains.insert().values(
                    domain=d, tenant_id=p.tenant_id, provider_id=p.id, created_at=at, token=secrets.token_urlsafe(24)
                )
            )
        elif held[d] != p.id:
            # One provider per domain: moving it is removing it from the other provider first, on purpose.
            raise DomainListedError(d)


def _password_on(kinds: Sequence[Row[Any, Any]]) -> bool:
    enabled = [str(row[0]) for row in kinds if row[1]]
    return not enabled or PASSWORD in enabled


async def _set_password(c: AsyncConnection, tenant_id: str, user_id: str, encoded: str, at: str) -> None:
    done = await c.execute(
        password_credentials.update()
        .where(password_credentials.c.user_id == user_id)
        .values(hash=encoded, updated_at=at)
    )
    if done.rowcount == 0:
        await c.execute(
            password_credentials.insert().values(user_id=user_id, tenant_id=tenant_id, hash=encoded, updated_at=at)
        )
