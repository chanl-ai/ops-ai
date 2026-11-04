"""Accounts at rest: how the platform signs in to one system, each account one `connections` row, with the tokens a
sign-in holds.

An account is written against its `revision` (409 on a stale write), as a module is. Secret parts are never here: the
account names the `tool_secrets` row holding each one (`secrets`), so there is one secret store and one cipher path.
Tokens and a sign-in's PKCE verifier are ciphertext only. A sandbox account (`sandbox`) is the one a test run of its
app uses (connections.records.account_for); `app_id` is the app it belongs to.

`connection_tokens` is keyed (tenant, connection, person); `person_id` is `''` for a shared token, a NOT NULL scope
column under a plain primary key, so the key dedupes on every database. A refreshed token is stored only
against the rotation it replaced (CAS), with no lock held while the token request is in flight; a caller that loses
reads the winner's token.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, ClassVar, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_policy import context_of
from ops_service_kit.settings import PluginClient
from ops_store import Guarantee, isolation
from ops_store.outbox import add as add_event
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.search import contains
from ops_store.team_scope import team_visible

from .modules import metadata, module_operations, service_outbox, tool_modules

_TS = sa.DateTime(timezone=True)
SHARED = ""
# The role every transaction of this store runs as: row-level security applies to it, not to the owner the
# service connects as, so the database holds a person's sign-ins to their connection's team.
ROLE = "ops_tools_tenant"

connections = sa.Table(
    "connections",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    # The team that owns it; only that team's modules use it.
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    # A kind in ops_tools.auth.kinds (none, api_key, basic, bearer, oauth2_client_credentials, oauth2_auth_code).
    sa.Column("auth_kind", sa.String(40), nullable=False),
    # draft, healthy, needs_reconnect, revoked or error; `status_detail` says what the system refused, never a value.
    sa.Column("status", sa.String(24), nullable=False),
    sa.Column("status_detail", sa.Text),
    # When the consent an older integration record carries runs out (the dev seed's); null for none.
    sa.Column("expires_at", _TS),
    sa.Column("catalog_id", sa.String(64)),
    # Whose account a call signs in with: team, person, or person_or_team; with person_or_team, a call with
    # nobody behind it uses the team's sign-in only while `team_backup` is on.
    sa.Column("sign_in", sa.String(16), nullable=False, server_default="team"),
    sa.Column("team_backup", sa.Boolean, nullable=False, server_default=sa.false()),
    # The account's last Test connection.
    sa.Column("health", sa.JSON),
    # What the console's card shows for a system connected by name: a category, one line, where its keys are.
    sa.Column("category", sa.String(80)),
    sa.Column("description", sa.String(300)),
    sa.Column("docs_url", sa.String(500)),
    # The app the account belongs to: `plugin:<id>` for a plugin's (a team keeps several named accounts of one
    # app, and the binding's connection is the default), the custom app's own first account's id for a custom app's.
    sa.Column("app_id", sa.String(120), nullable=False),
    # The account a test run of its app uses (records.account_for); a live run never signs in with it.
    sa.Column("sandbox", sa.Boolean, nullable=False, server_default=sa.false()),
    # The account's name, which a tool or step names to use it ("EU org"). One per team and plugin, checked when an
    # account is made: a unique index would treat nulls as equal on SQL Server, refusing a second by-name connection.
    sa.Column("account_name", sa.String(200)),
    # The kind's plain settings (header name, username, token address, scopes, a client certificate's PEM, the base
    # address); never the OAuth client, which is the app credential's (credential_id) or Ops AI's (platform_app).
    sa.Column("settings", sa.JSON, nullable=False),
    # Each secret field to the tool_secrets name holding its value.
    sa.Column("secrets", sa.JSON, nullable=False),
    # The plugin whose platform app the account signs in with: the install's own OAuth client, from the
    # install config (plugin_clients); null for the team's own app. A column, not a setting, so a save that rewrites
    # the settings (Edit keys) keeps it.
    sa.Column("platform_app", sa.String(120)),
    # The team's own OAuth client the account signs in with (app_credentials); null for Ops AI's app or a kind with
    # no client. The client id and secret live only on that row, never in settings or secrets here.
    sa.Column("credential_id", sa.String(64)),
    # A plugin's settings the account keeps its own: its sign-in address, the instance its token named.
    sa.Column("plugin_settings", sa.JSON),
    # "tool" for a connection the platform made to hold a custom tool's address, which the Apps grid does not
    # list; null for one a person added.
    sa.Column("origin", sa.String(16)),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("created_by", sa.String(200), nullable=False),
    sa.Column("created_at", _TS, nullable=False),
    sa.Column("updated_by", sa.String(200), nullable=False),
    sa.Column("updated_at", _TS, nullable=False),
    sa.Index("ix_connections_team", "tenant_id", "team_id"),
    sa.Index("ix_connections_app", "tenant_id", "team_id", "app_id"),
    # Held to its team by the database: only a transaction run as ROLE in that team reads it.
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

# A team's own OAuth client of an app (the app credential): its client id and the name of the team secret holding its
# client secret. The one place a team's client is kept, made under Credentials with no account; an account points at it
# by credential_id, and the store puts both into the account it reads (settings.clientId, secrets.clientSecret) and
# takes them out on a write. Deleting an account leaves it: other accounts may sign in with it.
app_credentials = sa.Table(
    "app_credentials",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    # The app the client was registered for, as connections.app_id names it.
    sa.Column("app_id", sa.String(120), nullable=False),
    # What the Credentials page lists it as.
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("client_id", sa.String(500), nullable=False),
    # The permissions it asks for, space-separated as an account's scopes setting is; null for all the app offers.
    sa.Column("scopes", sa.String(2000)),
    # The tool_secrets name in the team holding the client secret (its row's credential_id is this credential's id);
    # null for a public client.
    sa.Column("secret_name", sa.String(200)),
    # The registration's own settings (a plugin's credential_settings, or a custom app's sign-in and token addresses),
    # which every account signing in with it reads; null for none.
    sa.Column("settings", sa.JSON),
    sa.Column("created_by", sa.String(200), nullable=False),
    sa.Column("created_at", _TS, nullable=False),
    sa.Column("updated_by", sa.String(200), nullable=False),
    sa.Column("updated_at", _TS, nullable=False),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

connection_tokens = sa.Table(
    "connection_tokens",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("connection_id", sa.String(64), primary_key=True),
    # The connection's team, written with the row and moved with the connection.
    sa.Column("team_id", sa.String(64), nullable=False),
    # '' for the connection's shared token; a person's id once each person signs in (slice 14).
    sa.Column("person_id", sa.String(200), primary_key=True),
    sa.Column("access_ct", sa.Text, nullable=False),
    sa.Column("refresh_ct", sa.Text),
    sa.Column("expires_at", _TS),
    sa.Column("scopes", sa.JSON, nullable=False),
    # Who the system says signed in, when it says (an id token's or userinfo's subject).
    sa.Column("account", sa.String(320)),
    # Rises on every refresh; a reader can tell which token a call used.
    sa.Column("rotations", sa.Integer, nullable=False),
    sa.Column("refreshed_at", _TS, nullable=False),
    # When the system refused this person's key or sign-in, and what it said: their next call asks them for a
    # new one instead of sending the refused one again. A new key or sign-in clears it.
    sa.Column("refused_at", _TS),
    sa.Column("refused_reason", sa.String(300)),
    # The person's default among their sign-ins to one app's accounts; none pinned means the newest live one.
    sa.Column("pinned", sa.Boolean, nullable=False, server_default=sa.false()),
    # The account's last test, {status, message, at}: it runs right after a sign-in and never blocks it.
    sa.Column("test", sa.JSON),
    sa.ForeignKeyConstraint(
        ["tenant_id", "connection_id"], ["connections.tenant_id", "connections.id"], ondelete="CASCADE"
    ),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

oauth_states = sa.Table(
    "oauth_states",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    # sha256 of the state sent to the system; the state itself is never stored.
    sa.Column("state_hash", sa.String(64), primary_key=True),
    sa.Column("connection_id", sa.String(64), nullable=False),
    # The connection's team, written with the row.
    sa.Column("team_id", sa.String(64), nullable=False),
    # The person who started the sign-in; only they finish it.
    sa.Column("person_id", sa.String(200), nullable=False),
    sa.Column("verifier_ct", sa.Text, nullable=False),
    sa.Column("redirect_uri", sa.Text, nullable=False),
    sa.Column("expires_at", _TS, nullable=False),
    # Set in the transaction that exchanges the code: a state is used once.
    sa.Column("used_at", _TS),
    # The token row the sign-in fills: SHARED for the team's, the person's id for their own.
    sa.Column("token_for", sa.String(200), nullable=False, server_default=""),
    # The scopes the sign-in asked for, separated by spaces: what it granted when the token answer does not say.
    sa.Column("scopes", sa.Text, nullable=False, server_default=""),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

connect_links = sa.Table(
    "connect_links",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    # sha256 of the link's token; the token itself is never stored.
    sa.Column("token_hash", sa.String(64), primary_key=True),
    sa.Column("connection_id", sa.String(64), nullable=False),
    sa.Column("team_id", sa.String(64), nullable=False),
    # The person it was made for: only they open it.
    sa.Column("person_id", sa.String(200), nullable=False),
    sa.Column("email", sa.String(320), nullable=False),
    # The scopes the sign-in asks for, separated by spaces.
    sa.Column("scopes", sa.Text, nullable=False),
    # Why the link was made: a NotLinkedReason (auth/__init__.py) a person can answer by connecting.
    sa.Column("reason", sa.String(32), nullable=False),
    sa.Column("created_at", _TS, nullable=False),
    sa.Column("expires_at", _TS, nullable=False),
    # Set when the link starts a sign-in: a link is used once.
    sa.Column("used_at", _TS),
    sa.ForeignKeyConstraint(
        ["tenant_id", "connection_id"], ["connections.tenant_id", "connections.id"], ondelete="CASCADE"
    ),
    # A link belongs to the connection's team; another team's link is not found, by the query and by the database.
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

connection_audit = sa.Table(
    "connection_audit",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("connection_id", sa.String(64), nullable=False),
    # The connection's team, written with the row, so its history stays the team's after the connection is deleted.
    sa.Column("team_id", sa.String(64), nullable=False),
    # created, changed, secret_set, signed_in, signed_out, refresh_failed, deleted.
    sa.Column("action", sa.String(32), nullable=False),
    # The Test or Production slot an event from before accounts had sandboxes named; null since.
    sa.Column("environment", sa.String(16)),
    sa.Column("actor", sa.String(200), nullable=False),
    sa.Column("at", _TS, nullable=False),
    # Names only (which fields changed, which account signed in); never a value or a token.
    sa.Column("detail", sa.JSON, nullable=False),
    sa.Index("ix_connection_audit_connection", "tenant_id", "connection_id"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


# A plugin's app as connections.app_id names it; a custom app's is its first account's own id.
PLUGIN_APP = "plugin:"


def plugin_app(plugin_id: str) -> str:
    return f"{PLUGIN_APP}{plugin_id}"


def plugin_of(conn: Mapping[str, Any]) -> str | None:
    """The plugin whose account this is; None for a custom app's."""
    app = str(conn.get("app_id") or "")
    return app.removeprefix(PLUGIN_APP) if app.startswith(PLUGIN_APP) else None


