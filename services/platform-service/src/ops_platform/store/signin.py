"""Sign-in data: a workspace's providers and domains, provider identities, sign-in flows, password credentials and
reset tokens (migration 0010).

A domain listed on a provider is this workspace's claim, with a token it publishes in DNS; it routes sign-in and makes
people only once verified (0017). Another workspace's pending claim blocks nobody, and the unique index on
verified domains decides between two workspaces verifying the same one.

The lookups that come before the tenant is known (an email domain, a flow by its state or handoff hash, a reset by
its token hash) call the lookup functions (`lookups.py`) in `system_tx`; everything after runs in `tenant_tx`. Each
single-use thing (a flow's answer, its handoff, a reset token) is spent by a conditional update, so two requests racing
on one cannot both win. A first SSO sign-in finds or makes the person inside one transaction, and the unique index on
(provider, subject) decides a race between two first sign-ins.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, NotRequired, TypedDict

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_access import MEMBER_ROLES_BY_RANK
from ops_service_kit import narrow
from ops_service_kit.http import Json, Out
from ops_service_kit.ids import new_id
from ops_store import Guarantee
from ops_store.dialect import insert_ignore
from ops_store.documents import StoredShapeError, stored
from ops_store.rows import one, rows

from .audit import record, record_grants_ending
from .lookups import (
    PASSWORD_RESET,
    SIGNIN_DOMAIN,
    SIGNIN_FLOW,
    SIGNIN_HANDOFF,
    SIGNIN_SP,
    WATCHED_PROVIDERS,
    Lookup,
    lookup,
)
from .members import Actor, accept_invite_on, end_membership, use_link_invite_on
from .roles import holds_admin, mirror_membership
from .tables import (
    members,
    password_credentials,
    password_resets,
    sessions,
    signin_break_glass,
    signin_certificates,
    signin_domains,
    signin_email_failures,
    signin_flows,
    signin_grants,
    signin_group_rules,
    signin_identities,
    signin_lockouts,
    signin_providers,
    teams,
    tenants,
    users,
)
from .tenancy import RESET_LOOKUP, SIGNIN_LOCKOUT, SIGNIN_LOOKUP, SIGNIN_WATCH, TenantDb
from .workspace import default_team_in, security_team_in

PASSWORD = "password"
# The membership roles a provider may give, lowest first: the catalogue's rank without its top, admin, which a provider
# never gives (decision D5). When two group rules give one team, the higher role wins.
SIGNIN_ROLES = MEMBER_ROLES_BY_RANK[:-1]


@dataclass(frozen=True)
class DomainClaim:
    """A domain this workspace listed: the token it publishes as a TXT record, and when that record was seen."""

    domain: str
    provider_id: str
    token: str
    verified_at: str | None


@dataclass(frozen=True)
class TrustedCertificate:
    """A signing certificate a provider is trusted with, and where it came from."""

    fingerprint: str
    pem: str
    not_before: str
    not_after: str
    source: str
    added_at: str
    warned: str | None = None


class GroupsConfig(TypedDict, total=False):
    """A provider's group settings: `source` (the claim or attribute read, null for the default `groups`) and
    `onMissing` (keep | remove; absent on a provider saved before the choice existed)."""

    source: str | None
    onMissing: str | None


class ProviderConfig(TypedDict, total=False):
    """A provider's stored `config`: the OIDC or the SAML settings an admin saved, with no key for a null. Every key is
    optional because a password provider stores `{}` and older rows lack the later keys; a key not named here (an
    older row's group `map`) is kept as stored."""

    # OIDC
    issuer: str
    clientId: str
    clientSecretRef: str
    scopes: list[str]
    # SAML: the newest certificate still in its dates, for a console that reads one (the trusted ones are rows).
    idpEntityId: str
    ssoUrl: str
    certificate: str
    metadataUrl: str
    metadataReadAt: str
    # Null after a metadata read that went right.
    metadataError: str | None
    emailAttribute: str
    nameAttribute: str
    signRequests: bool
    requireEncryption: bool
    tiles: bool
    # Null is never written; it reads as no group settings.
    groups: GroupsConfig | None


# What a save writes is checked against the shape before it is stored.
PROVIDER_CONFIG = stored(ProviderConfig)


def config_view(value: object) -> ProviderConfig:
    """A stored config as the settings pages read it: the stored document when it fits the shape, else the same
    document without the declared keys whose value has another type. A row an older release wrote with a wrong type
    still lists, saves over and deletes, so an admin can repair it; a sign-in reads the stored document itself through
    OIDC_SIGN_IN or SAML_SIGN_IN and fails on that type. A document that is not an object fails here as it did."""
    try:
        return PROVIDER_CONFIG(value)
    except StoredShapeError:
        document = narrow.an_object(value, "a sign-in provider's config")
    fits: Json = {}
    for key, held in document.items():
        try:
            PROVIDER_CONFIG({key: held})
        except StoredShapeError:
            continue
        fits[key] = held
    return PROVIDER_CONFIG(fits)


class OidcSignIn(TypedDict):
    """The stored settings an OIDC sign-in uses; a missing required key or another type fails the sign-in."""

    issuer: str
    clientId: str
    clientSecretRef: NotRequired[str | None]
    scopes: NotRequired[list[str] | None]


class SamlSignIn(TypedDict):
    """The stored settings a SAML sign-in uses. `signRequests` and `requireEncryption` are not declared: they are
    read as truthy or not, whatever their stored type."""

    idpEntityId: str
    ssoUrl: str
    certificate: NotRequired[str | None]
    emailAttribute: NotRequired[str | None]
    nameAttribute: NotRequired[str | None]


# Read where a sign-in starts, so a provider missing one of these keys fails the sign-in instead of starting it.
OIDC_SIGN_IN = stored(OidcSignIn)
SAML_SIGN_IN = stored(SamlSignIn)


def group_settings(config: ProviderConfig) -> GroupsConfig:
    """A provider's group settings: `source` (the claim or attribute read) and `onMissing` (keep | remove)."""
    return config.get("groups") or {}


class BreakGlassRow(Out):
    """A person on the break-glass list; `last_used_at` is None until they sign in with it."""

    user_id: str
    email: str
    added_by: str
    added_at: str
    last_used_at: str | None


class _TestResult(Out):
    test_result: dict[str, JsonValue] | None
    answered_at: str | None


@dataclass(frozen=True)
class GroupRule:
    """A person the provider names in `group` gets `role` in `team`."""

    group: str
    team: str
    role: str
    id: str = ""


@dataclass(frozen=True)
class Provider:
    id: str
    tenant_id: str
    kind: str
    label: str
    enabled: bool
    # The settings pages' view (`config_view`); `stored` is the document as stored, which a sign-in reads.
    config: ProviderConfig
    stored: Json
    jit_team_id: str | None
    jit_role: str | None
    domains: list[str] = field(default_factory=list[str])
    claims: list[DomainClaim] = field(default_factory=list[DomainClaim])
    # The random id in this provider's own SAML addresses; None for one saved before providers had them.
    sp_id: str | None = None
    # Its trusted signing certificates, not removed, newest end date first (SAML only).
    certificates: list[TrustedCertificate] = field(default_factory=list[TrustedCertificate])
    group_rules: list[GroupRule] = field(default_factory=list[GroupRule])

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
class SpHit:
    """The provider a SAML address names, found before its tenant is known."""

    tenant_id: str
    provider_id: str
    kind: str
    enabled: bool
    tiles: bool


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
    subject: str | None = None
    invite_hash: str | None = None


class LinkRequired(Exception):
    """The provider's email belongs to a person already here, and nothing but that email says this is them: they link
    the provider from their own signed-in session, or sign in from their invite."""


class AlreadyLinked(Exception):
    """The provider subject is linked to someone, or the person already has a subject at this provider."""


@dataclass(frozen=True)
class SsoPerson:
    """Who a provider's answer resolved to, and whether they were made by this sign-in."""

    user_id: str
    created: bool


class DomainTakenError(Exception):
    """Another workspace has verified the domain."""


class DomainListedError(Exception):
    """The domain is on another provider of this workspace."""


async def _count_one(
    c: AsyncConnection, t: sa.Table, start: dict[str, str | int], *, keys: list[str], window_start: str
) -> int:
    """Adds one wrong password to the row `keys` name and returns the count; a count from before `window_start` starts
    again at one. The row is made first if there is none (`start`, at zero); one UPDATE counts, so two at once wait on
    the row's lock and both count. A right password or a reset may delete the row between the two statements: the
    count then starts again, as it would have after that delete."""
    at = start["first_failed_at"]
    stale = t.c.first_failed_at < window_start
    counted = (
        t.update()
        .where(*[t.c[k] == start[k] for k in keys])
        .values(
            failures=sa.case((stale, 1), else_=t.c.failures + 1),
            first_failed_at=sa.case((stale, at), else_=t.c.first_failed_at),
        )
        .returning(t.c.failures)
    )
    for _ in range(3):
        await c.execute(insert_ignore(c, t, start, keys=keys))
        failures = (await c.execute(counted)).scalar_one_or_none()
        if failures is not None:
            return int(failures)
    raise RuntimeError(f"{t.name}: the count's row was deleted three times while counting")


class SignInStore(TenantDb):
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION, Guarantee.RLS})

    # ── Providers and domains ──

    async def domain(self, domain: str) -> DomainHit | None:
        async with self.system_tx(SIGNIN_LOOKUP) as c:
            found = await lookup(c, SIGNIN_DOMAIN, domain.strip().lower())
        if not found:
            return None
        row = found[0]
        return DomainHit(str(row[0]), str(row[1]), str(row[2]), str(row[3]), bool(row[4]), bool(row[5]))

    async def sp(self, sp_id: str) -> SpHit | None:
        """The provider whose own SAML addresses carry `sp_id`, through the pre-tenant lookup."""
        async with self.system_tx(SIGNIN_LOOKUP) as c:
            found = await lookup(c, SIGNIN_SP, sp_id)
        if not found:
            return None
        row = found[0]
        return SpHit(str(row[0]), str(row[1]), str(row[2]), bool(row[3]), bool(row[4]))

    async def providers(self, tenant_id: str) -> list[Provider]:
        async with self.tenant_tx(tenant_id) as c:
            return await _providers(c)

    async def provider(self, tenant_id: str, provider_id: str) -> Provider | None:
        async with self.tenant_tx(tenant_id) as c:
            found = await _providers(c, provider_id)
        return found[0] if found else None

    async def password_allowed(self, tenant_id: str) -> bool:
        """A workspace with no enabled provider signs in by password, so turning its only SSO provider off never locks
        everyone out; once any provider is enabled, only an enabled password row allows it. Read inside the caller's
        own check, never cached."""
        async with self.tenant_tx(tenant_id) as c:
            kinds = (await c.execute(sa.select(signin_providers.c.kind, signin_providers.c.enabled))).all()
        return _password_on(kinds)

    async def save_provider(
        self,
        p: Provider,
        *,
        actor: str,
        at: str,
        request_id: str,
        certificates: Sequence[TrustedCertificate] | None = None,
        rules: Sequence[GroupRule] | None = None,
    ) -> None:
        """Creates or replaces the provider and its domains, audited, in one transaction. `certificates`, when given,
        are the ones the admin saved: listed ones are kept or added; an uploaded or typed one no longer listed is
        removed; one read from metadata stays until it ends or an admin removes it, so a bad metadata read never
        locks people out."""
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
            async with self.tenant_tx(p.tenant_id) as c:
                done = await c.execute(signin_providers.update().where(signin_providers.c.id == p.id).values(**values))
                if done.rowcount == 0:
                    await c.execute(
                        signin_providers.insert().values(
                            id=p.id, tenant_id=p.tenant_id, created_at=at, sp_id=p.sp_id, **values
                        )
                    )
                await _keep_claims(c, p, at)
                if certificates is not None:
                    await _keep_certificates(c, p, certificates, actor=actor, at=at, request_id=request_id)
                if rules is not None:
                    await _keep_rules(c, p, rules, actor=actor, at=at)
                await record(
                    c,
                    tenant_id=p.tenant_id,
                    team_id=None,
                    actor=actor,
                    action="signin.provider_saved",
                    target_kind="signin_provider",
                    target_id=p.id,
                    request_id=request_id,
                    detail={"kind": p.kind, "enabled": p.enabled, "domains": [*sorted(p.domains)]},
                )
        except IntegrityError as e:
            if "ux_signin_domains_verified" in str(e.orig):
                raise DomainTakenError from e
            raise

    async def add_certificates(
        self, p: Provider, certificates: Sequence[TrustedCertificate], *, at: str, request_id: str
    ) -> list[TrustedCertificate]:
        """Adds the certificates the provider is not yet trusted with (a metadata refresh), each audited; returns
        the ones added."""
        async with self.tenant_tx(p.tenant_id) as c:
            return await _add_certificates(c, p, certificates, actor="system", at=at, request_id=request_id)

    async def metadata_read(self, p: Provider, *, at: str, error: str | None) -> None:
        """Records when the provider's metadata URL was last read and what was wrong with it, if anything."""
        config: Json = {**p.stored, "metadataReadAt": at, "metadataError": error}
        async with self.tenant_tx(p.tenant_id) as c:
            await c.execute(
                signin_providers.update().where(signin_providers.c.id == p.id).values(config=config, updated_at=at)
            )

    async def mark_warned(self, tenant_id: str, provider_id: str, fingerprint: str, level: str) -> None:
        q = (
            signin_certificates.update()
            .where(signin_certificates.c.provider_id == provider_id, signin_certificates.c.fingerprint == fingerprint)
            .values(warned=level)
        )
        async with self.tenant_tx(tenant_id) as c:
            await c.execute(q)

    async def watched(self) -> list[tuple[str, str]]:
        """(tenant, provider) of every SAML provider of an open workspace, for the daily certificate watch."""
        async with self.system_tx(SIGNIN_WATCH) as c:
            rows = await lookup(c, WATCHED_PROVIDERS)
        return [(str(r[0]), str(r[1])) for r in rows]

    async def verified_elsewhere(self, tenant_id: str, domains: Sequence[str]) -> bool:
        """Whether another workspace has verified any of these domains, read through the pre-tenant lookup."""
        for d in domains:
            hit = await self.domain(d)
            if hit is not None and hit.tenant_id != tenant_id:
                return True
        return False

    async def claim(self, tenant_id: str, domain: str) -> DomainClaim | None:
        async with self.tenant_tx(tenant_id) as c:
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
            async with self.tenant_tx(tenant_id) as c:
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
        async with self.tenant_tx(tenant_id) as c:
            await c.execute(signin_certificates.delete().where(signin_certificates.c.provider_id == provider_id))
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

    # ── Break-glass ──

    async def break_glass(self, tenant_id: str) -> list[BreakGlassRow]:
        """The people on the break-glass list, with their email; whether each still counts is the caller's check."""
        b = signin_break_glass.c
        q = (
            sa.select(b.user_id, users.c.email, b.added_by, b.added_at, b.last_used_at)
            .join(users, sa.and_(users.c.id == b.user_id, users.c.status == "active"))
            .order_by(b.added_at)
        )
        async with self.tenant_tx(tenant_id) as c:
            return await rows(c, q, BreakGlassRow)

    async def add_break_glass(self, tenant_id: str, user_id: str, *, actor: str, at: str, request_id: str) -> None:
        async with self.tenant_tx(tenant_id) as c:
            held = await c.execute(
                sa.select(signin_break_glass.c.user_id).where(signin_break_glass.c.user_id == user_id)
            )
            if held.first() is None:
                await c.execute(
                    signin_break_glass.insert().values(
                        tenant_id=tenant_id, user_id=user_id, added_by=actor, added_at=at
                    )
                )
            await _record_break_glass(
                c, tenant_id, user_id, "signin.break_glass_added", actor=actor, request_id=request_id
            )

    async def remove_break_glass(self, tenant_id: str, user_id: str, *, actor: str, request_id: str) -> bool:
        async with self.tenant_tx(tenant_id) as c:
            done = await c.execute(signin_break_glass.delete().where(signin_break_glass.c.user_id == user_id))
            if done.rowcount:
                await _record_break_glass(
                    c, tenant_id, user_id, "signin.break_glass_removed", actor=actor, request_id=request_id
                )
        return bool(done.rowcount)

    async def break_glass_used(self, tenant_id: str, user_id: str, *, at: str, request_id: str) -> None:
        async with self.tenant_tx(tenant_id) as c:
            await c.execute(
                signin_break_glass.update().where(signin_break_glass.c.user_id == user_id).values(last_used_at=at)
            )
            await _record_break_glass(
                c, tenant_id, user_id, "signin.break_glass_used", actor=user_id, request_id=request_id
            )

    async def team_exists(self, tenant_id: str, team_id: str) -> bool:
        async with self.tenant_tx(tenant_id) as c:
            return (await c.execute(sa.select(teams.c.id).where(teams.c.id == team_id))).first() is not None

    # ── Passwords ──

    async def password_hash(self, tenant_id: str, user_id: str) -> str | None:
        q = sa.select(password_credentials.c.hash).where(password_credentials.c.user_id == user_id)
        async with self.tenant_tx(tenant_id) as c:
            return (await c.execute(q)).scalar()

    async def set_password(self, tenant_id: str, user_id: str, encoded: str, *, at: str) -> None:
        async with self.tenant_tx(tenant_id) as c:
            await _set_password(c, tenant_id, user_id, encoded, at)

    # ── Wrong passwords ──

    async def locked_until(self, tenant_id: str, user_id: str, *, now: str) -> str | None:
        """When the person's lock ends, while it lasts; None when they are not locked."""
        async with self.tenant_tx(tenant_id) as c:
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
        async with self.tenant_tx(tenant_id) as c:
            start: dict[str, str | int] = {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "failures": 0,
                "first_failed_at": at,
            }
            row = await _count_one(c, t, start, keys=["tenant_id", "user_id"], window_start=window_start)
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
        async with self.install_tx(SIGNIN_LOCKOUT, tables=(signin_email_failures,)) as c:
            until = (await c.execute(sa.select(t.c.locked_until).where(t.c.email_hash == email_hash))).scalar()
        return str(until) if until and str(until) > now else None

    async def count_email_failure(
        self, email_hash: str, *, at: str, window_start: str, max_failures: int, lock_until: str
    ) -> bool:
        """Counts one wrong password for an address in one upsert, as `count_failure` does for a person, whether or
        not the address has an account. Returns whether this one locked it."""
        t = signin_email_failures
        async with self.install_tx(SIGNIN_LOCKOUT, tables=(signin_email_failures,)) as c:
            start: dict[str, str | int] = {"email_hash": email_hash, "failures": 0, "first_failed_at": at}
            failures = await _count_one(c, t, start, keys=["email_hash"], window_start=window_start)
            if failures < max_failures:
                return False
            await c.execute(
                t.update()
                .where(t.c.email_hash == email_hash)
                .values(locked_until=lock_until, failures=0, first_failed_at=at)
            )
        return True

    async def clear_email_failures(self, email_hash: str) -> None:
        async with self.install_tx(SIGNIN_LOCKOUT, tables=(signin_email_failures,)) as c:
            await c.execute(signin_email_failures.delete().where(signin_email_failures.c.email_hash == email_hash))

    async def clear_failures(self, tenant_id: str, user_id: str) -> None:
        async with self.tenant_tx(tenant_id) as c:
            await c.execute(signin_lockouts.delete().where(signin_lockouts.c.user_id == user_id))

    async def resets_since(self, tenant_id: str, user_id: str, since: str) -> int:
        """Reset links sent to the person since `since`."""
        async with self.tenant_tx(tenant_id) as c:
            q = sa.select(sa.func.count()).where(
                password_resets.c.user_id == user_id, password_resets.c.created_at >= since
            )
            return int((await c.execute(q)).scalar_one())

    async def open_reset(self, tenant_id: str, user_id: str, *, token_hash: str, at: str, expires_at: str) -> None:
        async with self.tenant_tx(tenant_id) as c:
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
        async with self.system_tx(RESET_LOOKUP) as c:
            found = await lookup(c, PASSWORD_RESET, token_hash)
        if not found:
            return None
        reset_id, tenant_id = str(found[0][0]), str(found[0][1])
        async with self.tenant_tx(tenant_id) as c:
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
            # A new password ends a lock from wrong ones.
            await c.execute(signin_lockouts.delete().where(signin_lockouts.c.user_id == user_id))
            await record_grants_ending(
                c, tenant_id=tenant_id, user_id=user_id, actor=user_id, by="password_reset", request_id=request_id
            )
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
        invite_hash: str | None = None,
    ) -> str:
        flow_id = new_id("flw")
        async with self.tenant_tx(tenant_id) as c:
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
                    invite_hash=invite_hash,
                    created_at=at,
                    expires_at=expires_at,
                )
            )
        return flow_id

    async def flow_by_state(self, state_hash: str) -> Flow | None:
        return await self._flow(SIGNIN_FLOW, state_hash)

    async def flow_by_handoff(self, handoff_hash: str) -> Flow | None:
        return await self._flow(SIGNIN_HANDOFF, handoff_hash)

    async def _flow(self, by: Lookup, value: str) -> Flow | None:
        async with self.system_tx(SIGNIN_LOOKUP) as c:
            found = await lookup(c, by, value)
        if not found:
            return None
        row = found[0]
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
            cols.subject,
            cols.invite_hash,
        ).where(cols.id == str(row[0]))
        async with self.tenant_tx(str(row[1])) as c:
            found = (await c.execute(q)).first()
        return Flow(*found) if found else None

    async def answer(self, flow: Flow, *, user_id: str, handoff_hash: str, at: str, subject: str | None = None) -> bool:
        """Records who the provider vouched for and the handoff code, once, while the flow lives; a link flow also
        keeps the provider's subject for its complete step."""
        q = (
            signin_flows.update()
            .where(signin_flows.c.id == flow.id, signin_flows.c.answered_at.is_(None), signin_flows.c.expires_at > at)
            .values(user_id=user_id, handoff_hash=handoff_hash, answered_at=at, subject=subject)
        )
        async with self.tenant_tx(flow.tenant_id) as c:
            return (await c.execute(q)).rowcount == 1

    async def record_test(self, flow: Flow, result: dict[str, JsonValue], *, at: str) -> bool:
        """Keeps a test flow's result, once and before it expires. Sets no handoff, so no session can follow."""
        async with self.tenant_tx(flow.tenant_id) as c:
            done = await c.execute(
                signin_flows.update()
                .where(
                    signin_flows.c.id == flow.id,
                    signin_flows.c.purpose == "test",
                    signin_flows.c.answered_at.is_(None),
                    signin_flows.c.expires_at > at,
                )
                .values(test_result=result, answered_at=at)
            )
        return bool(done.rowcount)

    async def test_result(self, tenant_id: str, flow_id: str, user_id: str) -> dict[str, JsonValue] | None:
        """A test flow's result for the admin who started it: `waiting` until the provider answers."""
        f = signin_flows.c
        q = sa.select(f.test_result, f.answered_at).where(f.id == flow_id, f.purpose == "test", f.user_id == user_id)
        async with self.tenant_tx(tenant_id) as c:
            row = await one(c, q, _TestResult)
        if row is None:
            return None
        return row.test_result or {"state": "waiting"}

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
        async with self.tenant_tx(flow.tenant_id) as c:
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
        async with self.tenant_tx(tenant_id) as c:
            return (await c.execute(q)).scalar()

    async def linked_at(self, tenant_id: str, provider_id: str, user_id: str) -> str | None:
        """When the person's link to this provider was made; None when they have none."""
        q = sa.select(signin_identities.c.created_at).where(
            signin_identities.c.provider_id == provider_id, signin_identities.c.user_id == user_id
        )
        async with self.tenant_tx(tenant_id) as c:
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
        groups: tuple[str, ...] | None = None,
        email_verified: bool = False,
        invite_hash: str | None = None,
    ) -> SsoPerson | None:
        """The person this provider subject is: the one it is linked to; else, from a pending invite to this email
        that the provider vouched for (`email_verified` on OIDC), the invited person, now linked and a member;
        else, when the email is nobody's yet and the provider gives new people a role, a new person in its JIT team
        (or the workspace's default team) with that role. A person is linked or made only for an email on one of the
        provider's domains. Then the provider's group rules are applied (`_join_groups`). None: nobody may sign in as
        this answer. Raises `LinkRequired` when the email is an existing person's and no invite says it is them."""
        async with self.tenant_tx(p.tenant_id) as c:
            try:
                async with self.attempt(c):
                    person = await self._person(
                        c,
                        p,
                        subject=subject,
                        email=email,
                        name=name,
                        at=at,
                        request_id=request_id,
                        vouched=email_verified or p.kind != "oidc",
                        invite_hash=invite_hash,
                    )
                    if person is not None:
                        await self._join_groups(c, p, person.user_id, email, groups, at=at, request_id=request_id)
                    return person
            except IntegrityError:
                # Another first sign-in for this subject or email committed between our read and our insert; this
                # one's writes are rolled back to the savepoint and the person is read as that one made them.
                pass
        found = await self.linked(p.tenant_id, p.id, subject)
        return SsoPerson(found, False) if found else None

    async def _person(
        self,
        c: AsyncConnection,
        p: Provider,
        *,
        subject: str,
        email: str,
        name: str,
        at: str,
        request_id: str,
        vouched: bool,
        invite_hash: str | None,
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
        how = "jit"
        jit_team = (p.jit_team_id or await default_team_in(c, p.tenant_id)) if p.jit_role else None
        invite = await _invite(c, invite_hash, email, at) if invite_hash else None
        if existing is not None:
            if existing[1] != "active" or await holds_admin(c, p.tenant_id, str(existing[0])):
                # An admin links from their own signed-in session, never by an email the provider asserts: whoever
                # controls the provider could otherwise sign in as any admin on a verified domain.
                return None
            user_id, how = str(existing[0]), "invite"
            # The email alone never opens an existing person's account: anyone who can be given that address at the
            # provider, or a provider that never checked it, would sign in as them. Only a link invite on their own
            # membership does, mailed to that address, so it needs no email_verified; it changes no role.
            actor = Actor(p.tenant_id, invite.team_id, user_id, request_id) if invite else None
            if (
                invite is None
                or actor is None
                or invite.user_id != user_id
                or not await use_link_invite_on(c, actor, invite.member_id, email, at=at, via=p.id)
            ):
                raise LinkRequired
        elif invite is not None and invite.user_id is None and vouched:
            user_id, created, how = new_id("usr"), True, "invite"
            await c.execute(
                users.insert().values(
                    id=user_id, tenant_id=p.tenant_id, email=email, name=name, status="active", created_at=at
                )
            )
            actor = Actor(p.tenant_id, invite.team_id, user_id, request_id)
            if not await accept_invite_on(c, actor, invite.member_id, invite.role, email, at=at, via=p.id):
                raise LinkRequired  # rolls back the person made above
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
        await _link(c, p, user_id, subject, email=email, how=how, at=at, request_id=request_id)
        return SsoPerson(user_id, created)

    async def unlink(
        self,
        tenant_id: str,
        user_id: str,
        *,
        actor: str,
        team_id: str | None,
        at: str,
        request_id: str,
        provider_id: str | None = None,
    ) -> int:
        """Removes the person's provider links (one provider's, or all), each audited with its subject, and ends the
        sessions they signed in with through those providers, so a link removed after a takeover stops working at once.
        Returns how many links went."""
        q = sa.select(signin_identities.c.id, signin_identities.c.provider_id, signin_identities.c.subject).where(
            signin_identities.c.user_id == user_id
        )
        if provider_id is not None:
            q = q.where(signin_identities.c.provider_id == provider_id)
        async with self.tenant_tx(tenant_id) as c:
            gone = (await c.execute(q)).all()
            if not gone:
                return 0
            await c.execute(signin_identities.delete().where(signin_identities.c.id.in_([str(r[0]) for r in gone])))
            await c.execute(
                sessions.update()
                .where(
                    sessions.c.user_id == user_id,
                    sessions.c.provider_id.in_({str(r[1]) for r in gone}),
                    sessions.c.revoked_at.is_(None),
                )
                .values(revoked_at=at)
            )
            for _, provider, subject in gone:
                await record(
                    c,
                    tenant_id=tenant_id,
                    team_id=team_id,
                    actor=actor,
                    action="signin.unlink",
                    target_kind="user",
                    target_id=user_id,
                    request_id=request_id,
                    detail={"provider": str(provider), "subject": str(subject)},
                )
        return len(gone)

    async def link(self, p: Provider, user_id: str, subject: str, *, email: str, at: str, request_id: str) -> None:
        """Links the provider subject to `user_id`, the person of the signed-in session that started the link.
        Raises AlreadyLinked when the subject is someone's, or the person already has one at this provider."""
        async with self.tenant_tx(p.tenant_id) as c:
            active = await c.execute(sa.select(users.c.id).where(users.c.id == user_id, users.c.status == "active"))
            if active.first() is None:
                raise AlreadyLinked
            try:
                async with self.attempt(c):
                    await _link(c, p, user_id, subject, email=email, how="session", at=at, request_id=request_id)
            except IntegrityError as e:
                raise AlreadyLinked from e

    async def _join_groups(
        self,
        c: AsyncConnection,
        p: Provider,
        user_id: str,
        email: str,
        groups: tuple[str, ...] | None,
        *,
        at: str,
        request_id: str,
    ) -> None:
        """Gives the person each membership their groups map to, at the highest role any matching rule gives in that
        team. A membership given by hand or by a first sign-in is left as it is. With `onMissing` remove, a membership
        only groups gave, in a team none of their groups maps to now, ends, so an empty list ends every one. An
        unknown list (None, as from Entra's overage claim) changes nothing: it does not say the person left a group."""
        if groups is None:
            return
        held = set(groups)
        wanted: dict[str, tuple[str, list[str]]] = {}
        for rule in p.group_rules:
            if rule.group not in held:
                continue
            role, ids = wanted.get(rule.team, (rule.role, []))
            if SIGNIN_ROLES.index(rule.role) > SIGNIN_ROLES.index(role):
                role = rule.role
            wanted[rule.team] = (role, [*ids, rule.id])
        given = await _group_given(c, p.id, user_id)
        for team, (role, rule_ids) in wanted.items():
            active_team = (
                await c.execute(sa.select(teams.c.id).where(teams.c.id == team, teams.c.status == "active"))
            ).first()
            if active_team is None:
                continue
            current = (
                await c.execute(
                    sa.select(members.c.id, members.c.status, members.c.role).where(
                        members.c.team_id == team, members.c.user_id == user_id
                    )
                )
            ).first()
            if current is not None and current[1] == "active":
                member_id = str(current[0])
                if member_id not in given:
                    continue
                if current[2] != role:
                    await self._set_role(c, p, member_id, user_id, team=team, role=role, at=at)
            else:
                if current is not None:
                    await c.execute(members.delete().where(members.c.id == current[0]))
                member_id = await self._add_member(
                    c, p, user_id, email, team=team, role=role, at=at, request_id=request_id, why="group"
                )
                given[member_id] = (team, set())
            await _grant(c, p, member_id, [r for r in rule_ids if r not in given[member_id][1]], at=at)
        if group_settings(p.config).get("onMissing") != "remove":
            return
        for member_id, (team, _) in given.items():
            if team in wanted:
                continue
            await end_membership(c, Actor(p.tenant_id, team, user_id, request_id), member_id, user_id, at=at)
            await c.execute(signin_grants.delete().where(signin_grants.c.member_id == member_id))
            # An assistant connected to this team's MCP address acts in it; it ends with the membership, audited like
            # a removal by an admin. Their other teams' connections and their console sign-in stay.
            await record_grants_ending(
                c, tenant_id=p.tenant_id, user_id=user_id, actor=user_id, by="group", request_id=request_id,
                team_id=team,
            )  # fmt: skip
            await c.execute(
                sessions.update()
                .where(
                    sessions.c.user_id == user_id,
                    sessions.c.team_id == team,
                    sessions.c.kind == "mcp",
                    sessions.c.revoked_at.is_(None),
                )
                .values(revoked_at=at)
            )
            await record(
                c,
                tenant_id=p.tenant_id,
                team_id=team,
                actor=user_id,
                action="member.group_removed",
                target_kind="member",
                target_id=member_id,
                request_id=request_id,
                detail={"email": email, "provider": p.id},
            )

    async def _set_role(
        self, c: AsyncConnection, p: Provider, member_id: str, user_id: str, *, team: str, role: str, at: str
    ) -> None:
        await c.execute(members.update().where(members.c.id == member_id).values(role=role, updated_at=at))
        await mirror_membership(
            c,
            tenant_id=p.tenant_id,
            team_id=team,
            user_id=user_id,
            member_role=role,
            security_team=await security_team_in(c, p.tenant_id),
            granted_by=f"signin:{p.id}",
            at=at,
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
    ) -> str:
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
            security_team=await security_team_in(c, p.tenant_id),
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
        if why == "jit":
            await c.execute(
                signin_grants.insert().values(
                    id=new_id("sgt"), tenant_id=p.tenant_id, member_id=member_id, provider_id=p.id, why="jit",
                    granted_at=at,
                )
            )  # fmt: skip
        return member_id


@dataclass(frozen=True)
class PendingInvite:
    member_id: str
    team_id: str
    role: str
    # Set on a link invite (`TeamStore.reinvite`): the active member's own person.
    user_id: str | None


async def _invite(c: AsyncConnection, invite_hash: str, email: str, at: str) -> PendingInvite | None:
    """The pending, unexpired invite with this token hash, when it is to `email` on a domain the workspace accepts."""
    found = (
        await c.execute(
            sa.select(
                members.c.id,
                members.c.team_id,
                members.c.role,
                members.c.email,
                members.c.user_id,
                tenants.c.allowed_domains,
            )
            .join(tenants, tenants.c.id == members.c.tenant_id)
            .where(
                members.c.invite_token_hash == invite_hash,
                # An active member's row is pending only while `reinvite` has set its expiry; accepting nulls it.
                members.c.status.in_(("invited", "active")),
                members.c.invite_expires_at > at,
            )
        )
    ).first()
    if found is None or str(found[3]).lower() != email:
        return None
    domains: list[Any] = list(found[5] or [])
    allowed = {str(d).lower() for d in domains}
    if allowed and email.rpartition("@")[2] not in allowed:
        return None
    return PendingInvite(str(found[0]), str(found[1]), str(found[2]), str(found[4]) if found[4] else None)


async def _link(
    c: AsyncConnection, p: Provider, user_id: str, subject: str, *, email: str, how: str, at: str, request_id: str
) -> None:
    """The provider subject's link to the person, and its audit entry, in the caller's transaction. The unique
    constraints refuse a subject that is someone's and a second subject for the same person at this provider."""
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
    await record(
        c,
        tenant_id=p.tenant_id,
        team_id=None,
        actor=user_id,
        action="signin.link",
        target_kind="user",
        target_id=user_id,
        request_id=request_id,
        detail={"provider": p.id, "how": how, "subject": subject, "email": email},
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
    certs: dict[str, list[TrustedCertificate]] = {}
    k = signin_certificates.c
    trusted = (
        sa.select(k.provider_id, k.fingerprint, k.pem, k.not_before, k.not_after, k.source, k.added_at, k.warned)
        .where(k.removed_at.is_(None))
        .order_by(k.not_after.desc())
    )
    for pid, *rest in (await c.execute(trusted)).all():
        certs.setdefault(str(pid), []).append(TrustedCertificate(*rest))
    rules: dict[str, list[GroupRule]] = {}
    g = signin_group_rules.c
    mapped = sa.select(g.provider_id, g.group_value, g.team_id, g.role, g.id).order_by(g.created_at, g.id)
    for pid, group, team, role, rule_id in (await c.execute(mapped)).all():
        rules.setdefault(str(pid), []).append(GroupRule(str(group), str(team), str(role), str(rule_id)))
    return [
        Provider(
            id=str(r["id"]),
            tenant_id=str(r["tenant_id"]),
            kind=str(r["kind"]),
            label=str(r["label"]),
            enabled=bool(r["enabled"]),
            config=config_view(r["config"] or {}),
            stored=narrow.an_object(r["config"] or {}, "a sign-in provider's config"),
            jit_team_id=r["jit_team_id"],
            jit_role=r["jit_role"],
            domains=[x.domain for x in claims.get(str(r["id"]), [])],
            claims=claims.get(str(r["id"]), []),
            sp_id=r["sp_id"],
            certificates=certs.get(str(r["id"]), []),
            group_rules=rules.get(str(r["id"]), []),
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


async def _record_break_glass(
    c: AsyncConnection, tenant_id: str, user_id: str, action: str, *, actor: str, request_id: str
) -> None:
    await record(
        c,
        tenant_id=tenant_id,
        team_id=None,
        actor=actor,
        action=action,
        target_kind="user",
        target_id=user_id,
        request_id=request_id,
        detail={},
    )


async def _add_certificates(
    c: AsyncConnection,
    p: Provider,
    certificates: Sequence[TrustedCertificate],
    *,
    actor: str,
    at: str,
    request_id: str,
) -> list[TrustedCertificate]:
    k = signin_certificates.c
    held = {
        str(r[0]): r[1]
        for r in (await c.execute(sa.select(k.fingerprint, k.removed_at).where(k.provider_id == p.id))).all()
    }
    added: list[TrustedCertificate] = []
    for cert in certificates:
        # A refresh never brings back a certificate an admin removed; only a save by a person does.
        if cert.fingerprint in held and (held[cert.fingerprint] is None or actor == "system"):
            continue
        if cert.fingerprint in held:
            await c.execute(
                signin_certificates.update()
                .where(k.provider_id == p.id, k.fingerprint == cert.fingerprint)
                .values(removed_at=None, source=cert.source, added_at=at, added_by=actor, warned=None)
            )
        else:
            await c.execute(
                signin_certificates.insert().values(
                    tenant_id=p.tenant_id,
                    provider_id=p.id,
                    fingerprint=cert.fingerprint,
                    pem=cert.pem,
                    not_before=cert.not_before,
                    not_after=cert.not_after,
                    source=cert.source,
                    added_at=at,
                    added_by=actor,
                )
            )
        await record(
            c,
            tenant_id=p.tenant_id,
            team_id=None,
            actor=actor,
            action="signin.certificate_added",
            target_kind="signin_provider",
            target_id=p.id,
            request_id=request_id,
            detail={"fingerprint": cert.fingerprint, "notAfter": cert.not_after, "source": cert.source},
        )
        added.append(cert)
    return added


async def _keep_certificates(
    c: AsyncConnection,
    p: Provider,
    certificates: Sequence[TrustedCertificate],
    *,
    actor: str,
    at: str,
    request_id: str,
) -> None:
    k = signin_certificates.c
    listed = [x.fingerprint for x in certificates]
    await c.execute(
        signin_certificates.update()
        .where(
            k.provider_id == p.id,
            k.removed_at.is_(None),
            k.source != "metadata",
            k.fingerprint.not_in(listed),
        )
        .values(removed_at=at)
    )
    await _add_certificates(c, p, certificates, actor=actor, at=at, request_id=request_id)


async def _keep_rules(c: AsyncConnection, p: Provider, rules: Sequence[GroupRule], *, actor: str, at: str) -> None:
    """Makes the provider's group rules the listed ones. A rule still listed keeps its id, so the memberships it gave
    stay tied to it; one no longer listed goes, and what it gave counts as given by groups until the person's next
    sign-in decides."""
    g = signin_group_rules.c
    held = {
        (str(r[1]), str(r[2])): (str(r[0]), str(r[3]))
        for r in (await c.execute(sa.select(g.id, g.group_value, g.team_id, g.role).where(g.provider_id == p.id))).all()
    }
    listed = {(r.group, r.team): r.role for r in rules}
    gone = [rule_id for key, (rule_id, _) in held.items() if key not in listed]
    if gone:
        await c.execute(signin_grants.update().where(signin_grants.c.rule_id.in_(gone)).values(rule_id=None))
        await c.execute(signin_group_rules.delete().where(g.id.in_(gone)))
    for (group, team), role in listed.items():
        if (group, team) not in held:
            await c.execute(
                signin_group_rules.insert().values(
                    id=new_id("sgr"), tenant_id=p.tenant_id, provider_id=p.id, group_value=group, team_id=team,
                    role=role, created_at=at, created_by=actor,
                )
            )  # fmt: skip
        elif held[(group, team)][1] != role:
            await c.execute(signin_group_rules.update().where(g.id == held[(group, team)][0]).values(role=role))


async def _group_given(c: AsyncConnection, provider_id: str, user_id: str) -> dict[str, tuple[str, set[str]]]:
    """The person's active memberships this provider's groups gave: member id to (team, rule ids behind it)."""
    q = (
        sa.select(members.c.id, members.c.team_id, signin_grants.c.rule_id)
        .join(signin_grants, signin_grants.c.member_id == members.c.id)
        .where(
            members.c.user_id == user_id,
            members.c.status == "active",
            signin_grants.c.provider_id == provider_id,
            signin_grants.c.why == "group",
        )
    )
    found: dict[str, tuple[str, set[str]]] = {}
    for member_id, team, rule_id in (await c.execute(q)).all():
        entry = found.setdefault(str(member_id), (str(team), set[str]()))
        if rule_id is not None:
            entry[1].add(str(rule_id))
    return found


async def _grant(c: AsyncConnection, p: Provider, member_id: str, rule_ids: Sequence[str], *, at: str) -> None:
    for rule_id in rule_ids:
        await c.execute(
            signin_grants.insert().values(
                id=new_id("sgt"), tenant_id=p.tenant_id, member_id=member_id, provider_id=p.id, rule_id=rule_id,
                why="group", granted_at=at,
            )
        )  # fmt: skip


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
