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
from datetime import datetime, timedelta
from typing import Any, ClassVar, NotRequired, TypedDict, cast

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_policy import context_of
from ops_service_kit.errors import Conflict
from ops_service_kit.http import Json, Out
from ops_service_kit.listing import ListParams
from ops_service_kit.settings import PluginClient
from ops_store import Guarantee
from ops_store.listing import ListPage, list_page
from ops_store.outbox import add as add_event
from ops_store.rows import Select, one, rows
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.search import contains
from ops_store.store import Store
from ops_store.team_scope import any_team, team_visible

from .app_cards import forget_cards
from .modules import metadata, module_operations, service_outbox, team_modules, tool_modules
from .team_defaults import team_defaults
from .tenancy import ROLE

_TS = sa.DateTime(timezone=True)
SHARED = ""
# The refused_reason of a person's sign-in an admin ended (Apps > People); `ended_by` names the admin.
ENDED_BY_ADMIN = "ended_by_admin"
# How often a token row's last_used_at is written at most: often enough for "last used", rare enough for a busy row.
USED_EVERY = timedelta(minutes=1)
# A team token's columns that change its account's state on a renewal (records.account_state, team_test); a token
# with no refresh token lapses at its expiry, so any write of one changes its card's `due_at`.
_STATE_FIELDS = frozenset({"refused_at", "test"})
# An account a person added for a second login of their own (add_own_account): listed to them, not to the rest of the
# team, signing only that person's calls, and removed when its sign-in turns out to be an identity they already linked.
PERSON_ORIGIN = "person"

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
    # The account's name, which a tool or step names to use it ("EU org"), and the same name case-folded, written with
    # every row that has one (name_key), so the filtered unique index below holds one name per app in a team on every
    # database: SQL Server has no index over an expression.
    sa.Column("account_name", sa.String(200)),
    sa.Column("account_key", sa.String(200)),
    # Whose name it is: empty for the team's accounts, the person (case-folded created_by) for an account a person
    # added for themselves (origin "person"). A name is unique within its owner, so a person may name their own
    # account as the team names one of its.
    sa.Column("owner_key", sa.String(200), nullable=False, server_default=""),
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
NAMED = connections.c.account_key.isnot(None)
# Two accounts of one app in one team with one owner never share a name, since steps, agents and chats pick an account
# by its name: the guarantee behind name lookups (PluginHost.account_named), including two adds at the same moment.
# Filtered, as a plain unique index would hold every unnamed row equal on SQL Server.
sa.Index(
    "uq_connections_account_key",
    connections.c.tenant_id,
    connections.c.team_id,
    connections.c.app_id,
    connections.c.owner_key,
    connections.c.account_key,
    unique=True,
    postgresql_where=NAMED,
    mssql_where=NAMED,
    sqlite_where=NAMED,
)


def owner_key(created_by: object, origin: object) -> str:
    """Who owns an account's name: the person who added it for themselves (`created_by`, with `origin` person), else
    the team (empty)."""
    return str(created_by or "").strip().casefold() if origin == PERSON_ORIGIN else ""


def name_key(name: object) -> str | None:
    """An account name as its uniqueness and lookups compare it: trimmed and case-folded; None for no name."""
    text = str(name or "").strip()
    return text.casefold() if text else None


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
    # Each setting's mode, by name: "default" (Connect pre-selects it and a person may change it) or "fixed" (every
    # account signs in with it). A value with no mode is fixed.
    sa.Column("setting_modes", sa.JSON),
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
    # The person whose own sign-in it is, by name, as the app's accounts list names it; null on the team's row.
    sa.Column("person_name", sa.String(200)),
    # When a call last signed with this row, written at most once a minute (ConnectionStore.used), for Apps > People.
    sa.Column("last_used_at", _TS),
    # The admin who ended this person's sign-in (refused_reason ENDED_BY_ADMIN); a new sign-in clears both.
    sa.Column("ended_by", sa.String(200)),
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
    # Deleting a connection finds its links.
    sa.Index("ix_connect_links_connection", "tenant_id", "connection_id"),
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


def plugin_of(app_id: str | None) -> str | None:
    """The plugin whose app `app_id` is (an account's `app_id`); None for a custom app's."""
    app = app_id or ""
    return app.removeprefix(PLUGIN_APP) if app.startswith(PLUGIN_APP) else None


# An auth config's mode for one of its values: Connect pre-selects a default and a person may change it; every account
# on the config signs in with a fixed one.
DEFAULT_VALUE = "default"
FIXED_VALUE = "fixed"


def split_config(
    values: Mapping[str, JsonValue] | None, modes: Mapping[str, JsonValue] | None
) -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
    """An auth config's set values as (fixed, default). A value with no mode is fixed, as every value was before modes
    existed; an empty one is not set."""
    held: dict[str, JsonValue] = {k: v for k, v in dict(values or {}).items() if v not in (None, "")}
    said = dict(modes or {})
    fixed: dict[str, JsonValue] = {k: v for k, v in held.items() if said.get(k) != DEFAULT_VALUE}
    return fixed, {k: v for k, v in held.items() if k not in fixed}


class StaleConnection(RuntimeError):
    """The connection changed since it was read; nothing was written."""


class AccountNameTaken(Conflict):
    """Another account of the app in the team holds this name (uq_connections_account_key); nothing was written. A
    409 `account_name_taken` wherever it is raised, so every route that makes or renames an account answers the same,
    including the one of two adds at the same moment that the index refused."""

    code = "account_name_taken"

    def __init__(self, name: str) -> None:
        super().__init__(f"Another account of this app is already named {name}. Choose another name.")


class ConnectionInUse(RuntimeError):
    def __init__(self, modules: list[str]) -> None:
        super().__init__(", ".join(modules))
        self.modules = modules


class AppCredentialRow(Out):
    """One `app_credentials` row: a team's own OAuth client of an app."""

    tenant_id: str
    id: str
    team_id: str
    app_id: str
    name: str
    client_id: str
    scopes: str | None
    secret_name: str | None
    settings: Json | None
    setting_modes: Json | None
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


class NewCredential(TypedDict):
    """What a new app credential writes: its client, the secret it is held under and who made it when."""

    tenant_id: str
    id: str
    team_id: str
    app_id: str
    name: str
    client_id: str
    scopes: str | None
    secret_name: str | None
    settings: Json | None
    setting_modes: Json | None
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


class CredentialChange(TypedDict, total=False):
    """What an edit of an app credential may write."""

    name: str
    client_id: str
    scopes: str
    settings: Json | None
    setting_modes: Json | None


class AuditEvent(TypedDict):
    """One audit row to write: what happened, who did it and when, and the names it touched (never a value)."""

    action: str
    actor: str
    at: datetime
    detail: NotRequired[Json]


class ServiceEvent(TypedDict):
    """A service event written to the outbox beside the change it reports (connections.account_events)."""

    tenant_id: str
    team_id: str
    name: str
    key: str
    payload: Json


class AuditRow(Out):
    """One `connection_audit` row as stored."""

    id: int
    tenant_id: str
    connection_id: str
    team_id: str
    action: str
    environment: str | None
    actor: str
    at: datetime
    detail: JsonValue


class NewLink(TypedDict):
    """A connect link to store; only the hash of its token is kept."""

    tenant_id: str
    token_hash: str
    connection_id: str
    team_id: str
    person_id: str
    email: str
    scopes: str
    reason: str
    created_at: datetime
    expires_at: datetime


class LinkRow(Out):
    """One `connect_links` row as stored."""

    tenant_id: str
    token_hash: str
    connection_id: str
    team_id: str
    person_id: str
    email: str
    scopes: str
    reason: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None


