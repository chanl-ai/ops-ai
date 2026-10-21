# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Storage settings at rest (c-100): one versioned document per tenant, the tenant's storage credentials as
ciphertext only, and an audit row for every change, written in the same transaction as the change.

The document is JSON kept as text and never queried (database portability D5): files-service reads it whole. A save
names the version it was made from and is refused when another save got there first."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_files.store.files import ROLE, files, metadata
from ops_store import isolation
from ops_store.schema import TENANT_SCOPED
from ops_store.team_scope import any_team

# Why the storage settings check reads every team's files: a target any team's files are stored on stays.
STORAGE_TARGETS = "storage_targets"

storage_settings = sa.Table(
    "storage_settings",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("document", sa.Text, nullable=False),
    sa.Column("updated_by", sa.String(320), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    # Workspace-level: the tenant's storage, changed by an admin under can() (c-415).
    info=TENANT_SCOPED,
)

storage_credentials = sa.Table(
    "storage_credentials",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("name", sa.String(64), primary_key=True),
    sa.Column("kind", sa.String(32), nullable=False),
    # AES-256-GCM ciphertext (ops_files.secrets); never a value.
    sa.Column("sealed", sa.Text, nullable=False),
    sa.Column("set_by", sa.String(320), nullable=False),
    sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
    info=TENANT_SCOPED,
)

storage_settings_audit = sa.Table(
    "storage_settings_audit",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("action", sa.String(32), nullable=False),  # settings_saved | credential_set | credential_deleted
    sa.Column("subject", sa.String(64), nullable=False),
    # What changed, in words; a credential is named here, never valued.
    sa.Column("detail", sa.Text, nullable=False),
    sa.Column("actor", sa.String(320), nullable=False),
    sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_storage_settings_audit_tenant", "tenant_id", "at"),
    info=TENANT_SCOPED,
)


class StaleVersionError(Exception):
    """The save was made from a version another save has replaced."""


@dataclass(frozen=True)
class SavedSettings:
    version: int
    document: dict[str, Any]
    updated_by: str
    updated_at: datetime


@dataclass(frozen=True)
class CredentialRow:
    name: str
    kind: str
    sealed: str
    set_by: str
    set_at: datetime


class SettingsStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def get(self) -> SavedSettings | None:
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            row = (
                (await c.execute(sa.select(storage_settings).where(storage_settings.c.tenant_id == tenant)))
                .mappings()
                .first()
            )
        if row is None:
            return None
        return SavedSettings(row["version"], json.loads(row["document"]), row["updated_by"], row["updated_at"])

    async def save(
        self, *, base_version: int, document: dict[str, Any], by: str, at: datetime, detail: str
    ) -> SavedSettings:
        """Writes version `base_version + 1`; `base_version` 0 is the first save. Refused when it is not current."""
        tenant = isolation.tenant()
        text = json.dumps(document, sort_keys=True)
        try:
            async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                if base_version == 0:
                    exists = (
                        await c.execute(
                            sa.select(storage_settings.c.version).where(storage_settings.c.tenant_id == tenant)
                        )
                    ).first()
                    if exists is not None:
                        raise StaleVersionError(f"version {exists[0]} is saved; reload and save again")
                    await c.execute(
                        storage_settings.insert().values(
                            tenant_id=tenant, version=1, document=text, updated_by=by, updated_at=at
                        )
                    )
                else:
                    done = await c.execute(
                        storage_settings.update()
                        .where(storage_settings.c.tenant_id == tenant, storage_settings.c.version == base_version)
                        .values(version=base_version + 1, document=text, updated_by=by, updated_at=at)
                    )
                    if done.rowcount != 1:
                        raise StaleVersionError(f"version {base_version} is no longer current; reload and save again")
                await self._audit(
                    c, tenant, action="settings_saved", subject=f"v{base_version + 1}", detail=detail, actor=by, at=at
                )
        except IntegrityError as e:
            # Two first saves at once: the second insert meets the first's row (the tenant is the key).
            raise StaleVersionError("another save got there first; reload and save again") from e
        return SavedSettings(base_version + 1, document, by, at)

    async def locations_in_use(self) -> set[tuple[str, str]]:
        """The (backend, container) pairs the tenant's files are stored in, every team's; a save may not drop a target
        on one."""
        with isolation.tenant_wide(STORAGE_TARGETS):
            tenant = isolation.tenant()
            where = (files.c.tenant_id == tenant, any_team(files, "a target any team's files are on stays"))
            q = sa.select(files.c.storage_backend, files.c.storage_container).where(*where).distinct()
            async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                return {(str(r[0]), str(r[1])) for r in await c.execute(q)}

    async def credentials(self) -> list[CredentialRow]:
        tenant = isolation.tenant()
        q = (
            sa.select(storage_credentials)
            .where(storage_credentials.c.tenant_id == tenant)
            .order_by(storage_credentials.c.name)
        )
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            return [
                CredentialRow(r["name"], r["kind"], r["sealed"], r["set_by"], r["set_at"])
                for r in (await c.execute(q)).mappings()
            ]

    async def credential(self, name: str) -> CredentialRow | None:
        return next((r for r in await self.credentials() if r.name == name), None)

    async def put_credential(self, name: str, *, kind: str, sealed: str, by: str, at: datetime) -> None:
        """Sets or replaces a credential: delete then insert in one transaction, so no dialect's upsert is needed."""
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            where = (storage_credentials.c.tenant_id == tenant) & (storage_credentials.c.name == name)
            replaced = (await c.execute(storage_credentials.delete().where(where))).rowcount
            await c.execute(
                storage_credentials.insert().values(
                    tenant_id=tenant, name=name, kind=kind, sealed=sealed, set_by=by, set_at=at
                )
            )
            detail = f"{'replaced' if replaced else 'added'} {kind} credential {name}"
            await self._audit(
                c,
                tenant,
                action="credential_set",
                subject=name,
                detail=detail,
                actor=by,
                at=at,
            )

    async def delete_credential(self, name: str, *, by: str, at: datetime) -> bool:
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            where = (storage_credentials.c.tenant_id == tenant) & (storage_credentials.c.name == name)
            gone = (await c.execute(storage_credentials.delete().where(where))).rowcount == 1
            if gone:
                await self._audit(
                    c,
                    tenant,
                    action="credential_deleted",
                    subject=name,
                    detail=f"deleted credential {name}",
                    actor=by,
                    at=at,
                )
        return gone

    async def audit(self) -> list[dict[str, Any]]:
        tenant = isolation.tenant()
        q = (
            sa.select(storage_settings_audit)
            .where(storage_settings_audit.c.tenant_id == tenant)
            .order_by(storage_settings_audit.c.id)
        )
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    @staticmethod
    async def _audit(
        c: AsyncConnection, tenant: str, *, action: str, subject: str, detail: str, actor: str, at: datetime
    ) -> None:
        await c.execute(
            storage_settings_audit.insert().values(
                tenant_id=tenant, action=action, subject=subject, detail=detail, actor=actor, at=at
            )
        )