class StaleConnection(RuntimeError):
    """The connection changed since it was read; nothing was written."""


class ConnectionInUse(RuntimeError):
    def __init__(self, modules: list[str]) -> None:
        super().__init__(", ".join(modules))
        self.modules = modules


Row = dict[str, Any]

# What a deleted token or sign-in state held: its credential store reference beside its key, so the caller drops the
# value through the store (`held_of`). A row deleted without that leaves the value in a vault for good.
_HELD_TOKEN = (
    connection_tokens.c.connection_id,
    connection_tokens.c.person_id,
    connection_tokens.c.access_ct,
    connection_tokens.c.refresh_ct,
)
_HELD_STATE = (oauth_states.c.state_hash, oauth_states.c.verifier_ct)


def token_context(tenant_id: str, part: str, connection_id: str, person: str) -> str:
    """The credential store context of a token row's `access` or `refresh` reference."""
    return context_of(tenant_id, f"{part}/{connection_id}/{person or 'shared'}")


def verifier_context(tenant_id: str, state_hash: str) -> str:
    """The credential store context of a sign-in state's PKCE verifier."""
    return context_of(tenant_id, f"pkce/{state_hash}")


def held_of(tenant_id: str, rows: Sequence[Row]) -> list[tuple[str, str]]:
    """Each (reference, context) the deleted rows held: a token row's access and refresh parts, a state's verifier."""
    held: list[tuple[str, str]] = []
    for r in rows:
        if "state_hash" in r:
            held.append((str(r["verifier_ct"]), verifier_context(tenant_id, str(r["state_hash"]))))
            continue
        key = (str(r["connection_id"]), str(r["person_id"]))
        for part in ("access", "refresh"):
            if r.get(f"{part}_ct"):
                held.append((str(r[f"{part}_ct"]), token_context(tenant_id, part, *key)))
    return held