class NewState(TypedDict):
    """A sign-in in progress to store; the connection's team is read in the statement that writes it."""

    tenant_id: str
    state_hash: str
    connection_id: str
    person_id: str
    verifier_ct: str
    redirect_uri: str
    expires_at: datetime
    token_for: NotRequired[str]
    scopes: NotRequired[str]


class StateRow(Out):
    """One `oauth_states` row as stored."""

    tenant_id: str
    state_hash: str
    connection_id: str
    team_id: str
    person_id: str
    verifier_ct: str
    redirect_uri: str
    expires_at: datetime
    used_at: datetime | None
    token_for: str
    scopes: str


class StateAccount(Out):
    """The account a sign-in's state was sent out for and whose token it fills."""

    connection_id: str
    token_for: str


class _OptionalColumns(TypedDict, total=False):
    name: str
    status: str
    status_detail: str | None
    expires_at: datetime | None
    catalog_id: str | None
    sign_in: str
    team_backup: bool
    health: Json | None
    category: str | None
    description: str | None
    docs_url: str | None
    app_id: str
    sandbox: bool
    account_name: str | None
    account_key: str | None
    owner_key: str
    settings: Json
    secrets: dict[str, str]
    platform_app: str | None
    credential_id: str | None
    plugin_settings: Json | None
    origin: str | None
    revision: int
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


class AccountColumns(_OptionalColumns, total=False):
    """The `connections` columns an edit names, and an account being made as well."""

    team_id: str
    auth_kind: str


class _Identity(TypedDict):
    tenant_id: str
    id: str
    team_id: str
    auth_kind: str


class NewAccount(_Identity, _OptionalColumns):
    """An account to make: its identity, and any of the other columns."""


class TokenWrite(TypedDict, total=False):
    """The `connection_tokens` columns a write names; a sign-in or a refresh writes the `TokenFields`, a new sign-in
    also clears the refusal and the test."""

    access_ct: str
    refresh_ct: str | None
    expires_at: datetime | None
    scopes: JsonValue
    account: str | None
    rotations: int
    refreshed_at: datetime
    refused_at: datetime | None
    refused_reason: str | None
    ended_by: str | None
    test: Json | None


class _AccountFields(Out):
    """The `connections` columns every account read carries but its settings and secret names."""

    tenant_id: str
    id: str
    team_id: str
    name: str
    auth_kind: str
    status: str
    status_detail: str | None
    expires_at: datetime | None
    catalog_id: str | None
    sign_in: str
    team_backup: bool
    # The last Test connection, {status, account, message, at, ...}; null before one ran.
    health: Json | None
    category: str | None
    description: str | None
    docs_url: str | None
    app_id: str
    sandbox: bool
    account_name: str | None
    account_key: str | None
    owner_key: str
    platform_app: str | None
    credential_id: str | None
    plugin_settings: Json | None
    origin: str | None
    revision: int
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


class _AccountRow(_AccountFields):
    """One `connections` row as stored. The JSON columns are NOT NULL, yet a JSON null is a value they can hold."""

    settings: Json | None
    # Each secret field to the `tool_secrets` name holding its value.
    secrets: dict[str, str] | None


class AccountUse(Out):
    """A module using an account."""

    id: str
    name: str


class Account(_AccountFields):
    """An account as its readers see it (`ConnectionStore._read`): the OAuth client it signs in with joined into its
    `settings` (clientId, scopes) and `secrets` (clientSecret); on a plugin's account with a team auth config, that
    config's fixed values (`credential_settings`); and, from a read that lists them, the modules using it (`used_by`,
    None from one that does not)."""

    settings: Json
    secrets: dict[str, str]
    credential_settings: Json | None = None
    used_by: list[AccountUse] | None = None


class OwnSignIn(Out):
    """One person's own sign-in on one of an app's accounts, as the account choice reads it."""

    connection_id: str
    account: str | None
    pinned: bool
    refreshed_at: datetime
    refused_at: datetime | None
    test: JsonValue
    # ENDED_BY_ADMIN when an admin ended it (ended_by names them), else the system's words; None while it works.
    refused_reason: str | None = None
    ended_by: str | None = None


class TokenFields(Out):
    """What a sign-in or a refresh writes to a `connection_tokens` row: the access and refresh references (ciphertext
    in the credential store, never a token), when it ends, what it granted and who it signed in as."""

    access_ct: str
    refresh_ct: str | None
    expires_at: datetime | None
    # The scopes granted, a JSON list as stored.
    scopes: JsonValue
    account: str | None
    rotations: int
    refreshed_at: datetime

    def columns(self) -> TokenWrite:
        """The fields as the columns a write names."""
        return {
            "access_ct": self.access_ct,
            "refresh_ct": self.refresh_ct,
            "expires_at": self.expires_at,
            "scopes": self.scopes,
            "account": self.account,
            "rotations": self.rotations,
            "refreshed_at": self.refreshed_at,
        }


class TokenRow(TokenFields):
    """One `connection_tokens` row: the team's (person_id SHARED) or one person's own sign-in on an account."""

    tenant_id: str
    connection_id: str
    team_id: str
    person_id: str
    refused_at: datetime | None
    refused_reason: str | None
    pinned: bool
    # The account's last test, {status, message, at}; null before one ran.
    test: JsonValue
    person_name: str | None
    last_used_at: datetime | None = None
    ended_by: str | None = None


class TeamToken(TokenRow):
    """The team account's token row, with whether a refresh token is held (`renews`)."""

    renews: bool


class PersonSignIn(Out):
    """A person's own sign-in on an account, as the account's people list reads it."""

    person_id: str
    account: str | None
    scopes: JsonValue
    refreshed_at: datetime
    expires_at: datetime | None


class SignIn(Out):
    """A person's own sign-in on one of an app's accounts, with what its state is read from."""

    connection_id: str
    person_id: str
    person_name: str | None
    account: str | None
    pinned: bool
    refreshed_at: datetime
    expires_at: datetime | None
    refused_at: datetime | None
    test: JsonValue
    renews: bool


class PersonRow(Out):
    """One person on Apps > People: their own sign-ins on the team's accounts, counted by state, and the last call
    any of them signed."""

    person_id: str
    person_name: str | None
    connected: int
    expired: int
    refused: int
    last_used_at: datetime | None


class PersonAppSignIn(Out):
    """One of a person's own sign-ins on Apps > People, with its account and app and what its state is read from."""

    person_id: str
    connection_id: str
    app_id: str
    account_name: str | None
    connection_name: str
    account: str | None
    refreshed_at: datetime
    expires_at: datetime | None
    refused_at: datetime | None
    refused_reason: str | None
    ended_by: str | None
    last_used_at: datetime | None
    renews: bool


class IdleSignIn(Out):
    """A sign-in the keep-alive refreshes, by its key and the rotation read."""

    connection_id: str
    person_id: str
    rotations: int


class OwnAccount(Out):
    """An account of the team a person signs in to, with the person's own sign-in on it (Your connections). From
    `connectable` the sign-in is outer-joined, so each of its columns is null where the person has not connected; `mine`
    reads only connected ones and selects neither `docs_url` nor `person_id`."""

    connection_id: str
    name: str
    status: str
    auth_kind: str
    sandbox: bool
    app_id: str
    platform_app: str | None
    credential_name: str | None
    account: str | None
    scopes: JsonValue
    refreshed_at: datetime | None
    expires_at: datetime | None
    refused_at: datetime | None
    refused_reason: str | None
    test: JsonValue
    docs_url: str | None = None
    person_id: str | None = None


class HeldToken(Out):
    """What a deleted token row held: its key and its credential store references (`held_of`)."""

    connection_id: str
    person_id: str
    access_ct: str
    refresh_ct: str | None


