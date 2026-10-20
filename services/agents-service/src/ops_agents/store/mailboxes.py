"""Team mailboxes connected on Channels > Email (c-199): what the Email received trigger watches and how it is read.
A mailbox belongs to one team of one tenant; its address is unique in the tenant, since a workflow names the mailbox it
watches by address. Credentials are never stored here: `password_secret` names a Secrets-page secret that only
tools-service reads."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar, Literal

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import Guarantee
from ops_store.schema import TENANT_SCOPED
from ops_store.search import contains

from .base import metadata
from .tenancy import current_tenant, tenant_scope, tenant_tx

Provider = Literal["gmail", "imap", "graph"]
Sender = Literal["none", "smtp", "resend", "graph"]

mailboxes = sa.Table(
    "mailboxes",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("address", sa.String(320), nullable=False),
    # gmail and imap are read over IMAP; graph by Microsoft Graph; dev is the dev stack's folder of JSON items.
    sa.Column("provider", sa.String(16), nullable=False),
    sa.Column("imap_host", sa.String(255)),
    sa.Column("imap_port", sa.Integer),
    sa.Column("imap_tls", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.Column("username", sa.String(320)),
    sa.Column("password_secret", sa.String(120)),
    sa.Column("graph_tenant_id", sa.String(64)),
    sa.Column("graph_client_id", sa.String(64)),
    sa.Column("folder", sa.String(200), nullable=False, server_default="inbox"),
    # How replies leave: none, smtp or resend, from `from_address`; the password or API key is `sender_secret`, a
    # Secrets-page secret by name (c-200). A Gmail mailbox with smtp and no host uses Gmail's SMTP server.
    sa.Column("sender", sa.String(16), nullable=False, server_default="none"),
    sa.Column("from_address", sa.String(320)),
    sa.Column("smtp_host", sa.String(255)),
    sa.Column("smtp_port", sa.Integer),
    sa.Column("smtp_starttls", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.Column("sender_secret", sa.String(120)),
    # A paused mailbox is not read; its workflows stay bound and start again when it resumes.
    sa.Column("paused", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    # A workflow names its mailbox by address, so one tenant has one mailbox per address.
    sa.UniqueConstraint("tenant_id", "address", name="uq_mailboxes_tenant_address"),
    info=TENANT_SCOPED,
)


@dataclass
class MailboxRow:
    id: str
    team_id: str
    name: str
    address: str
    provider: Provider
    imap_host: str | None = None
    imap_port: int | None = None
    imap_tls: bool = True
    username: str | None = None
    password_secret: str | None = None
    graph_tenant_id: str | None = None
    graph_client_id: str | None = None
    folder: str = "inbox"
    sender: Sender = "none"
    from_address: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_starttls: bool = True
    sender_secret: str | None = None
    paused: bool = False
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""
    tenant_id: str = field(default="")

    def values(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if k not in ("tenant_id",)}


class AddressTakenError(ValueError):
    """Another mailbox of the tenant has this address."""


def _row(r: Any) -> MailboxRow:
    return MailboxRow(**{c.name: r[c.name] for c in mailboxes.columns})


class MailboxStore:
    # One row per mailbox; the unique (tenant, address) index decides a create or address change that races (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def create(self, m: MailboxRow) -> None:
        try:
            async with tenant_tx(self.engine) as c:
                await c.execute(mailboxes.insert().values(tenant_id=current_tenant(), **m.values()))
        except IntegrityError as e:
            raise AddressTakenError(m.address) from e

    async def update(self, mailbox_id: str, values: dict[str, Any]) -> None:
        t = mailboxes
        try:
            async with tenant_tx(self.engine) as c:
                await c.execute(
                    t.update().where(t.c.tenant_id == current_tenant(), t.c.id == mailbox_id).values(**values)
                )
        except IntegrityError as e:
            raise AddressTakenError(str(values.get("address"))) from e

    async def get(self, mailbox_id: str) -> MailboxRow | None:
        t = mailboxes
        async with tenant_tx(self.engine) as c:
            r = (
                (await c.execute(t.select().where(t.c.tenant_id == current_tenant(), t.c.id == mailbox_id)))
                .mappings()
                .first()
            )
        return _row(r) if r else None

    async def by_address(self, tenant_id: str, address: str) -> MailboxRow | None:
        """The tenant's mailbox at `address`, case-insensitive. Read under that tenant's row-level security, so the
        listener, which acts outside a request, sees no other tenant's mailbox."""
        t = mailboxes
        q = t.select().where(t.c.tenant_id == tenant_id, sa.func.lower(t.c.address) == address.lower())
        with tenant_scope(tenant_id):
            async with tenant_tx(self.engine) as c:
                r = (await c.execute(q)).mappings().first()
        return _row(r) if r else None

    async def list(self, *, team: str | None, search: str = "") -> list[MailboxRow]:
        """The tenant's mailboxes, `team`'s only when given, by name."""
        t = mailboxes
        q = t.select().where(t.c.tenant_id == current_tenant())
        if team is not None:
            q = q.where(t.c.team_id == team)
        if search:
            q = q.where(sa.or_(contains(t.c.name, search), contains(t.c.address, search)))
        async with tenant_tx(self.engine) as c:
            rows = (await c.execute(q.order_by(sa.func.lower(t.c.name), t.c.id))).mappings().all()
        return [_row(r) for r in rows]

    async def drop_seeded_except(self, ids: list[str]) -> None:
        """Dev seed: removes the mailboxes an earlier seed file connected and this one no longer names, so a seeded
        mailbox can change id without its address clashing with the old row."""
        t = mailboxes
        async with tenant_tx(self.engine) as c:
            await c.execute(
                t.delete().where(t.c.tenant_id == current_tenant(), t.c.created_by == "seed", t.c.id.not_in(ids))
            )

    async def put_seed(self, m: MailboxRow) -> None:
        """Dev seed: the row as the file has it, created or replaced by id."""
        t = mailboxes
        async with tenant_tx(self.engine) as c:
            await c.execute(t.delete().where(t.c.tenant_id == current_tenant(), t.c.id == m.id))
            await c.execute(t.insert().values(tenant_id=current_tenant(), **m.values()))
