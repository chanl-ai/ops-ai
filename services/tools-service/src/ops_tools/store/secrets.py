"""Tool secrets at rest: only the credential store's reference to each value (`ops_policy.credentials`), never a
value, and an audit row for every create, rotate, rename, delete and use, written in the same transaction as the
change it records. Values are put and read through `secrets.SecretResolver`; this store keeps the reference opaque."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.http import Out
from ops_store import Guarantee, background
from ops_store.dialect import locked
from ops_store.rows import rows
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.search import contains
from ops_store.store import Store
from ops_store.team_scope import team_visible

from .modules import metadata
from .tenancy import ROLE, SYSTEM_ROLE

_TS = sa.DateTime(timezone=True)

tool_secrets = sa.Table(
    "tool_secrets",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    # The team whose tool modules and connections read it: two teams that call the same system each hold their
    # own row under the same name, so a module installed in both resolves `{{NAME}}` to its own team's value.
    sa.Column("team_id", sa.String(64), primary_key=True),
    # ^[A-Z][A-Z0-9_]*$, the name a `{{NAME}}` reference uses.
    sa.Column("name", sa.String(120), primary_key=True),
    # The credential store's reference to the value: the sealed value itself with the row-sealed adapter, a
    # vault's secret id with a vault adapter. Read and written only through the credential store.
    sa.Column("ciphertext", sa.Text, nullable=False),
    # Rises on every rotation, so a reader can tell which value a call used.
    sa.Column("version", sa.Integer, nullable=False),
    # The value's last four characters, shown so a person can tell which value is held (secrets.ending); null for a
    # short value, whose ending would give too much away.
    sa.Column("ends", sa.String(4)),
    sa.Column("created_by", sa.String(200), nullable=False),
    sa.Column("created_at", _TS, nullable=False),
    sa.Column("rotated_at", _TS),
    sa.Column("last_used_at", _TS),
    # The template slot a provisioned record fills, found again by it on the next run, and what a person may change:
    # `system` nothing, `managed` anything. Null on a record no template made.
    sa.Column("template_id", sa.String(120), index=True),
    sa.Column("protection", sa.String(16)),
    # The connection whose secret part this is; written through the connection, listed as belonging to it,
    # never rotated or deleted on its own. Null for a secret a person added on the Secrets page.
    sa.Column("connection_id", sa.String(64)),
    # The team's app credential whose client secret this is: changed with the credential under Credentials, never on
    # its own, and not listed as a value tools reference. Null for every other secret.
    sa.Column("credential_id", sa.String(64)),
    # Held to its team by the database: only a transaction run as ROLE in the row's team reads it.
    info={**TENANT_SCOPED, **TEAM_OWNED},
)
secret_audit = sa.Table(
    "secret_audit",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("name", sa.String(120), nullable=False),
    sa.Column("action", sa.String(16), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("actor", sa.String(200), nullable=False),
    # For a use: the tool whose call sent the value.
    sa.Column("tool", sa.String(120)),
    sa.Column("at", _TS, nullable=False),
    # The retention sweep deletes by age across tenants.
    sa.Index("ix_secret_audit_at", "at"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


# How long a secret's use and change rows are kept: the sweep deletes older ones, every tenant's, as the system role.
AUDIT_KEPT_S = 90 * 86400.0


# Why the sweep deletes across tenants: rows of every team pass their age on one clock.
class SecretMeta(Out):
    """A team secret as listed: everything but the value's reference."""

    tenant_id: str
    team_id: str
    name: str
    version: int
    ends: str | None
    created_by: str
    created_at: datetime
    rotated_at: datetime | None
    last_used_at: datetime | None
    template_id: str | None
    protection: str | None
    connection_id: str | None
    credential_id: str | None


class SecretChange(Out):
    """One audit row: a secret created, rotated, renamed, deleted or used."""

    id: int
    tenant_id: str
    team_id: str
    name: str
    action: str
    version: int
    actor: str
    tool: str | None
    at: datetime


_META = [c for c in tool_secrets.c if c.name != "ciphertext"]

AUDIT_RETENTION = "the retention sweep deletes every tenant's secret use rows past their age"


async def _sweep_audit(conn: AsyncConnection, now: float) -> int:
    """One pass: deletes the rows older than AUDIT_KEPT_S. `at` is a timestamp, so the cutoff is one too."""
    cutoff = datetime.fromtimestamp(now - AUDIT_KEPT_S, UTC)
    gone = await conn.execute(secret_audit.delete().where(secret_audit.c.at < cutoff))
    return int(gone.rowcount or 0)


AUDIT_SWEEP = background.register(
    background.Process(
        "tools_secret_audit_retention",
        "tools",
        "Retention of secret_audit",
        f"Deletes secret use and change rows older than {AUDIT_KEPT_S / 86400:g} days.",
        background.RETENTION_EVERY_S,
        "Rows of every team pass their date on one clock; the sweep deletes them as the service's system role.",
        sweep=_sweep_audit,
    )
).key