class HeldState(Out):
    """What a deleted sign-in state held: its key and the PKCE verifier's credential store reference (`held_of`)."""

    state_hash: str
    verifier_ct: str


Held = HeldToken | HeldState

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


def held_of(tenant_id: str, rows: Sequence[Held]) -> list[tuple[str, str]]:
    """Each (reference, context) the deleted rows held: a token row's access and refresh parts, a state's verifier."""
    held: list[tuple[str, str]] = []
    for r in rows:
        if isinstance(r, HeldState):
            held.append((r.verifier_ct, verifier_context(tenant_id, r.state_hash)))
            continue
        for part, ref in (("access", r.access_ct), ("refresh", r.refresh_ct)):
            if ref:
                held.append((ref, token_context(tenant_id, part, r.connection_id, r.person_id)))
    return held


# The account's auth config, when it signs in with one of the team's own (its name, read beside the account).
_CREDENTIAL_OF = sa.and_(
    app_credentials.c.tenant_id == connections.c.tenant_id, app_credentials.c.id == connections.c.credential_id
)


async def _forget_account_cards(c: AsyncConnection, tenant_id: str, connection_id: str) -> None:
    """Clears the card stamp of the team holding the account: its status, test, settings or team token decide its
    card's state (store/app_cards.py)."""
    k = connections.c
    owner = sa.select(k.team_id).where(k.tenant_id == tenant_id, k.id == connection_id, team_visible(connections))
    await forget_cards(c, tenant_id, team_defaults.c.team_id.in_(owner))


async def _forget_credential_cards(c: AsyncConnection, tenant_id: str, credential_id: str) -> None:
    """Clears the card stamp of the team holding the auth config: whether its app has a usable one decides the state."""
    a = app_credentials.c
    owner = sa.select(a.team_id).where(a.tenant_id == tenant_id, a.id == credential_id, team_visible(app_credentials))
    await forget_cards(c, tenant_id, team_defaults.c.team_id.in_(owner))