class ConnectionStore:
    # A change and its audit row land together (TRANSACTION) against the revision read (CAS); a
    # token is stored against the rotation it replaced (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.CAS})

    def __init__(self, engine: AsyncEngine, install_clients: Mapping[str, PluginClient] | None = None) -> None:
        """`install_clients` is the install config's OAuth client per plugin (plugin_clients): Ops AI's app, whose
        client id an account on it reads."""
        self.engine = engine
        self.install_clients = dict(install_clients or {})

    def _tx(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """One transaction as ROLE carrying the caller's tenant and team; NoTenantError before any connection when the
        caller set none."""
        return isolation.isolated_tx(self.engine, role=ROLE)

    @staticmethod
    def _team(tenant_id: str, connection_id: str) -> sa.ScalarSelect[str]:
        """The connection's team, read in the statement that writes a sign-in row, so the row never names another."""
        k = connections.c
        mine = (k.tenant_id == tenant_id, k.id == connection_id, team_visible(connections))
        return sa.select(k.team_id).where(*mine).scalar_subquery()

    # ── Records ───────────────────────────────────────────────────────────

    async def _credentials(self, c: AsyncConnection, tenant_id: str, ids: list[str]) -> dict[str, Row]:
        if not ids:
            return {}
        t = app_credentials
        q = t.select().where(t.c.tenant_id == tenant_id, t.c.id.in_(ids), team_visible(t))
        return {str(r["id"]): dict(r) for r in (await c.execute(q)).mappings()}

    async def credential(self, tenant_id: str, credential_id: str) -> Row | None:
        """The team's app credential; None when it is not the team's."""
        async with self._tx() as c:
            return (await self._credentials(c, tenant_id, [credential_id])).get(credential_id)

    async def team_credentials(self, tenant_id: str, team_id: str, app_id: str | None = None) -> list[Row]:
        """The team's app credentials, of one app when `app_id` is given, oldest first."""
        t = app_credentials.c
        where = [t.tenant_id == tenant_id, t.team_id == team_id, team_visible(app_credentials)]
        if app_id is not None:
            where.append(t.app_id == app_id)
        q = app_credentials.select().where(*where).order_by(t.created_at, t.id)
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def add_credential(self, row: Row) -> None:
        """A new app credential: tenant, id, team, app, name, client id, scopes, secret name, who and when."""
        async with self._tx() as c:
            await c.execute(app_credentials.insert().values(**row))

    async def change_credential(
        self, tenant_id: str, credential_id: str, values: Row, *, actor: str, at: datetime
    ) -> None:
        """Writes the credential's name, client id, permissions or settings, with who changed it and when."""
        t = app_credentials.c
        async with self._tx() as c:
            await c.execute(
                app_credentials.update()
                .where(t.tenant_id == tenant_id, t.id == credential_id, team_visible(app_credentials))
                .values(**values, updated_by=actor, updated_at=at)
            )

    async def touch_credential(
        self, tenant_id: str, credential_id: str, *, actor: str, at: datetime, secret_name: str | None = None
    ) -> None:
        """Records who changed the credential last, and with `secret_name` the team secret now holding its client
        secret: an account reads its secret through that name alone, so a secret stored under no name is never sent."""
        t = app_credentials.c
        values: Row = {"updated_by": actor, "updated_at": at}
        if secret_name is not None:
            values["secret_name"] = secret_name
        async with self._tx() as c:
            await c.execute(
                app_credentials.update()
                .where(t.tenant_id == tenant_id, t.id == credential_id, team_visible(app_credentials))
                .values(**values)
            )

    async def credential_accounts(self, tenant_id: str, credential_ids: list[str]) -> list[Row]:
        """The accounts signing in with each named credential, oldest first."""
        if not credential_ids:
            return []
        k = connections.c
        q = (
            connections.select()
            .where(k.tenant_id == tenant_id, k.credential_id.in_(credential_ids), team_visible(connections))
            .order_by(k.created_at, k.id)
        )
        async with self._tx() as c:
            rows = [dict(r) for r in (await c.execute(q)).mappings()]
            return await self._read(c, tenant_id, rows, used=False)

    def install_client(self, plugin_id: str) -> PluginClient | None:
        """Ops AI's own OAuth client for a plugin, from the install config; None when the install set none."""
        return self.install_clients.get(plugin_id)

    def _with_client(self, row: Row, creds: dict[str, Row]) -> Row:
        """The account as its readers see it: the client id of the OAuth client it signs in with in its settings, and
        the name of the client secret in its secrets, from the team's app credential or Ops AI's app."""
        settings, secrets = dict(row.get("settings") or {}), dict(row.get("secrets") or {})
        cred = creds.get(str(row.get("credential_id") or ""))
        installed = self.install_clients.get(str(row.get("platform_app") or ""))
        if cred is not None:
            held = dict(cred.get("settings") or {})
            if str(row.get("app_id") or "").startswith(PLUGIN_APP):
                # A plugin's: merged by the plugin host over the account's own (PluginHost.settings).
                row = {**row, "credential_settings": held}
            else:
                # A custom app's: the registration's addresses and certificate, over any the account was given.
                settings |= held
            settings["clientId"] = cred["client_id"]
            if cred.get("scopes"):
                # The permissions the team's client asks for are the credential's, for every account on it.
                settings["scopes"] = cred["scopes"]
            if cred.get("secret_name"):
                secrets["clientSecret"] = cred["secret_name"]
        elif installed is not None:
            settings["clientId"] = installed.id
        return {**row, "settings": settings, "secrets": secrets}

    async def _put_client(
        self, c: AsyncConnection, tenant_id: str, connection_id: str, fields: Row, *, actor: str, at: datetime
    ) -> Row:
        """Takes the OAuth client out of an account being written: on Ops AI's app it keeps none; otherwise the client
        id and secret name go to the account's app credential (made on the first one) and the account keeps only its
        credential_id. A write that names no secrets (a sign-in saving the instance it read) keeps the client's
        secret as it is."""
        if "credential_id" in fields:
            # The account picks one of the team's credentials (or Ops AI's app): the client it reads is that one's.
            for part, key in (("settings", "clientId"), ("secrets", "clientSecret")):
                if part in fields:
                    fields = {**fields, part: {k: v for k, v in dict(fields[part] or {}).items() if k != key}}
            return fields
        named = "secrets" in fields
        settings, secrets = dict(fields.get("settings") or {}), dict(fields.get("secrets") or {})
        client_id, secret_name = settings.pop("clientId", None), secrets.pop("clientSecret", None)
        fields = {**fields, "settings": settings, **({"secrets": secrets} if named else {})}
        k = connections.c
        held = (
            await c.execute(
                sa.select(k.credential_id, k.platform_app, k.team_id, k.app_id, k.account_name, k.name).where(
                    k.tenant_id == tenant_id, k.id == connection_id, team_visible(connections)
                )
            )
        ).first()
        if held is None:
            raise StaleConnection(connection_id)
        platform = fields.get("platform_app", held.platform_app)
        if platform or not client_id:
            return {**fields, "credential_id": None} if platform else fields
        t = app_credentials
        values = {"client_id": str(client_id), "updated_by": actor, "updated_at": at}
        if named:
            values["secret_name"] = secret_name
        if held.credential_id:
            await c.execute(t.update().where(t.c.tenant_id == tenant_id, t.c.id == held.credential_id).values(**values))
            return {**fields, "credential_id": str(held.credential_id)}
        made = f"cred_{uuid.uuid4().hex[:12]}"
        await c.execute(
            t.insert().values(
                tenant_id=tenant_id, id=made, team_id=held.team_id, app_id=held.app_id,
                name=held.account_name or held.name, created_by=actor, created_at=at, **values,
            )
        )  # fmt: skip
        return {**fields, "credential_id": made}

    async def _used_by(self, c: AsyncConnection, tenant_id: str, ids: list[str]) -> dict[str, list[Row]]:
        """The modules pointing at each connection, joined here so a list never looks them up one by one."""
        if not ids:
            return {}
        q = sa.select(tool_modules.c.connection_id, tool_modules.c.id, tool_modules.c.display_name).where(
            tool_modules.c.tenant_id == tenant_id, tool_modules.c.connection_id.in_(ids), team_visible(tool_modules)
        )
        out: dict[str, list[Row]] = {}
        for r in await c.execute(q.order_by(tool_modules.c.display_name)):
            out.setdefault(str(r.connection_id), []).append({"id": r.id, "name": r.display_name})
        return out

    async def _read(self, c: AsyncConnection, tenant_id: str, rows: list[Row], *, used: bool = True) -> list[Row]:
        """The rows with their OAuth client joined in (one more query) and, with `used`, the modules using them."""
        creds = await self._credentials(c, tenant_id, [str(r["credential_id"]) for r in rows if r.get("credential_id")])
        users = await self._used_by(c, tenant_id, [str(r["id"]) for r in rows]) if used else {}
        return [
            {**self._with_client(r, creds), **({"used_by": users.get(str(r["id"]), [])} if used else {})} for r in rows
        ]

    async def get(self, tenant_id: str, connection_id: str) -> Row | None:
        k = connections.c
        q = connections.select().where(k.tenant_id == tenant_id, k.id == connection_id, team_visible(connections))
        async with self._tx() as c:
            row = (await c.execute(q)).mappings().first()
            return (await self._read(c, tenant_id, [dict(row)]))[0] if row else None

    async def accounts(self, tenant_id: str, team_id: str, app_id: str) -> list[Row]:
        """The team's accounts of one app, oldest first."""
        k = connections.c
        q = (
            connections.select()
            .where(k.tenant_id == tenant_id, k.team_id == team_id, k.app_id == app_id, team_visible(connections))
            .order_by(k.created_at, k.id)
        )
        async with self._tx() as c:
            rows = [dict(r) for r in (await c.execute(q)).mappings()]
            return await self._read(c, tenant_id, rows)

    async def by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, Row]:
        """The named accounts, without the modules using them: what a module list shows of each, its base address
        included."""
        if not ids:
            return {}
        k = connections.c
        q = connections.select().where(k.tenant_id == tenant_id, k.id.in_(ids), team_visible(connections))
        async with self._tx() as c:
            rows = [dict(r) for r in (await c.execute(q)).mappings()]
            return {str(r["id"]): r for r in await self._read(c, tenant_id, rows, used=False)}

    @staticmethod
    def _visible(tenant_id: str, teams: list[str], search: str) -> sa.ColumnElement[bool]:
        """`teams`: the owning teams the caller sees (its own)."""
        where = sa.and_(connections.c.tenant_id == tenant_id, contains(connections.c.name, search))
        return sa.and_(where, connections.c.team_id.in_(teams))

    async def count(self, tenant_id: str, teams: list[str], search: str) -> int:
        q = (
            sa.select(sa.func.count())
            .select_from(connections)
            .where(self._visible(tenant_id, teams, search), team_visible(connections))
        )
        async with self._tx() as c:
            return int((await c.execute(q)).scalar_one())

    async def page(self, tenant_id: str, teams: list[str], search: str, offset: int, limit: int) -> list[Row]:
        q = (
            connections.select()
            .where(self._visible(tenant_id, teams, search), team_visible(connections))
            .order_by(sa.func.lower(connections.c.name), connections.c.id)
            .offset(offset)
            .limit(limit)
        )
        async with self._tx() as c:
            rows = [dict(r) for r in (await c.execute(q)).mappings()]
            return await self._read(c, tenant_id, rows)

    async def create(self, row: Row, *, actor: str, at: datetime) -> bool:
        """False when the id is taken (nothing written). `row` carries the account's settings and secret names; an
        OAuth client in them goes to the account's app credential."""
        fields: Row = {"settings": row.get("settings") or {}, "secrets": row.get("secrets") or {}}
        async with self._tx() as c:
            try:
                async with c.begin_nested():
                    await c.execute(connections.insert().values(**{**row, "settings": {}, "secrets": {}}))
            except IntegrityError:
                return False
            if fields["settings"] or fields["secrets"]:
                put = await self._put_client(c, row["tenant_id"], row["id"], fields, actor=actor, at=at)
                k = connections.c
                await c.execute(
                    connections.update().where(k.tenant_id == row["tenant_id"], k.id == row["id"]).values(**put)
                )
            event = {"action": "created", "actor": actor, "at": at, "detail": {"kind": row["auth_kind"]}}
            await self._audit(c, row["tenant_id"], row["id"], event)
        return True

    async def change(
        self,
        tenant_id: str,
        connection_id: str,
        expected_revision: int,
        values: Row,
        *,
        actor: str,
        at: datetime,
        action: str = "changed",
        detail: Row | None = None,
    ) -> None:
        """Writes `values` (its settings and secret names, `platform_app` and `plugin_settings` among them) only
        against the revision read, with its audit row; StaleConnection otherwise. An OAuth client in the settings goes
        to the account's app credential."""
        async with self._tx() as c:
            if "settings" in values or "secrets" in values or "platform_app" in values:
                values = await self._put_client(c, tenant_id, connection_id, values, actor=actor, at=at)
            q = (
                connections.update()
                .where(
                    connections.c.tenant_id == tenant_id,
                    connections.c.id == connection_id,
                    connections.c.revision == expected_revision,
                )
                .values(**values, revision=expected_revision + 1, updated_by=actor, updated_at=at)
            )
            if (await c.execute(q)).rowcount != 1:
                raise StaleConnection(connection_id)
            if "team_id" in values:
                # A connection moved to another team takes its sign-in rows; only a tenant-wide caller may move one,
                # since the policy refuses writing a row into a team the caller does not act in.
                for t in (connection_tokens, oauth_states):
                    of_it = sa.and_(t.c.tenant_id == tenant_id, t.c.connection_id == connection_id)
                    await c.execute(t.update().where(of_it).values(team_id=values["team_id"]))
                k = connections.c
                cred = (
                    await c.execute(
                        sa.select(k.credential_id).where(
                            k.tenant_id == tenant_id, k.id == connection_id, team_visible(connections)
                        )
                    )
                ).scalar()
                if cred:
                    a = app_credentials
                    mine = sa.and_(a.c.tenant_id == tenant_id, a.c.id == cred)
                    await c.execute(a.update().where(mine).values(team_id=values["team_id"]))
            event = {"action": action, "actor": actor, "at": at, "detail": detail or {}}
            await self._audit(c, tenant_id, connection_id, event)

    async def set_base(self, tenant_id: str, connection_id: str, base: str, *, actor: str, at: datetime) -> None:
        """Sets the app's address on the account, keeping its other settings."""
        k = connections.c
        mine = (k.tenant_id == tenant_id, k.id == connection_id, team_visible(connections))
        async with self._tx() as c:
            held = (await c.execute(sa.select(k.settings).where(*mine))).scalar()
            if held is None:
                raise StaleConnection(connection_id)
            await c.execute(
                connections.update()
                .where(*mine)
                .values(settings={**dict(held or {}), "baseUrl": base}, updated_by=actor, updated_at=at)
            )
            event = {"action": "changed", "actor": actor, "at": at, "detail": {"baseUrl": base}}
            await self._audit(c, tenant_id, connection_id, event)

    async def delete(self, tenant_id: str, connection_id: str, *, actor: str, at: datetime) -> list[Row] | None:
        """None when there is no such connection; ConnectionInUse naming the modules that use it, checked in the
        delete's own transaction. Else the token and sign-in state rows the delete took with it (`held_of`)."""
        async with self._tx() as c:
            used = (await self._used_by(c, tenant_id, [connection_id])).get(connection_id, [])
            if used:
                raise ConnectionInUse([str(u["name"]) for u in used])
            mine = (connections.c.tenant_id == tenant_id, connections.c.id == connection_id, team_visible(connections))
            found = (await c.execute(sa.select(connections.c.team_id).where(*mine))).first()
            if found is None:
                return None
            tokens_q = sa.select(*_HELD_TOKEN).where(
                connection_tokens.c.tenant_id == tenant_id,
                connection_tokens.c.connection_id == connection_id,
                team_visible(connection_tokens),
            )
            states_q = sa.select(*_HELD_STATE).where(
                oauth_states.c.tenant_id == tenant_id,
                oauth_states.c.connection_id == connection_id,
                team_visible(oauth_states),
            )
            held = [dict(r) for q in (tokens_q, states_q) for r in (await c.execute(q)).mappings()]
            if (await c.execute(connections.delete().where(*mine))).rowcount == 0:
                return None
            # The cascade takes the tokens and links; sign-in states name the connection with no key, so they go here.
            await c.execute(
                oauth_states.delete().where(
                    oauth_states.c.tenant_id == tenant_id, oauth_states.c.connection_id == connection_id
                )
            )
            event = {"action": "deleted", "actor": actor, "at": at}
            await self._audit(c, tenant_id, connection_id, event, team_id=str(found.team_id))
        return held

    async def _audit(
        self, c: AsyncConnection, tenant_id: str, connection_id: str, event: Row, *, team_id: str | None = None
    ) -> None:
        """`event`: action, actor, at and detail (names only). The row takes its connection's team, read in the same
        statement, or `team_id` for a connection already deleted in this transaction."""
        team = team_id if team_id is not None else self._team(tenant_id, connection_id)
        await c.execute(
            connection_audit.insert().values(
                tenant_id=tenant_id,
                connection_id=connection_id,
                team_id=team,
                **{"detail": {}, **event},
            )
        )

    async def audit(self, tenant_id: str, connection_id: str, *, limit: int = 50) -> list[Row]:
        q = (
            connection_audit.select()
            .where(
                connection_audit.c.tenant_id == tenant_id,
                connection_audit.c.connection_id == connection_id,
                team_visible(connection_audit),
            )
            .order_by(connection_audit.c.id.desc())
            .limit(limit)
        )
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def note(self, tenant_id: str, connection_id: str, event: Row, *, report: Row | None = None) -> None:
        """An audit row on its own (a sign-in, a sign-out, a failed refresh): action, actor, at, detail. `report`: a
        service event (connections.account_events) written in the same transaction."""
        async with self._tx() as c:
            await self._audit(c, tenant_id, connection_id, event)
            if report is not None:
                await add_event(c, service_outbox, **report)

    async def set_status(self, tenant_id: str, connection_id: str, status: str, detail: str | None) -> None:
        """The gateway's own finding (a refused token request); not a person's edit, so the revision stays."""
        q = (
            connections.update()
            .where(connections.c.tenant_id == tenant_id, connections.c.id == connection_id)
            .values(status=status, status_detail=detail)
        )
        async with self._tx() as c:
            await c.execute(q)

    async def needs_reconnect(self, tenant_id: str, connection_id: str, detail: str | None, event: Row) -> None:
        """The gateway's finding that the team account stopped working: with `detail`, what the system
        refused, the connection is marked needs_reconnect; `event` is the admins' notice (connections.account_events),
        written in the same transaction unless the outbox already holds one under its key, so a call made while the
        account stays broken tells nobody again."""
        o = service_outbox.c
        seen = sa.select(o.id).where(
            o.tenant_id == event["tenant_id"], o.name == event["name"], o.event_key == event["key"]
        )
        async with self._tx() as c:
            if detail is not None:
                await c.execute(
                    connections.update()
                    .where(connections.c.tenant_id == tenant_id, connections.c.id == connection_id)
                    .values(status="needs_reconnect", status_detail=detail)
                )
            if (await c.execute(seen)).first() is None:
                await add_event(c, service_outbox, **event)

    async def set_health(
        self, tenant_id: str, connection_id: str, health: Row, status: tuple[str, str | None] | None = None
    ) -> None:
        """A Test connection's result on the account and, with `status`, its status. A finding, so the revision
        stays."""
        values: Row = {"health": health}
        if status is not None:
            values |= {"status": status[0], "status_detail": status[1]}
        async with self._tx() as c:
            await c.execute(
                connections.update()
                .where(connections.c.tenant_id == tenant_id, connections.c.id == connection_id)
                .values(**values)
            )

    async def set_plugin_settings(self, tenant_id: str, connection_id: str, values: Row) -> bool:
        """Merges `values` into the account's plugin settings (a sign-in's instance); False when there is no such
        account. A finding of the sign-in, not a person's edit, so the revision stays."""
        k = connections.c
        key = (k.tenant_id == tenant_id, k.id == connection_id, team_visible(connections))
        async with self._tx() as c:
            held = (await c.execute(sa.select(k.plugin_settings).where(*key))).first()
            if held is None:
                return False
            merged = {**dict(held.plugin_settings or {}), **values}
            await c.execute(connections.update().where(*key).values(plugin_settings=merged))
        return True

    # ── Tokens ────────────────────────────────────────────────────────────

    @staticmethod
    def _token_key(tenant_id: str, connection_id: str, person: str) -> tuple[Any, ...]:
        t = connection_tokens.c
        return (t.tenant_id == tenant_id, t.connection_id == connection_id, t.person_id == person)

    async def token(self, tenant_id: str, connection_id: str, person: str = SHARED) -> Row | None:
        q = connection_tokens.select().where(
            *self._token_key(tenant_id, connection_id, person), team_visible(connection_tokens)
        )
        async with self._tx() as c:
            row = (await c.execute(q)).mappings().first()
            return dict(row) if row else None

    async def team_tokens(self, tenant_id: str, connection_ids: list[str]) -> dict[str, Row]:
        """The team account's token row (never a person's) of each of these connections: what an app's state is
        derived from."""
        if not connection_ids:
            return {}
        q = connection_tokens.select().where(
            connection_tokens.c.tenant_id == tenant_id,
            connection_tokens.c.connection_id.in_(connection_ids),
            connection_tokens.c.person_id == SHARED,
            team_visible(connection_tokens),
        )
        async with self._tx() as c:
            return {str(r["connection_id"]): dict(r) for r in (await c.execute(q)).mappings()}

    async def tokens(self, tenant_id: str, connection_id: str) -> list[Row]:
        q = connection_tokens.select().where(
            connection_tokens.c.tenant_id == tenant_id,
            connection_tokens.c.connection_id == connection_id,
            team_visible(connection_tokens),
        )
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def put_token(
        self,
        tenant_id: str,
        connection_id: str,
        values: Row,
        *,
        expected_rotations: int | None,
        person: str = SHARED,
    ) -> bool:
        """Stores a token only if the row is still as it was read: `expected_rotations` None means there was no row (an
        insert, which fails if another caller inserted first), else the rotation read (CAS). False when another caller
        stored first; nothing is written then. No lock is held while the token is fetched."""
        key = self._token_key(tenant_id, connection_id, person)
        async with self._tx() as c:
            if expected_rotations is not None:
                q = connection_tokens.update().where(*key, connection_tokens.c.rotations == expected_rotations)
                return (await c.execute(q.values(**values))).rowcount == 1
            try:
                async with c.begin_nested():
                    await c.execute(
                        connection_tokens.insert().values(
                            tenant_id=tenant_id,
                            connection_id=connection_id,
                            person_id=person,
                            team_id=self._team(tenant_id, connection_id),
                            **values,
                        )
                    )
            except IntegrityError:
                return False
            return True

    async def replace_token(self, tenant_id: str, connection_id: str, values: Row, person: str = SHARED) -> None:
        """A finished sign-in's token, whatever was held before; a refusal marked on the row before is cleared."""
        key = self._token_key(tenant_id, connection_id, person)
        # A new sign-in starts untested: the test that follows it writes its own outcome.
        values = {"refused_at": None, "refused_reason": None, "test": None, **values}
        async with self._tx() as c:
            if (await c.execute(connection_tokens.update().where(*key).values(**values))).rowcount == 0:
                await c.execute(
                    connection_tokens.insert().values(
                        tenant_id=tenant_id,
                        connection_id=connection_id,
                        person_id=person,
                        team_id=self._team(tenant_id, connection_id),
                        **values,
                    )
                )

    async def mark_refused(self, tenant_id: str, connection_id: str, person: str, *, reason: str, at: datetime) -> bool:
        """Marks a person's own row refused by the system; False when they hold none."""
        q = connection_tokens.update().where(*self._token_key(tenant_id, connection_id, person))
        async with self._tx() as c:
            return (await c.execute(q.values(refused_at=at, refused_reason=reason[:300]))).rowcount > 0

    async def set_token_test(self, tenant_id: str, connection_id: str, person: str, test: Row) -> bool:
        """The account's last test on its own row, the team's (SHARED) or a person's; False when it holds none."""
        q = connection_tokens.update().where(*self._token_key(tenant_id, connection_id, person))
        async with self._tx() as c:
            return (await c.execute(q.values(test=test))).rowcount > 0

    async def forget_person(self, tenant_id: str, team_id: str, person: str) -> list[Row]:
        """Deletes every sign-in of `person`'s own on `team_id`'s connections (S14: they
        left the team); the rows deleted (`held_of`). Their sign-ins on another team's connections and the team
        accounts stay."""
        if person == SHARED:
            return []
        t = connection_tokens.c
        q = connection_tokens.delete().where(t.tenant_id == tenant_id, t.team_id == team_id, t.person_id == person)
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q.returning(*_HELD_TOKEN))).mappings()]

    async def forget_token(self, tenant_id: str, connection_id: str, person: str = SHARED) -> list[Row]:
        """The token row deleted, empty when there was none (`held_of`)."""
        q = connection_tokens.delete().where(*self._token_key(tenant_id, connection_id, person))
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q.returning(*_HELD_TOKEN))).mappings()]

    async def idle_sign_ins(self, tenant_id: str, refreshed_before: datetime, *, limit: int = 500) -> list[Row]:
        """The acting team's sign-ins, the team's and each person's, that hold a refresh token, were last refreshed
        before `refreshed_before` and are not refused, oldest first: what the keep-alive refreshes. A revoked account's
        are left out."""
        t, k = connection_tokens.c, connections.c
        on = sa.and_(k.tenant_id == t.tenant_id, k.id == t.connection_id)
        q = (
            sa.select(t.connection_id, t.person_id, t.rotations)
            .select_from(connection_tokens.join(connections, on))
            .where(
                t.tenant_id == tenant_id,
                t.refresh_ct.is_not(None),
                t.refreshed_at < refreshed_before,
                t.refused_at.is_(None),
                k.status != "revoked",
                team_visible(connection_tokens),
                team_visible(connections),
            )
            .order_by(t.refreshed_at, t.connection_id, t.person_id)
            .limit(limit)
        )
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def own_sign_ins(self, tenant_id: str, person: str, connection_ids: list[str]) -> list[Row]:
        """One person's own sign-ins on these connections (an app's accounts), newest first: which they pinned
        and which the system refused."""
        if not connection_ids:
            return []
        t = connection_tokens.c
        q = (
            sa.select(t.connection_id, t.account, t.pinned, t.refreshed_at, t.refused_at, t.test)
            .where(
                t.tenant_id == tenant_id,
                t.connection_id.in_(connection_ids),
                t.person_id == person,
                team_visible(connection_tokens),
            )
            .order_by(t.refreshed_at.desc(), t.connection_id)
        )
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def pin(self, tenant_id: str, person: str, connection_id: str, connection_ids: list[str]) -> bool:
        """Pins the person's sign-in on `connection_id` as their default among `connection_ids` (one app's accounts),
        unpinning the others in the same transaction, so a person has one default per app. False when they hold no
        sign-in there."""
        t = connection_tokens.c
        mine = (t.tenant_id == tenant_id, t.person_id == person)
        async with self._tx() as c:
            held = await c.execute(
                sa.select(sa.func.count())
                .select_from(connection_tokens)
                .where(*mine, t.connection_id == connection_id, team_visible(connection_tokens))
            )
            if not held.scalar_one():
                return False
            await c.execute(
                connection_tokens.update()
                .where(*mine, t.connection_id.in_(connection_ids))
                # A CASE rather than the comparison itself: SQL Server takes no boolean expression as a value.
                .values(pinned=sa.case((t.connection_id == connection_id, sa.true()), else_=sa.false()))
            )
        return True

    async def people(self, tenant_id: str, connection_id: str) -> list[Row]:
        """Every person's own sign-in on the connection, oldest first; the team's shared row is not one."""
        t = connection_tokens.c
        q = (
            sa.select(t.person_id, t.account, t.scopes, t.refreshed_at, t.expires_at)
            .where(
                t.tenant_id == tenant_id,
                t.connection_id == connection_id,
                t.person_id != SHARED,
                team_visible(connection_tokens),
            )
            .order_by(t.refreshed_at, t.person_id)
        )
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def sign_ins(self, tenant_id: str, connection_ids: list[str]) -> list[Row]:
        """Every person's own sign-in on these connections (an app's accounts), newest first, with what its state is
        read from: whether the system refused it, and whether it can renew once it ends, and whether the person pinned
        it. The team's row is not one."""
        if not connection_ids:
            return []
        t = connection_tokens.c
        q = (
            sa.select(
                t.connection_id,
                t.person_id,
                t.account,
                t.pinned,
                t.refreshed_at,
                t.expires_at,
                t.refused_at,
                t.test,
                t.refresh_ct.is_not(None).label("renews"),
            )
            .where(
                t.tenant_id == tenant_id,
                t.connection_id.in_(connection_ids),
                t.person_id != SHARED,
                team_visible(connection_tokens),
            )
            .order_by(t.refreshed_at.desc(), t.person_id)
        )
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def operation_scopes(self, tenant_id: str, connection_id: str) -> list[str]:
        """Every scope an operation of a module on this connection needs, in a stable order: what the team's
        account asks for when it signs in, since the calls it signs have nobody to ask for more."""
        o, m = module_operations.c, tool_modules.c
        q = (
            sa.select(o.scopes)
            .join(tool_modules, sa.and_(m.tenant_id == o.tenant_id, m.id == o.module_id))
            .where(o.tenant_id == tenant_id, m.connection_id == connection_id, team_visible(tool_modules))
            .order_by(o.module_id, o.position)
        )
        async with self._tx() as c:
            rows = (await c.execute(q)).scalars().all()
        return list(dict.fromkeys(str(x) for r in rows if isinstance(r, list) for x in cast(list[Any], r)))

    async def mine(self, tenant_id: str, team_id: str, person: str) -> list[Row]:
        """One person's own sign-ins on the team's connections, by connection name."""
        t, k = connection_tokens.c, connections.c
        q = (
            sa.select(
                t.connection_id,
                k.name,
                k.status,
                k.auth_kind,
                k.sandbox,
                k.app_id,
                t.account,
                t.scopes,
                t.refreshed_at,
                t.expires_at,
                t.refused_at,
                t.refused_reason,
                t.test,
            )
            .join(connections, sa.and_(k.tenant_id == t.tenant_id, k.id == t.connection_id))
            .where(
                t.tenant_id == tenant_id,
                k.team_id == team_id,
                t.person_id == person,
                team_visible(connection_tokens),
                team_visible(connections),
            )
            .order_by(k.name, t.connection_id)
        )
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def connectable(self, tenant_id: str, team_id: str, person: str, kinds: list[str]) -> list[Row]:
        """Every account of the team each person signs in to with one of `kinds`, with the person's own row
        where they have one: Your connections, connected or not, by connection name."""
        t, k = connection_tokens.c, connections.c
        own = sa.and_(t.tenant_id == k.tenant_id, t.connection_id == k.id, t.person_id == person)
        q = (
            sa.select(
                k.id.label("connection_id"),
                k.name,
                k.status,
                k.auth_kind,
                k.docs_url,
                k.sandbox,
                k.app_id,
                t.person_id,
                t.account,
                t.scopes,
                t.refreshed_at,
                t.expires_at,
                t.refused_at,
                t.refused_reason,
                t.test,
            )
            .outerjoin(connection_tokens, own)
            .where(
                k.tenant_id == tenant_id,
                k.team_id == team_id,
                k.sign_in != "team",
                k.auth_kind.in_(kinds),
                team_visible(connections),
            )
            .order_by(k.name, k.id)
        )
        async with self._tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    # ── Connect links ─────────────────────────────────────────────────────

    async def add_link(self, row: Row, *, now: datetime) -> None:
        """A link asking one person to sign in; the tenant's expired links go in the same transaction."""
        async with self._tx() as c:
            await c.execute(
                connect_links.delete().where(
                    connect_links.c.tenant_id == row["tenant_id"], connect_links.c.expires_at < now
                )
            )
            await c.execute(connect_links.insert().values(**row))

    async def take_link(self, tenant_id: str, token_hash: str, *, now: datetime) -> Row | None:
        """The link under this hash, marked used in the statement that checks it is unused and unexpired; None when
        there is none, it was used or it expired."""
        k = connect_links.c
        where = (
            k.tenant_id == tenant_id,
            k.token_hash == token_hash,
            k.used_at.is_(None),
            k.expires_at >= now,
            team_visible(connect_links),
        )
        async with self._tx() as c:
            row = (await c.execute(connect_links.select().where(*where))).mappings().first()
            if row is None:
                return None
            if (await c.execute(connect_links.update().where(*where).values(used_at=now))).rowcount != 1:
                return None
            return dict(row)

    async def link(self, tenant_id: str, token_hash: str) -> Row | None:
        """The link under this hash, used or not, for telling its owner apart from anyone else."""
        k = connect_links.c
        async with self._tx() as c:
            found = await c.execute(
                connect_links.select().where(
                    k.tenant_id == tenant_id, k.token_hash == token_hash, team_visible(connect_links)
                )
            )
            row = found.mappings().first()
            return dict(row) if row else None

    # ── Sign-in states ────────────────────────────────────────────────────

    async def add_state(self, row: Row, *, now: datetime) -> list[Row]:
        """Stores a sign-in in progress; expired ones of the tenant go in the same transaction, so the table holds only
        sign-ins under ten minutes old and the used ones not yet pruned. Returns the expired states (`held_of`)."""
        async with self._tx() as c:
            expired = oauth_states.delete().where(
                oauth_states.c.tenant_id == row["tenant_id"], oauth_states.c.expires_at < now
            )
            pruned = [dict(r) for r in (await c.execute(expired.returning(*_HELD_STATE))).mappings()]
            team = self._team(str(row["tenant_id"]), str(row["connection_id"]))
            await c.execute(oauth_states.insert().values(**row, team_id=team))
        return pruned

    async def take_state(
        self, tenant_id: str, state_hash: str, *, connection_id: str, person: str, now: datetime
    ) -> Row | None:
        """The sign-in under this state, marked used in the same statement that checks it is this person's, for this
        connection, unused and unexpired; None otherwise, so another person's attempt never spends it."""
        s = oauth_states.c
        where = (
            s.tenant_id == tenant_id,
            s.state_hash == state_hash,
            s.connection_id == connection_id,
            s.person_id == person,
            s.used_at.is_(None),
            s.expires_at >= now,
            team_visible(oauth_states),
        )
        async with self._tx() as c:
            row = (await c.execute(oauth_states.select().where(*where))).mappings().first()
            if row is None:
                return None
            if (await c.execute(oauth_states.update().where(*where).values(used_at=now))).rowcount != 1:
                return None
            return dict(row)