def _of(tenant_id: str, team_id: str) -> sa.ColumnElement[bool]:
    return sa.and_(tool_secrets.c.tenant_id == tenant_id, tool_secrets.c.team_id == team_id)


class SecretStore(Store):
    """Every read and write names one team (`team_id`): no method reads or changes another team's rows."""

    # A change and its audit row land together (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})
    # Every transaction runs as ROLE carrying the caller's tenant and team, so the database shows this team's rows
    # only; NoTenantError before any connection when the caller set none.
    role = ROLE
    system_role = SYSTEM_ROLE

    async def _audit(self, c: AsyncConnection, tenant_id: str, team_id: str, change: dict[str, Any]) -> None:
        await c.execute(secret_audit.insert().values(tenant_id=tenant_id, team_id=team_id, **change))

    async def listed(self, tenant_id: str, team_id: str) -> list[SecretMeta]:
        """The team's secrets' metadata; the ciphertext is not selected."""
        q = sa.select(*_META).where(_of(tenant_id, team_id)).order_by(tool_secrets.c.name)
        async with self.tx() as c:
            return await rows(c, q, SecretMeta)

    async def page(
        self,
        tenant_id: str,
        team_id: str,
        search: str,
        *,
        offset: int,
        limit: int,
        template_id: str | None = None,
    ) -> list[SecretMeta]:
        """One page of the team's secrets whose name contains `search`, by name, leaving out accounts' secret parts;
        the ciphertext is not selected, and LIMIT and OFFSET run in the query."""
        q = (
            sa.select(*_META)
            .where(self._matching(tenant_id, team_id, search, template_id))
            .order_by(sa.func.lower(tool_secrets.c.name))
        )
        async with self.tx() as c:
            return await rows(c, q.offset(offset).limit(limit), SecretMeta)

    async def count(self, tenant_id: str, team_id: str, search: str, template_id: str | None = None) -> int:
        q = (
            sa.select(sa.func.count())
            .select_from(tool_secrets)
            .where(self._matching(tenant_id, team_id, search, template_id), team_visible(tool_secrets))
        )
        async with self.tx() as c:
            return int((await c.execute(q)).scalar_one())

    @staticmethod
    def _matching(tenant_id: str, team_id: str, search: str, template_id: str | None = None) -> sa.ColumnElement[bool]:
        # An account's secret parts (an API key, a password) are its sign-in, kept and changed on the account, so the
        # Secrets list leaves them out. An auth config's client secret is listed, read only, with its config.
        named = sa.and_(
            _of(tenant_id, team_id),
            tool_secrets.c.connection_id.is_(None),
            contains(tool_secrets.c.name, search),
        )
        return named if template_id is None else sa.and_(named, tool_secrets.c.template_id == template_id)

    async def create(
        self,
        tenant_id: str,
        team_id: str,
        name: str,
        ref: str,
        *,
        actor: str,
        at: datetime,
        ends: str | None = None,
        template: dict[str, str] | None = None,
        connection_id: str | None = None,
        credential_id: str | None = None,
    ) -> bool:
        """False when the team already has the name (nothing written). `template` carries the provisioner's
        `template_id` and `protection`; `connection_id` marks a connection's secret part, and
        `credential_id` an app credential's client secret."""
        row = {"tenant_id": tenant_id, "team_id": team_id, "name": name, "ciphertext": ref, "version": 1, "ends": ends}
        if connection_id is not None:
            row["connection_id"] = connection_id
        if credential_id is not None:
            row["credential_id"] = credential_id
        row |= template or {}
        async with self.tx() as c:
            try:
                async with self.attempt(c):
                    await c.execute(tool_secrets.insert().values(**row, created_by=actor, created_at=at))
            except IntegrityError:
                return False
            change = {"name": name, "action": "created", "version": 1, "actor": actor, "at": at}
            await self._audit(c, tenant_id, team_id, change)
        return True

    async def missing_ends(self, tenant_id: str, team_id: str, name: str) -> str | None:
        """The reference of a secret kept before its last four characters were, so they can be read once and kept;
        None once it has them or when the team has no such secret."""
        q = sa.select(tool_secrets.c.ciphertext).where(
            _of(tenant_id, team_id),
            tool_secrets.c.name == name,
            tool_secrets.c.ends.is_(None),
            team_visible(tool_secrets),
        )
        async with self.tx() as c:
            found = (await c.execute(q)).first()
        return str(found.ciphertext) if found else None

    async def keep_ends(self, tenant_id: str, team_id: str, name: str, ref: str, ends: str) -> None:
        """Keeps the last four characters read from `ref`, unless the secret was replaced since."""
        q = (
            tool_secrets.update()
            .where(_of(tenant_id, team_id), tool_secrets.c.name == name, tool_secrets.c.ciphertext == ref)
            .values(ends=ends)
        )
        async with self.tx() as c:
            await c.execute(q)

    async def rotate(
        self, tenant_id: str, team_id: str, name: str, ref: str, *, actor: str, at: datetime, ends: str | None = None
    ) -> tuple[int, str] | None:
        """The new version and the reference it replaced, or None when the team has no such secret. The row is locked
        while it is read, so two rotations each hand back the reference they replaced and none is lost."""
        mine = sa.and_(_of(tenant_id, team_id), tool_secrets.c.name == name)
        async with self.tx() as c:
            read = sa.select(tool_secrets.c.ciphertext).where(mine, team_visible(tool_secrets))
            found = (await c.execute(locked(read, tool_secrets))).first()
            if found is None:
                return None
            q = (
                tool_secrets.update()
                .where(mine)
                .values(ciphertext=ref, version=tool_secrets.c.version + 1, rotated_at=at, ends=ends)
                .returning(tool_secrets.c.version)
            )
            version = int((await c.execute(q)).scalar_one())
            change = {"name": name, "action": "rotated", "version": version, "actor": actor, "at": at}
            await self._audit(c, tenant_id, team_id, change)
            return version, str(found.ciphertext)

    async def ref(self, tenant_id: str, team_id: str, name: str) -> str | None:
        """The reference of the team's secret of that name, or None; reading it is not a use, so it is not audited."""
        q = sa.select(tool_secrets.c.ciphertext).where(
            _of(tenant_id, team_id), tool_secrets.c.name == name, team_visible(tool_secrets)
        )
        async with self.tx() as c:
            found = (await c.execute(q)).first()
        return str(found.ciphertext) if found else None

    async def rename(
        self, tenant_id: str, team_id: str, name: str, to: str, ref: str, *, was: str, actor: str, at: datetime
    ) -> bool | None:
        """Gives the secret the name `to` and the reference `ref` (its value sealed under the new name), only while it
        still holds `was`. None when it is gone or was replaced meanwhile; False when the team already has `to`."""
        async with self.tx() as c:
            try:
                async with self.attempt(c):
                    q = (
                        tool_secrets.update()
                        .where(_of(tenant_id, team_id), tool_secrets.c.name == name, tool_secrets.c.ciphertext == was)
                        .values(name=to, ciphertext=ref)
                        .returning(tool_secrets.c.version)
                    )
                    version = (await c.execute(q)).scalar_one_or_none()
            except IntegrityError:
                return False
            if version is None:
                return None
            change = {"name": to, "action": "renamed", "version": int(version), "actor": actor, "at": at}
            await self._audit(c, tenant_id, team_id, change)
        return True

    async def delete(self, tenant_id: str, team_id: str, name: str, *, actor: str, at: datetime) -> str | None:
        """The deleted value's reference, or None when the team has no such secret."""
        async with self.tx() as c:
            q = (
                tool_secrets.delete()
                .where(_of(tenant_id, team_id), tool_secrets.c.name == name)
                .returning(tool_secrets.c.version, tool_secrets.c.ciphertext)
            )
            gone = (await c.execute(q)).first()
            if gone is None:
                return None
            change = {"name": name, "action": "deleted", "version": gone.version, "actor": actor, "at": at}
            await self._audit(c, tenant_id, team_id, change)
            return str(gone.ciphertext)

    async def use(
        self, tenant_id: str, team_id: str, names: list[str], *, actor: str, tool: str, at: datetime, audit: bool = True
    ) -> dict[str, tuple[str, int]]:
        """The reference and version of each named secret the team has, recording the use of each in one
        transaction. Read on every call, never cached, so a rotation applies to the next call. `audit` False is a
        poller's read (a mailbox read every few seconds): its time of use is kept, with no audit row per poll."""
        if not names:
            return {}
        async with self.tx() as c:
            q = sa.select(tool_secrets.c.name, tool_secrets.c.ciphertext, tool_secrets.c.version).where(
                _of(tenant_id, team_id), tool_secrets.c.name.in_(names), team_visible(tool_secrets)
            )
            found = {r.name: (r.ciphertext, int(r.version)) for r in await c.execute(q)}
            if found:
                await c.execute(
                    tool_secrets.update()
                    .where(_of(tenant_id, team_id), tool_secrets.c.name.in_(list(found)))
                    .values(last_used_at=at)
                )
            for name, (_, version) in found.items() if audit else ():
                change = {"name": name, "action": "used", "version": version, "actor": actor, "tool": tool, "at": at}
                await self._audit(c, tenant_id, team_id, change)
        return found

    async def audit(self, tenant_id: str, team_id: str) -> list[SecretChange]:
        mine = (secret_audit.c.tenant_id == tenant_id, secret_audit.c.team_id == team_id, team_visible(secret_audit))
        q = secret_audit.select().where(*mine).order_by(secret_audit.c.id)
        async with self.tx() as c:
            return await rows(c, q, SecretChange)