class ConnectionStore(Store):
    # A change and its audit row land together (TRANSACTION) against the revision read (CAS); a
    # token is stored against the rotation it replaced (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.CAS})
    # Every transaction runs as ROLE carrying the caller's tenant and team; NoTenantError before any connection when
    # the caller set none.
    role = ROLE

    def __init__(self, engine: AsyncEngine, install_clients: Mapping[str, PluginClient] | None = None) -> None:
        """`install_clients` is the install config's OAuth client per plugin (plugin_clients): Ops AI's app, whose
        client id an account on it reads."""
        super().__init__(engine)
        self.install_clients = dict(install_clients or {})

    @staticmethod
    def _team(tenant_id: str, connection_id: str) -> sa.ScalarSelect[str]:
        """The connection's team, read in the statement that writes a sign-in row, so the row never names another."""
        k = connections.c
        mine = (k.tenant_id == tenant_id, k.id == connection_id, team_visible(connections))
        return sa.select(k.team_id).where(*mine).scalar_subquery()

    # ── Records ───────────────────────────────────────────────────────────

    async def _credentials(self, c: AsyncConnection, tenant_id: str, ids: list[str]) -> dict[str, AppCredentialRow]:
        if not ids:
            return {}
        t = app_credentials
        q = t.select().where(t.c.tenant_id == tenant_id, t.c.id.in_(ids), team_visible(t))
        return {r.id: r for r in await rows(c, q, AppCredentialRow)}

    async def credential(self, tenant_id: str, credential_id: str) -> AppCredentialRow | None:
        """The team's app credential; None when it is not the team's."""
        async with self.tx() as c:
            return (await self._credentials(c, tenant_id, [credential_id])).get(credential_id)

    async def team_credentials(self, tenant_id: str, team_id: str, app_id: str | None = None) -> list[AppCredentialRow]:
        """The team's app credentials, of one app when `app_id` is given, oldest first."""
        t = app_credentials.c
        where = [t.tenant_id == tenant_id, t.team_id == team_id, team_visible(app_credentials)]
        if app_id is not None:
            where.append(t.app_id == app_id)
        q = app_credentials.select().where(*where).order_by(t.created_at, t.id)
        async with self.tx() as c:
            return await rows(c, q, AppCredentialRow)

    async def add_credential(self, row: NewCredential) -> None:
        """A new app credential: tenant, id, team, app, name, client id, scopes, secret name, who and when."""
        async with self.tx() as c:
            await c.execute(app_credentials.insert().values(**row))
            await forget_cards(c, row["tenant_id"], team_defaults.c.team_id == row["team_id"])

    async def change_credential(
        self, tenant_id: str, credential_id: str, values: CredentialChange, *, actor: str, at: datetime
    ) -> None:
        """Writes the credential's name, client id, permissions or settings, with who changed it and when."""
        t = app_credentials.c
        async with self.tx() as c:
            await c.execute(
                app_credentials.update()
                .where(t.tenant_id == tenant_id, t.id == credential_id, team_visible(app_credentials))
                .values(**values, updated_by=actor, updated_at=at)
            )
            await _forget_credential_cards(c, tenant_id, credential_id)

    async def delete_credential(self, tenant_id: str, credential_id: str) -> bool:
        """Deletes the team's app credential; False when there is none. Accounts are moved off it first."""
        t = app_credentials.c
        async with self.tx() as c:
            await _forget_credential_cards(c, tenant_id, credential_id)
            gone = await c.execute(
                app_credentials.delete().where(
                    t.tenant_id == tenant_id, t.id == credential_id, team_visible(app_credentials)
                )
            )
            return bool(gone.rowcount)

    async def touch_credential(
        self, tenant_id: str, credential_id: str, *, actor: str, at: datetime, secret_name: str | None = None
    ) -> None:
        """Records who changed the credential last, and with `secret_name` the team secret now holding its client
        secret: an account reads its secret through that name alone, so a secret stored under no name is never sent."""
        t = app_credentials.c
        values: dict[str, str | datetime] = {"updated_by": actor, "updated_at": at}
        if secret_name is not None:
            values["secret_name"] = secret_name
        async with self.tx() as c:
            await c.execute(
                app_credentials.update()
                .where(t.tenant_id == tenant_id, t.id == credential_id, team_visible(app_credentials))
                .values(**values)
            )
            if secret_name is not None:
                await _forget_credential_cards(c, tenant_id, credential_id)

    async def credential_accounts(self, tenant_id: str, credential_ids: list[str]) -> list[Account]:
        """The accounts signing in with each named credential, oldest first."""
        if not credential_ids:
            return []
        k = connections.c
        q = (
            connections.select()
            .where(k.tenant_id == tenant_id, k.credential_id.in_(credential_ids), team_visible(connections))
            .order_by(k.created_at, k.id)
        )
        async with self.tx() as c:
            return await self._read(c, tenant_id, q, used=False)

    def install_client(self, plugin_id: str) -> PluginClient | None:
        """Ops AI's own OAuth client for a plugin, from the install config; None when the install set none."""
        return self.install_clients.get(plugin_id)

    def _with_client(
        self, row: _AccountRow, creds: dict[str, AppCredentialRow], used: list[AccountUse] | None
    ) -> Account:
        """The account as its readers see it: the client id of the OAuth client it signs in with in its settings, and
        the name of the client secret in its secrets, from the team's app credential or Ops AI's app."""
        settings: Json = dict(row.settings or {})
        secrets = dict(row.secrets or {})
        cred = creds.get(row.credential_id or "")
        installed = self.install_clients.get(row.platform_app or "")
        fixed: Json | None = None
        if cred is not None:
            held = dict(cred.settings or {})
            if row.app_id.startswith(PLUGIN_APP):
                # A plugin's fixed values, merged by the plugin host over the account's own (PluginHost.settings); a
                # default one was the account's starting value and the account keeps its own.
                fixed = split_config(held, cred.setting_modes)[0]
            else:
                # A custom app's: the registration's addresses and certificate, over any the account was given.
                settings |= held
            settings["clientId"] = cred.client_id
            if cred.scopes:
                # The permissions the team's client asks for are the credential's, for every account on it.
                settings["scopes"] = cred.scopes
            if cred.secret_name:
                secrets["clientSecret"] = cred.secret_name
        elif installed is not None:
            settings["clientId"] = installed.id
        fields = row.model_dump(exclude={"settings", "secrets"})
        return Account(**fields, settings=settings, secrets=secrets, credential_settings=fixed, used_by=used)

    async def _put_client(
        self,
        c: AsyncConnection,
        tenant_id: str,
        connection_id: str,
        fields: AccountColumns,
        *,
        actor: str,
        at: datetime,
    ) -> AccountColumns:
        """Takes the OAuth client out of an account being written: on Ops AI's app it keeps none; otherwise the client
        id and secret name go to the account's app credential (made on the first one) and the account keeps only its
        credential_id. A write that names no secrets (a sign-in saving the instance it read) keeps the client's
        secret as it is."""
        if "credential_id" in fields:
            # The account picks one of the team's credentials (or Ops AI's app): the client it reads is that one's.
            if "settings" in fields:
                fields = {
                    **fields,
                    "settings": {k: v for k, v in dict(fields["settings"] or {}).items() if k != "clientId"},
                }
            if "secrets" in fields:
                fields = {
                    **fields,
                    "secrets": {k: v for k, v in dict(fields["secrets"] or {}).items() if k != "clientSecret"},
                }
            return fields
        named = "secrets" in fields
        settings, secrets = dict(fields.get("settings") or {}), dict(fields.get("secrets") or {})
        client_id, secret_name = settings.pop("clientId", None), secrets.pop("clientSecret", None)
        fields = {**fields, "settings": settings}
        if named:
            fields["secrets"] = secrets
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
        values: dict[str, str | datetime | None] = {"client_id": str(client_id), "updated_by": actor, "updated_at": at}
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

    async def _used_by(self, c: AsyncConnection, tenant_id: str, ids: list[str]) -> dict[str, list[AccountUse]]:
        """The modules pointing at each connection, joined here so a list never looks them up one by one."""
        if not ids:
            return {}
        q = sa.select(tool_modules.c.connection_id, tool_modules.c.id, tool_modules.c.display_name).where(
            tool_modules.c.tenant_id == tenant_id, tool_modules.c.connection_id.in_(ids), team_modules()
        )
        out: dict[str, list[AccountUse]] = {}
        for r in await c.execute(q.order_by(tool_modules.c.display_name)):
            out.setdefault(str(r.connection_id), []).append(AccountUse(id=r.id, name=r.display_name))
        return out

    async def _read(self, c: AsyncConnection, tenant_id: str, q: Select, *, used: bool = True) -> list[Account]:
        """The accounts `q` selects, with their OAuth client joined in (one more query) and, with `used`, the modules
        using them."""
        found = await rows(c, q, _AccountRow)
        creds = await self._credentials(c, tenant_id, [r.credential_id for r in found if r.credential_id])
        users = await self._used_by(c, tenant_id, [r.id for r in found]) if used else {}
        return [self._with_client(r, creds, users.get(r.id, []) if used else None) for r in found]

    async def get(self, tenant_id: str, connection_id: str) -> Account | None:
        k = connections.c
        q = connections.select().where(k.tenant_id == tenant_id, k.id == connection_id, team_visible(connections))
        async with self.tx() as c:
            found = await self._read(c, tenant_id, q)
            return found[0] if found else None

    async def accounts(self, tenant_id: str, team_id: str, app_id: str) -> list[Account]:
        """The team's accounts of one app, oldest first."""
        k = connections.c
        q = (
            connections.select()
            .where(k.tenant_id == tenant_id, k.team_id == team_id, k.app_id == app_id, team_visible(connections))
            .order_by(k.created_at, k.id)
        )
        async with self.tx() as c:
            return await self._read(c, tenant_id, q)

    async def by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, Account]:
        """The named accounts, without the modules using them: what a module list shows of each, its base address
        included."""
        if not ids:
            return {}
        k = connections.c
        q = connections.select().where(k.tenant_id == tenant_id, k.id.in_(ids), team_visible(connections))
        async with self.tx() as c:
            return {r.id: r for r in await self._read(c, tenant_id, q, used=False)}

    async def of_apps(self, tenant_id: str, team_id: str, app_ids: Sequence[str]) -> list[Account]:
        """The team's accounts of the named apps (a page of the Apps grid, so a short list), with the modules using
        them."""
        if not app_ids:
            return []
        k = connections.c
        q = (
            connections.select()
            .where(
                k.tenant_id == tenant_id, k.team_id == team_id, k.app_id.in_(list(app_ids)), team_visible(connections)
            )
            .order_by(sa.func.lower(k.name), k.id)
        )
        async with self.tx() as c:
            return await self._read(c, tenant_id, q)

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
        async with self.tx() as c:
            return int((await c.execute(q)).scalar_one())

    async def page(self, tenant_id: str, teams: list[str], search: str, offset: int, limit: int) -> list[Account]:
        q = (
            connections.select()
            .where(self._visible(tenant_id, teams, search), team_visible(connections))
            .order_by(sa.func.lower(connections.c.name), connections.c.id)
            .offset(offset)
            .limit(limit)
        )
        async with self.tx() as c:
            return await self._read(c, tenant_id, q)

    async def create(self, row: NewAccount, *, actor: str, at: datetime) -> bool:
        """False when the id is taken (nothing written). `row` carries the account's settings and secret names; an
        OAuth client in them goes to the account's app credential."""
        fields: AccountColumns = {"settings": row.get("settings") or {}, "secrets": row.get("secrets") or {}}
        owner = owner_key(row.get("created_by"), row.get("origin"))
        row = {**row, "account_key": name_key(row.get("account_name")), "owner_key": owner}
        async with self.tx() as c:
            try:
                async with self.attempt(c):
                    await c.execute(connections.insert().values(**{**row, "settings": {}, "secrets": {}}))
            except IntegrityError as e:
                k = connections.c
                # The key is (tenant_id, id): a clash may be another team's row, so the refusal check names no team.
                taken = sa.select(k.id).where(
                    k.tenant_id == row["tenant_id"],
                    k.id == row["id"],
                    any_team(connections, "an id clash is decided across teams; the row is never returned"),
                )
                if (await c.execute(taken)).first() is None:
                    raise AccountNameTaken(str(row.get("account_name"))) from e
                return False
            if fields["settings"] or fields["secrets"]:
                put = await self._put_client(c, row["tenant_id"], row["id"], fields, actor=actor, at=at)
                k = connections.c
                await c.execute(
                    connections.update().where(k.tenant_id == row["tenant_id"], k.id == row["id"]).values(**put)
                )
            event: AuditEvent = {"action": "created", "actor": actor, "at": at, "detail": {"kind": row["auth_kind"]}}
            await self._audit(c, row["tenant_id"], row["id"], event)
            await forget_cards(c, row["tenant_id"], team_defaults.c.team_id == row["team_id"])
        return True

    async def change(
        self,
        tenant_id: str,
        connection_id: str,
        expected_revision: int,
        values: AccountColumns,
        *,
        actor: str,
        at: datetime,
        action: str = "changed",
        detail: Json | None = None,
    ) -> None:
        """Writes `values` (its settings and secret names, `platform_app` and `plugin_settings` among them) only
        against the revision read, with its audit row; StaleConnection otherwise. An OAuth client in the settings goes
        to the account's app credential."""
        if "account_name" in values:
            values = {**values, "account_key": name_key(values["account_name"])}
        async with self.tx() as c:
            if "settings" in values or "secrets" in values or "platform_app" in values:
                values = await self._put_client(c, tenant_id, connection_id, values, actor=actor, at=at)
            q = (
                connections.update()
                .where(
                    connections.c.tenant_id == tenant_id,
                    connections.c.id == connection_id,
                    connections.c.revision == expected_revision,
                )
                .values(**{**values, "revision": expected_revision + 1, "updated_by": actor, "updated_at": at})
            )
            try:
                async with self.attempt(c):
                    changed = (await c.execute(q)).rowcount
            except IntegrityError as e:
                raise AccountNameTaken(str(values.get("account_name"))) from e
            if changed != 1:
                raise StaleConnection(connection_id)
            # Any edit may change the card: its name or category, or its settings, sign-in or auth config, which
            # decide its state. A move changes two teams' cards; only a tenant-wide caller moves one, and it clears
            # every team's.
            if "team_id" in values:
                await forget_cards(c, tenant_id, sa.true())
            else:
                await _forget_account_cards(c, tenant_id, connection_id)
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
            event: AuditEvent = {"action": action, "actor": actor, "at": at, "detail": detail or {}}
            await self._audit(c, tenant_id, connection_id, event)

    async def set_base(self, tenant_id: str, connection_id: str, base: str, *, actor: str, at: datetime) -> None:
        """Sets the app's address on the account, keeping its other settings."""
        k = connections.c
        mine = (k.tenant_id == tenant_id, k.id == connection_id, team_visible(connections))
        async with self.tx() as c:
            held = (await c.execute(sa.select(k.settings).where(*mine))).scalar()
            if held is None:
                raise StaleConnection(connection_id)
            await c.execute(
                connections.update()
                .where(*mine)
                .values(settings={**dict(held or {}), "baseUrl": base}, updated_by=actor, updated_at=at)
            )
            await _forget_account_cards(c, tenant_id, connection_id)
            event: AuditEvent = {"action": "changed", "actor": actor, "at": at, "detail": {"baseUrl": base}}
            await self._audit(c, tenant_id, connection_id, event)

    async def delete(self, tenant_id: str, connection_id: str, *, actor: str, at: datetime) -> list[Held] | None:
        """None when there is no such connection; ConnectionInUse naming the modules that use it, checked in the
        delete's own transaction. Else the token and sign-in state rows the delete took with it (`held_of`)."""
        async with self.tx() as c:
            used = (await self._used_by(c, tenant_id, [connection_id])).get(connection_id, [])
            if used:
                raise ConnectionInUse([u.name for u in used])
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
            held: list[Held] = [*await rows(c, tokens_q, HeldToken), *await rows(c, states_q, HeldState)]
            if (await c.execute(connections.delete().where(*mine))).rowcount == 0:
                return None
            await forget_cards(c, tenant_id, team_defaults.c.team_id == found.team_id)
            # The cascade takes the tokens and links; sign-in states name the connection with no key, so they go here.
            await c.execute(
                oauth_states.delete().where(
                    oauth_states.c.tenant_id == tenant_id, oauth_states.c.connection_id == connection_id
                )
            )
            event: AuditEvent = {"action": "deleted", "actor": actor, "at": at}
            await self._audit(c, tenant_id, connection_id, event, team_id=str(found.team_id))
        return held

    async def _audit(
        self, c: AsyncConnection, tenant_id: str, connection_id: str, event: AuditEvent, *, team_id: str | None = None
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

    async def audit(self, tenant_id: str, connection_id: str, *, limit: int = 50) -> list[AuditRow]:
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
        async with self.tx() as c:
            return await rows(c, q, AuditRow)

    async def newest(
        self, tenant_id: str, connection_ids: Sequence[str], action: str
    ) -> list[tuple[str, datetime, JsonValue]]:
        """Each account's newest audit row of one action, as (account id, at, detail), in one statement however many
        accounts are named: an app credential's list reads its accounts' last Test with my account this way."""
        if not connection_ids:
            return []
        a = connection_audit
        last = (
            sa.select(sa.func.max(a.c.id).label("id"))
            .where(
                a.c.tenant_id == tenant_id,
                a.c.connection_id.in_(list(connection_ids)),
                a.c.action == action,
                team_visible(a),
            )
            .group_by(a.c.connection_id)
        )
        q = sa.select(a.c.connection_id, a.c.at, a.c.detail).where(a.c.id.in_(last), team_visible(a))
        async with self.tx() as c:
            return [(str(r.connection_id), r.at, cast(JsonValue, r.detail)) for r in await c.execute(q)]

    async def note(
        self, tenant_id: str, connection_id: str, event: AuditEvent, *, report: ServiceEvent | None = None
    ) -> None:
        """An audit row on its own (a sign-in, a sign-out, a failed refresh): action, actor, at, detail. `report`: a
        service event (connections.account_events) written in the same transaction."""
        async with self.tx() as c:
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
        async with self.tx() as c:
            await c.execute(q)
            await _forget_account_cards(c, tenant_id, connection_id)

    async def needs_reconnect(
        self, tenant_id: str, connection_id: str, detail: str | None, event: ServiceEvent
    ) -> None:
        """The gateway's finding that the team account stopped working: with `detail`, what the system
        refused, the connection is marked needs_reconnect; `event` is the admins' notice (connections.account_events),
        written in the same transaction unless the outbox already holds one under its key, so a call made while the
        account stays broken tells nobody again."""
        o = service_outbox.c
        seen = sa.select(o.id).where(
            o.tenant_id == event["tenant_id"], o.name == event["name"], o.event_key == event["key"]
        )
        async with self.tx() as c:
            if detail is not None:
                await c.execute(
                    connections.update()
                    .where(connections.c.tenant_id == tenant_id, connections.c.id == connection_id)
                    .values(status="needs_reconnect", status_detail=detail)
                )
                await _forget_account_cards(c, tenant_id, connection_id)
            if (await c.execute(seen)).first() is None:
                await add_event(c, service_outbox, **event)

    async def set_health(
        self, tenant_id: str, connection_id: str, health: Json, status: tuple[str, str | None] | None = None
    ) -> None:
        """A Test connection's result on the account and, with `status`, its status. A finding, so the revision
        stays."""
        values: dict[str, Json | str | None] = {"health": health}
        if status is not None:
            values |= {"status": status[0], "status_detail": status[1]}
        async with self.tx() as c:
            await c.execute(
                connections.update()
                .where(connections.c.tenant_id == tenant_id, connections.c.id == connection_id)
                .values(**values)
            )
            await _forget_account_cards(c, tenant_id, connection_id)

    async def set_plugin_settings(self, tenant_id: str, connection_id: str, values: Json) -> bool:
        """Merges `values` into the account's plugin settings (a sign-in's instance); False when there is no such
        account. A finding of the sign-in, not a person's edit, so the revision stays."""
        k = connections.c
        key = (k.tenant_id == tenant_id, k.id == connection_id, team_visible(connections))
        async with self.tx() as c:
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

    async def token(self, tenant_id: str, connection_id: str, person: str = SHARED) -> TokenRow | None:
        q = connection_tokens.select().where(
            *self._token_key(tenant_id, connection_id, person), team_visible(connection_tokens)
        )
        async with self.tx() as c:
            return await one(c, q, TokenRow)

    async def team_tokens(self, tenant_id: str, connection_ids: list[str]) -> dict[str, TeamToken]:
        """The team account's token row (never a person's) of each of these connections: what an app's state is
        derived from. `renews` says whether a refresh token is held, so a caller never names the reference's column."""
        if not connection_ids:
            return {}
        # A CASE, not the bare test: SQL Server refuses a predicate as a selected value.
        renews = sa.case((connection_tokens.c.refresh_ct.is_not(None), 1), else_=0).label("renews")
        q = (
            connection_tokens.select()
            .add_columns(renews)
            .where(
                connection_tokens.c.tenant_id == tenant_id,
                connection_tokens.c.connection_id.in_(connection_ids),
                connection_tokens.c.person_id == SHARED,
                team_visible(connection_tokens),
            )
        )
        async with self.tx() as c:
            return {r.connection_id: r for r in await rows(c, q, TeamToken)}

    async def tokens(self, tenant_id: str, connection_id: str) -> list[TokenRow]:
        q = connection_tokens.select().where(
            connection_tokens.c.tenant_id == tenant_id,
            connection_tokens.c.connection_id == connection_id,
            team_visible(connection_tokens),
        )
        async with self.tx() as c:
            return await rows(c, q, TokenRow)

    async def put_token(
        self,
        tenant_id: str,
        connection_id: str,
        values: TokenWrite,
        *,
        expected_rotations: int | None,
        person: str = SHARED,
    ) -> bool:
        """Stores a token only if the row is still as it was read: `expected_rotations` None means there was no row (an
        insert, which fails if another caller inserted first), else the rotation read (CAS). False when another caller
        stored first; nothing is written then. No lock is held while the token is fetched."""
        key = self._token_key(tenant_id, connection_id, person)
        async with self.tx() as c:
            if expected_rotations is not None:
                q = connection_tokens.update().where(*key, connection_tokens.c.rotations == expected_rotations)
                stored = (await c.execute(q.values(**values))).rowcount == 1
                # A renewal that keeps a refresh token leaves the team account's state as it was; any other change
                # to the team's token may change its card's.
                if stored and person == SHARED and (_STATE_FIELDS & values.keys() or not values.get("refresh_ct")):
                    await _forget_account_cards(c, tenant_id, connection_id)
                return stored
            try:
                async with self.attempt(c):
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
            if person == SHARED:
                await _forget_account_cards(c, tenant_id, connection_id)
            return True

    async def replace_token(self, tenant_id: str, connection_id: str, values: TokenWrite, person: str = SHARED) -> None:
        """A finished sign-in's token, whatever was held before; a refusal marked on the row before is cleared."""
        key = self._token_key(tenant_id, connection_id, person)
        # A new sign-in starts untested: the test that follows it writes its own outcome.
        values = {"refused_at": None, "refused_reason": None, "ended_by": None, "test": None, **values}
        async with self.tx() as c:
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
            if person == SHARED:
                await _forget_account_cards(c, tenant_id, connection_id)

    async def mark_refused(self, tenant_id: str, connection_id: str, person: str, *, reason: str, at: datetime) -> bool:
        """Marks a person's own row refused by the system; False when they hold none."""
        q = connection_tokens.update().where(*self._token_key(tenant_id, connection_id, person))
        async with self.tx() as c:
            marked = (await c.execute(q.values(refused_at=at, refused_reason=reason[:300]))).rowcount > 0
            if marked and person == SHARED:
                await _forget_account_cards(c, tenant_id, connection_id)
            return marked

    async def used(self, tenant_id: str, connection_id: str, person: str, *, at: datetime) -> bool:
        """Notes that a call signed with this token row: at most one write a minute per row, decided in the UPDATE's
        WHERE, so a burst of calls from several workers writes once. False when nothing was written."""
        t = connection_tokens.c
        q = connection_tokens.update().where(
            *self._token_key(tenant_id, connection_id, person),
            sa.or_(t.last_used_at.is_(None), t.last_used_at < at - USED_EVERY),
        )
        async with self.tx() as c:
            return (await c.execute(q.values(last_used_at=at))).rowcount > 0

    async def end_sign_in(
        self, tenant_id: str, connection_id: str, person: str, *, by: str, at: datetime, event: AuditEvent
    ) -> bool | None:
        """An admin ends a person's own sign-in: the row is marked refused with ENDED_BY_ADMIN, so the person's next
        call asks them to connect, and `event` is written to the account's audit log in the same transaction. True
        when this call ended it, False when it was already ended by an admin (nothing is written), None when the person
        holds no sign-in on the account."""
        if person == SHARED:
            return None
        t = connection_tokens.c
        key = self._token_key(tenant_id, connection_id, person)
        not_ended = sa.or_(t.refused_reason.is_(None), t.refused_reason != ENDED_BY_ADMIN)
        async with self.tx() as c:
            q = connection_tokens.update().where(*key, not_ended, team_visible(connection_tokens))
            done = await c.execute(q.values(refused_at=at, refused_reason=ENDED_BY_ADMIN, ended_by=by[:200]))
            if done.rowcount > 0:
                await self._audit(c, tenant_id, connection_id, event)
                return True
            held = (
                sa.select(sa.func.count()).select_from(connection_tokens).where(*key, team_visible(connection_tokens))
            )
            return False if (await c.execute(held)).scalar_one() else None

    @staticmethod
    def _state_counts(now: datetime) -> tuple[sa.ColumnElement[int], sa.ColumnElement[int], sa.ColumnElement[int]]:
        """Connected, expired and refused as 1 or 0 per token row, as records.person_state reads one row: a CASE, since
        SQL Server sums no predicate."""
        t = connection_tokens.c
        refused = t.refused_at.is_not(None)
        expired = sa.and_(t.refused_at.is_(None), t.expires_at < now, t.refresh_ct.is_(None))
        one = sa.literal(1)
        zero = sa.literal(0)
        return (
            sa.case((sa.or_(refused, expired), zero), else_=one),
            sa.case((expired, one), else_=zero),
            sa.case((refused, one), else_=zero),
        )

    def _team_sign_ins(self, tenant_id: str, team_id: str, apps: Sequence[str]) -> list[sa.ColumnElement[bool]]:
        t, k = connection_tokens.c, connections.c
        where = [
            t.tenant_id == tenant_id,
            t.team_id == team_id,
            t.person_id != SHARED,
        ]
        if apps:
            where.append(k.app_id.in_(list(apps)))
        return where

    async def people_page(
        self, tenant_id: str, team_id: str, q: ListParams, *, apps: Sequence[str], states: Sequence[str], now: datetime
    ) -> tuple[ListPage, dict[str, dict[str, int]], dict[str, str]]:
        """One page of the people who hold their own sign-ins on the team's accounts, grouped, counted by state,
        searched by name and paged in SQL: `apps` keeps their sign-ins to those apps, `states` the people with at least
        one sign-in in any of those states. With the facets, people per app and per state over the search, and the
        name of an account of each app the facet counts."""
        t, k = connection_tokens.c, connections.c
        on = sa.and_(k.tenant_id == t.tenant_id, k.id == t.connection_id)
        connected, expired, refused = self._state_counts(now)
        grouped = (
            sa.select(
                t.person_id.label("person_id"),
                sa.func.max(t.person_name).label("person_name"),
                sa.func.sum(connected).label("connected"),
                sa.func.sum(expired).label("expired"),
                sa.func.sum(refused).label("refused"),
                sa.func.max(t.last_used_at).label("last_used_at"),
            )
            .select_from(connection_tokens.join(connections, on))
            .where(
                *self._team_sign_ins(tenant_id, team_id, apps),
                team_visible(connection_tokens),
                team_visible(connections),
            )
            .group_by(t.person_id)
            .subquery("people")
        )
        g = grouped.c
        held = {"connected": g.connected > 0, "expired": g.expired > 0, "refused": g.refused > 0}
        wanted = [held[s] for s in states if s in held]
        query = sa.select(grouped).where(sa.or_(*wanted)) if wanted else sa.select(grouped)
        by_name = sa.func.lower(sa.func.coalesce(g.person_name, g.person_id))
        plain = q.model_copy(update={"filters": {}, "ids": None, "sort_by": None})
        async with self.tx() as c:
            page = await list_page(
                c, query, plain, search=[g.person_name, g.person_id], default_sort=by_name.asc(), key=(g.person_id,)
            )
            facets, names = await self._people_facets(c, tenant_id, team_id, q.search, now)
        page["data"] = [PersonRow.model_validate(r).model_dump() for r in page["data"]]
        return page, facets, names

    async def _people_facets(
        self, c: AsyncConnection, tenant_id: str, team_id: str, search: str | None, now: datetime
    ) -> tuple[dict[str, dict[str, int]], dict[str, str]]:
        """People per app and per state over the search, each person counted once under each value; and an account's
        name for each app, which names a custom app."""
        t, k = connection_tokens.c, connections.c
        on = sa.and_(k.tenant_id == t.tenant_id, k.id == t.connection_id)
        where = [
            *self._team_sign_ins(tenant_id, team_id, ()),
            team_visible(connection_tokens),
            team_visible(connections),
        ]
        if search:
            where.append(sa.or_(contains(t.person_name, search), contains(t.person_id, search)))
        frm = connection_tokens.join(connections, on)
        per_app = (
            sa.select(k.app_id, sa.func.count(sa.distinct(t.person_id)), sa.func.min(k.name))
            .select_from(frm)
            .where(*where)
            .group_by(k.app_id)
        )
        _, expired, refused = self._state_counts(now)
        state = sa.case((refused == 1, "refused"), (expired == 1, "expired"), else_="connected").label("state")
        pairs = sa.select(t.person_id, state).select_from(frm).where(*where).distinct().subquery()
        per_state = sa.select(pairs.c.state, sa.func.count()).group_by(pairs.c.state)
        apps = [(str(a), int(n), str(name)) for a, n, name in await c.execute(per_app)]
        facets = {
            "app": {a: n for a, n, _ in apps},
            "state": {str(s): int(n) for s, n in await c.execute(per_state)},
        }
        return facets, {a: name for a, _, name in apps}

    async def sign_in_counts(
        self, tenant_id: str, team_id: str, app_ids: Sequence[str], now: datetime
    ) -> dict[str, tuple[int, int, int]]:
        """Each app's people's own sign-ins on the team's accounts, counted as (connected, expired, refused) in one
        GROUP BY: the Apps list's sign-in health."""
        if not app_ids:
            return {}
        t, k = connection_tokens.c, connections.c
        on = sa.and_(k.tenant_id == t.tenant_id, k.id == t.connection_id)
        connected, expired, refused = self._state_counts(now)
        q = (
            sa.select(k.app_id, sa.func.sum(connected), sa.func.sum(expired), sa.func.sum(refused))
            .select_from(connection_tokens.join(connections, on))
            .where(
                *self._team_sign_ins(tenant_id, team_id, app_ids),
                team_visible(connection_tokens),
                team_visible(connections),
            )
            .group_by(k.app_id)
        )
        async with self.tx() as c:
            return {str(a): (int(x), int(y), int(z)) for a, x, y, z in await c.execute(q)}

    async def people_sign_ins(self, tenant_id: str, team_id: str, people: Sequence[str]) -> list[PersonAppSignIn]:
        """Each named person's own sign-ins on the team's accounts, with the account and app each is on, by app then
        account: the rows of one page of Apps > People."""
        if not people:
            return []
        t, k = connection_tokens.c, connections.c
        on = sa.and_(k.tenant_id == t.tenant_id, k.id == t.connection_id)
        q = (
            sa.select(
                t.person_id,
                t.connection_id,
                k.app_id,
                k.account_name,
                k.name.label("connection_name"),
                t.account,
                t.refreshed_at,
                t.expires_at,
                t.refused_at,
                t.refused_reason,
                t.ended_by,
                t.last_used_at,
                # A CASE, not the bare test: SQL Server refuses a predicate as a selected value.
                sa.case((t.refresh_ct.is_not(None), 1), else_=0).label("renews"),
            )
            .select_from(connection_tokens.join(connections, on))
            .where(
                *self._team_sign_ins(tenant_id, team_id, ()),
                team_visible(connection_tokens),
                team_visible(connections),
                t.person_id.in_(list(people)),
            )
            .order_by(k.app_id, k.name, t.connection_id)
        )
        async with self.tx() as c:
            return await rows(c, q, PersonAppSignIn)

    async def name_token(self, tenant_id: str, connection_id: str, person: str, account: str) -> bool:
        """Who a sign-in signed in as, kept on its row when the token answer did not say; False when the row holds a
        name already or there is no row."""
        q = connection_tokens.update().where(
            *self._token_key(tenant_id, connection_id, person), connection_tokens.c.account.is_(None)
        )
        async with self.tx() as c:
            return (await c.execute(q.values(account=account))).rowcount > 0

    async def name_person(self, tenant_id: str, connection_id: str, person: str, name: str) -> bool:
        """The name of the person whose own sign-in the row is, kept each time they sign in; False when no row."""
        q = connection_tokens.update().where(*self._token_key(tenant_id, connection_id, person))
        async with self.tx() as c:
            return (await c.execute(q.values(person_name=name[:200]))).rowcount > 0

    async def set_token_test(self, tenant_id: str, connection_id: str, person: str, test: Json) -> bool:
        """The account's last test on its own row, the team's (SHARED) or a person's; False when it holds none."""
        q = connection_tokens.update().where(*self._token_key(tenant_id, connection_id, person))
        async with self.tx() as c:
            tested = (await c.execute(q.values(test=test))).rowcount > 0
            if tested and person == SHARED:
                await _forget_account_cards(c, tenant_id, connection_id)
            return tested

    async def forget_person(self, tenant_id: str, team_id: str, person: str) -> list[HeldToken]:
        """Deletes every sign-in of `person`'s own on `team_id`'s connections (S14: they
        left the team); the rows deleted (`held_of`). Their sign-ins on another team's connections and the team
        accounts stay."""
        if person == SHARED:
            return []
        t = connection_tokens.c
        q = connection_tokens.delete().where(
            t.tenant_id == tenant_id, t.team_id == team_id, t.person_id == person, team_visible(connection_tokens)
        )
        async with self.tx() as c:
            # Validated here, as `ops_store.rows.rows` reads a select and not the rows a delete returns.
            taken = (await c.execute(q.returning(*_HELD_TOKEN))).mappings()
            return [HeldToken.model_validate(dict(r)) for r in taken]

    async def forget_token(self, tenant_id: str, connection_id: str, person: str = SHARED) -> list[HeldToken]:
        """The token row deleted, empty when there was none (`held_of`)."""
        q = connection_tokens.delete().where(*self._token_key(tenant_id, connection_id, person))
        async with self.tx() as c:
            row = await one(c, q.returning(*_HELD_TOKEN), HeldToken)
            gone = [row] if row is not None else []
            if gone and person == SHARED:
                await _forget_account_cards(c, tenant_id, connection_id)
            return gone

    async def idle_sign_ins(self, tenant_id: str, refreshed_before: datetime, *, limit: int = 500) -> list[IdleSignIn]:
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
        async with self.tx() as c:
            return await rows(c, q, IdleSignIn)

    async def own_sign_ins(self, tenant_id: str, person: str, connection_ids: list[str]) -> list[OwnSignIn]:
        """One person's own sign-ins on these connections (an app's accounts), newest first: which they pinned
        and which the system refused."""
        if not connection_ids:
            return []
        t = connection_tokens.c
        q = (
            sa.select(
                t.connection_id, t.account, t.pinned, t.refreshed_at, t.refused_at, t.test, t.refused_reason, t.ended_by
            )
            .where(
                t.tenant_id == tenant_id,
                t.connection_id.in_(connection_ids),
                t.person_id == person,
                team_visible(connection_tokens),
            )
            .order_by(t.refreshed_at.desc(), t.connection_id)
        )
        async with self.tx() as c:
            return await rows(c, q, OwnSignIn)

    async def pin(self, tenant_id: str, person: str, connection_id: str, connection_ids: list[str]) -> bool:
        """Pins the person's sign-in on `connection_id` as their default among `connection_ids` (one app's accounts),
        unpinning the others in the same transaction, so a person has one default per app. False when they hold no
        sign-in there."""
        t = connection_tokens.c
        mine = (t.tenant_id == tenant_id, t.person_id == person)
        async with self.tx() as c:
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

    async def people(self, tenant_id: str, connection_id: str) -> list[PersonSignIn]:
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
        async with self.tx() as c:
            return await rows(c, q, PersonSignIn)

    async def sign_ins(self, tenant_id: str, connection_ids: list[str]) -> list[SignIn]:
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
                t.person_name,
                t.account,
                t.pinned,
                t.refreshed_at,
                t.expires_at,
                t.refused_at,
                t.test,
                # A CASE, not the bare test: SQL Server refuses a predicate as a selected value.
                sa.case((t.refresh_ct.is_not(None), 1), else_=0).label("renews"),
            )
            .where(
                t.tenant_id == tenant_id,
                t.connection_id.in_(connection_ids),
                t.person_id != SHARED,
                team_visible(connection_tokens),
            )
            .order_by(t.refreshed_at.desc(), t.person_id)
        )
        async with self.tx() as c:
            return await rows(c, q, SignIn)

    async def operation_scopes(self, tenant_id: str, connection_id: str) -> list[str]:
        """Every scope an operation of a module on this connection needs, in a stable order: what the team's
        account asks for when it signs in, since the calls it signs have nobody to ask for more."""
        o, m = module_operations.c, tool_modules.c
        q = (
            sa.select(o.scopes)
            .join(tool_modules, sa.and_(m.tenant_id == o.tenant_id, m.id == o.module_id))
            .where(o.tenant_id == tenant_id, m.connection_id == connection_id, team_modules())
            .order_by(o.module_id, o.position)
        )
        async with self.tx() as c:
            rows = (await c.execute(q)).scalars().all()
        return list(dict.fromkeys(str(x) for r in rows if isinstance(r, list) for x in cast(list[Any], r)))

    async def mine(self, tenant_id: str, team_id: str, person: str) -> list[OwnAccount]:
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
                k.platform_app,
                app_credentials.c.name.label("credential_name"),
                t.account,
                t.scopes,
                t.refreshed_at,
                t.expires_at,
                t.refused_at,
                t.refused_reason,
                t.test,
            )
            .join(connections, sa.and_(k.tenant_id == t.tenant_id, k.id == t.connection_id))
            .outerjoin(app_credentials, sa.and_(_CREDENTIAL_OF, team_visible(app_credentials)))
            .where(
                t.tenant_id == tenant_id,
                k.team_id == team_id,
                t.person_id == person,
                team_visible(connection_tokens),
                team_visible(connections),
            )
            .order_by(k.name, t.connection_id)
        )
        async with self.tx() as c:
            return await rows(c, q, OwnAccount)

    async def connectable(self, tenant_id: str, team_id: str, person: str, kinds: list[str]) -> list[OwnAccount]:
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
                k.platform_app,
                app_credentials.c.name.label("credential_name"),
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
            .outerjoin(app_credentials, sa.and_(_CREDENTIAL_OF, team_visible(app_credentials)))
            .where(
                k.tenant_id == tenant_id,
                k.team_id == team_id,
                k.sign_in != "team",
                k.auth_kind.in_(kinds),
                # Another person's own second account is theirs alone: listed only to whoever signed in to it.
                sa.or_(k.origin.is_(None), k.origin != "person", t.person_id.is_not(None)),
                team_visible(connections),
            )
            .order_by(k.name, k.id)
        )
        async with self.tx() as c:
            return await rows(c, q, OwnAccount)

    # ── Connect links ─────────────────────────────────────────────────────

    async def add_link(self, row: NewLink, *, now: datetime) -> None:
        """A link asking one person to sign in; the tenant's expired links go in the same transaction."""
        async with self.tx() as c:
            await c.execute(
                connect_links.delete().where(
                    connect_links.c.tenant_id == row["tenant_id"], connect_links.c.expires_at < now
                )
            )
            await c.execute(connect_links.insert().values(**row))

    async def take_link(self, tenant_id: str, token_hash: str, *, now: datetime) -> LinkRow | None:
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
        async with self.tx() as c:
            row = (await rows(c, connect_links.select().where(*where).limit(1), LinkRow) or [None])[0]
            if row is None:
                return None
            if (await c.execute(connect_links.update().where(*where).values(used_at=now))).rowcount != 1:
                return None
            return row

    async def link(self, tenant_id: str, token_hash: str) -> LinkRow | None:
        """The link under this hash, used or not, for telling its owner apart from anyone else."""
        k = connect_links.c
        async with self.tx() as c:
            q = connect_links.select().where(
                k.tenant_id == tenant_id, k.token_hash == token_hash, team_visible(connect_links)
            )
            return (await rows(c, q.limit(1), LinkRow) or [None])[0]

    # ── Sign-in states ────────────────────────────────────────────────────

    async def add_state(self, row: NewState, *, now: datetime) -> list[HeldState]:
        """Stores a sign-in in progress; expired ones of the tenant go in the same transaction, so the table holds only
        sign-ins under ten minutes old and the used ones not yet pruned. Returns the expired states (`held_of`)."""
        async with self.tx() as c:
            expired = oauth_states.delete().where(
                oauth_states.c.tenant_id == row["tenant_id"], oauth_states.c.expires_at < now
            )
            taken = (await c.execute(expired.returning(*_HELD_STATE))).mappings()
            pruned = [HeldState.model_validate(dict(r)) for r in taken]
            team = self._team(str(row["tenant_id"]), str(row["connection_id"]))
            await c.execute(oauth_states.insert().values(**row, team_id=team))
        return pruned

    async def state_account(self, tenant_id: str, state_hash: str) -> StateAccount | None:
        """The account and whose token a sign-in's state was sent out for, read without spending it: what the return
        page finishes, which `take_state` then checks and spends. None for an unknown state."""
        s = oauth_states.c
        q = sa.select(s.connection_id, s.token_for).where(
            s.tenant_id == tenant_id, s.state_hash == state_hash, team_visible(oauth_states)
        )
        async with self.tx() as c:
            return (await rows(c, q.limit(1), StateAccount) or [None])[0]

    async def take_state(
        self, tenant_id: str, state_hash: str, *, connection_id: str, person: str, now: datetime
    ) -> StateRow | None:
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
        async with self.tx() as c:
            row = (await rows(c, oauth_states.select().where(*where).limit(1), StateRow) or [None])[0]
            if row is None:
                return None
            if (await c.execute(oauth_states.update().where(*where).values(used_at=now))).rowcount != 1:
                return None
            return row
