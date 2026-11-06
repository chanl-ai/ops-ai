"""Accounts: create, change their settings and secret parts, sign in and out. An account is one connection.

Who may: reading needs `connections.view`, every change and every sign-in `connections.manage`, which admins hold by
default; `can()` decides, and a service token holds neither unless its scopes list them. A
connection belongs to the team it was created in; a team sees its own, an all-scope team sees every one, and a record
outside the caller's team answers 404.

Secret parts are written once, from the request that sets them, into the one secret store (`tool_secrets`, named
`CONN_<ID>_<FIELD>`, its `connection_id` set), and never come back: a read says which are set, by whom and when. A name
an account already holds is kept when its value is replaced, so a name made before sandboxes keeps working.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets as random
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn, cast
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

from ops_access import Access
from ops_identity import ActingForPerson, Principal
from ops_plugin_sdk.manifest import PLATFORM_AUTHORIZE_PARAMS, SignInError
from ops_policy import CredentialStore
from ops_service_kit.errors import Conflict, NotFound, ServiceUnavailable, Unprocessable, ValidationFailed
from ops_service_kit.ids import new_id
from ops_service_kit.logging import get_logger

from ..auth import Authenticator, AuthFailed, Prepared
from ..auth.assertion import SigningError, key_matches, read_certificate
from ..auth.discovery import Discovery
from ..auth.kinds import BY_ID, CERTIFICATE, Kind, kind_of, views
from ..auth.pkce import challenge, verifier
from ..auth.tokens import SIGNED_IN_AS, ClientProof, Tokens, account_of, person_named
from ..egress import EgressDenied, EgressPolicy, for_tenant
from ..environments import TEST
from ..executor import transport_failure
from ..modules.directory import Directory
from ..modules.service import Caller
from ..secrets import SecretResolver
from ..store.connections import (
    SHARED,
    ConnectionInUse,
    ConnectionStore,
    StaleConnection,
    plugin_app,
    plugin_of,
    verifier_context,
)
from .account_events import connected_event
from .records import status_of

# Where the identity provider sends the browser back: a console page, which hands the code and state to
# `complete_sign_in` under the person's own token.
SIGN_IN_RETURN_PATH = "/connections/sign-in/return"
SIGN_IN_TTL = timedelta(minutes=10)
# Whose token a sign-in's state is for when it is an admin's credential check: nobody's, so none is kept. Not a
# person id or SHARED, so a check's state can never finish as a sign-in.
CHECK = "check"
# How long Test connection waits for the system's answer.
TEST_TIMEOUT_S = 10.0
# The right to sign in your own account on a connection each person signs in to; see ConnectionService._can.
OWN = "own"
# Settings changes that make a held token wrong for the system: it is dropped, so the next call signs in again.
# tenant, account, the token answer, and whether it is a person's own sign-in, which may not change what the
# team's sign-in set -> account settings to add, or None. A ValueError with a `code` names why for the event.
OnToken = Callable[[str, str, dict[str, Any], bool], Awaitable[dict[str, Any] | None]]
# tenant, account, who signed in -> after a finished sign-in: the account's app is turned on for its team.
OnSignedIn = Callable[[str, str, str], Awaitable[None]]
# tenant, account -> the plugin's settings on it as a person may read them.
PluginSettings = Callable[[str, str], Awaitable[dict[str, Any]]]
# tenant, account, the system's error code and description -> what the plugin behind the account says of that refusal,
# or None for an account no plugin serves or a code its plugin does not name.
SignInErrors = Callable[[str, str, str, str | None], Awaitable[SignInError | None]]
# The codes a token exchange answers when the client's secret is wrong: RFC 6749's, and GitHub's own.
WRONG_SECRET = ("invalid_client", "incorrect_client_credentials")
TOKEN_SETTINGS = (
    "tokenUrl", "clientId", "scopes", "audience", "resource", "authorizeUrl", "clientAuth", "signingCertificate",
    "subject", "scopeIn",
)  # fmt: skip
_NOT_UPPER = re.compile(r"[^A-Z0-9]+")


def _details(i: dict[str, Any]) -> dict[str, Any]:
    """A connection's card details as given, blanks stored as none."""
    return {
        "category": (str(i.get("category") or "").strip() or None),
        "description": (str(i.get("description") or "").strip() or None),
        "docs_url": (str(i.get("docs_url") or "").strip() or None),
    }


def secret_name(connection_id: str, field: str) -> str:
    """The tool_secrets name of one secret part: upper snake case, as every secret name is."""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", field)
    parts = (connection_id, snake)
    return "CONN_" + "_".join(_NOT_UPPER.sub("_", p.upper()).strip("_") for p in parts)


def _iso(at: datetime | None) -> str | None:
    return at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z") if at else None


def connection_rights(p: Principal, action: str, *, what: str = "the team's apps") -> None:
    """`can(connections, action)`: the one check every connection route runs, or Forbidden."""
    Access().can(p, "connections", action, what=what)


def _person(who: Caller) -> str:
    """Who started a sign-in: the token's subject and email. Dev header callers share one subject and differ by email,
    so both are kept."""
    p = who.principal
    return f"{p.sub}|{p.email}"[:200] if p is not None else who.name


# How the console names Ops AI's own OAuth app wherever an auth config is named.
OPS_AI_APP = "Ops AI's app"
MCP_LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def is_mcp_server(settings: dict[str, Any]) -> bool:
    """An MCP server added by its address: the token it takes is for the server itself (`resource` is its address),
    as `connect_mcp` sets it."""
    base, resource = str(settings.get("baseUrl") or ""), str(settings.get("resource") or "")
    return bool(base) and base.rstrip("/") == resource.rstrip("/")


def mcp_error(res: httpx.Response) -> str | None:
    """The JSON-RPC error a server answered tools/list with, or None when it listed them. A streamed answer
    (text/event-stream) carries the message on its first `data:` line."""
    text = res.text
    if "text/event-stream" in res.headers.get("content-type", ""):
        text = next((line[5:].strip() for line in text.splitlines() if line.startswith("data:")), "")
    try:
        body = json.loads(text)
    except ValueError:
        return "its answer was not JSON-RPC"
    if not isinstance(body, dict):
        return "its answer was not JSON-RPC"
    answer = cast(dict[str, Any], body)
    error: Any = answer.get("error")
    if isinstance(error, dict):
        return str(cast(dict[str, Any], error).get("message") or "an error")
    if error is not None:
        return str(error)
    return None if "result" in answer else "its answer had no result"


def _names(conn: dict[str, Any] | None) -> dict[str, str]:
    """An account's secret field to secret name map."""
    return {str(k): str(v) for k, v in cast(dict[Any, Any], (conn or {}).get("secrets") or {}).items()}


def _not_found(what: str, code: str) -> NotFound:
    """NotFound with its own code, so a caller can tell why without a 403."""
    e = NotFound(what)
    e.code = code
    return e


def own_key(who: Caller) -> str:
    """The id a person's own sign-in is kept under, as the acting-for token names them, so the call that acts
    for them finds the row: their verified subject, or `dev:<email>` for the dev header caller (dev mode, no roles),
    whose subject every dev person shares. A platform session from the dev sign-in also says `dev` but holds roles,
    and is keyed by its subject."""
    p = who.principal
    if p is None:
        return f"dev:{who.name}"
    return p.sub if who.verified else f"dev:{p.email}"


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


log = get_logger("ops_tools.connections")


class ConnectionService:
    def __init__(
        self,
        store: ConnectionStore,
        secrets: SecretResolver,
        credentials: CredentialStore,
        tokens: Tokens,
        directory: Directory,
        *,
        egress: EgressPolicy | None,
        console_url: str | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        discovery: Discovery | None = None,
        auth: Authenticator | None = None,
        http: httpx.AsyncClient | None = None,
        on_token: OnToken | None = None,
        plugin_settings: PluginSettings | None = None,
        sign_in_errors: SignInErrors | None = None,
        on_signed_in: OnSignedIn | None = None,
    ) -> None:
        """`console_url` is where a sign-in returns (`SIGN_IN_RETURN_PATH` on it); without it no sign-in starts.
        `discovery` finds an MCP server's sign-in; without it no MCP connection is made from an address.
        `auth` and `http` (the egress client) run Test connection, signed in as a call is; without them none
        runs."""
        self.store = store
        self.secrets = secrets
        self.credentials = credentials
        self.tokens = tokens
        self.dir = directory
        self.egress = egress
        self.console_url = console_url
        self.access = Access()
        self.clock = clock
        self.discovery = discovery
        self.auth = auth
        self.http = http
        # A plugin's connection reads settings from the token answer (Salesforce's instance_url).
        self.on_token = on_token
        self.on_signed_in = on_signed_in
        # A plugin's settings on an account as a person may read them (PluginHost.account_settings); without it an
        # account's page shows none.
        self.plugin_settings = plugin_settings
        # What a plugin says of a refused sign-in (PluginHost.sign_in_error); without it the platform's words are said.
        self.sign_in_errors = sign_in_errors
        # A plugin app's title and logo by its app id (PluginHost.display_of), for My accounts; set once the plugin
        # host is up.
        self.app_display: Callable[[str], tuple[str, str | None] | None] | None = None
        # The permissions a plugin account's sign-in asks for, from its team's switched-on tools
        # (PluginHost.sign_in_scopes); set once the plugin host is up.
        self.sign_in_scopes: Callable[[str, str], Awaitable[list[str] | None]] | None = None
        # Tests that run after a sign-in, held so the event loop keeps them until they finish.
        self._after_sign_in: set[asyncio.Task[None]] = set()

    # ── Who may ───────────────────────────────────────────────────────────

    def _can(self, who: Caller, action: str, what: str = "the team's apps") -> None:
        if who.principal is None:
            return
        if action == OWN:
            # A person's own sign-in gives the gateway nothing their account in the system does not already hold, and
            # running a tool still needs tools.run: anyone who sees the team's connections or chats may connect.
            if self.access.may(who.principal, "chat", "run"):
                return
            action = "view"
        connection_rights(who.principal, action, what=what)

    def check(self, who: Caller, action: str, what: str = "the team's apps") -> None:
        """Refuses a caller who may not take `action` on the team's connections, by the same rights every route here
        reads; for an answer joined outside this service, such as the app credentials list."""
        self._can(who, action, what)

    def _event(self, who: Caller, action: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "action": action,
            "actor": who.name,
            "at": self.clock(),
            "detail": detail or {},
        }

    def _sees(self, who: Caller, conn: dict[str, Any]) -> bool:
        """A team reads its own connections only, an all-scope team included."""
        return conn["team_id"] == who.team.id

    async def _get(self, who: Caller, connection_id: str) -> dict[str, Any]:
        conn = await self.store.get(who.tenant_id, connection_id)
        if conn is None or not self._sees(who, conn):
            raise NotFound(f"Connection {connection_id}")
        return conn

    async def account_of(self, who: Caller, app_id: str, account_id: str) -> dict[str, Any]:
        """The team's account under its own app; an account of another app, or another team's, is not found."""
        conn = await self._get(who, account_id)
        if conn["app_id"] != app_id:
            raise NotFound(f"Account {account_id}")
        return conn

    # ── Views ─────────────────────────────────────────────────────────────

    async def _secret_meta(self, tenant_id: str, team_id: str, names: list[str]) -> dict[str, dict[str, Any]]:
        rows = {r["name"]: r for r in await self.secrets.store.listed(tenant_id, team_id) if r["name"] in names}
        return rows

    def _keys(
        self, kind: Kind, conn: dict[str, Any], meta: dict[str, dict[str, Any]], token: dict[str, Any] | None
    ) -> dict[str, Any]:
        """The account's settings, which secret parts are set (by whom and when, never a value), the team's sign-in and
        the signing certificate's view."""
        named = _names(conn)
        secret_fields = [f for f in (*kind.fields, *CERTIFICATE) if f.secret]
        secrets: dict[str, Any] = {}
        for f in secret_fields:
            row = meta.get(named.get(f.name, ""))
            secrets[f.name] = (
                {"set": True, "setBy": row["created_by"], "setAt": _iso(row.get("rotated_at") or row["created_at"])}
                if row
                else {"set": False}
            )
        signed: dict[str, Any] | None = (
            {
                "account": token.get("account"),
                "since": _iso(token["refreshed_at"]),
                "expiresAt": _iso(token.get("expires_at")),
                "scopes": token.get("scopes") or [],
            }
            if token
            else None
        )
        settings: dict[str, Any] = dict(conn["settings"] or {})
        out: dict[str, Any] = {
            "settings": settings,
            "secrets": secrets,
            "signedIn": signed,
            "platformApp": conn.get("platform_app"),
            "credentialId": conn.get("credential_id"),
        }
        if cert := settings.get("signingCertificate"):
            try:
                out["certificate"] = read_certificate(str(cert)).view(self.clock())
            except SigningError:
                out["certificate"] = None
        return out

    async def _view(self, who: Caller, conn: dict[str, Any], *, detail: bool) -> dict[str, Any]:
        kind = BY_ID.get(str(conn["auth_kind"]), BY_ID["none"])
        out: dict[str, Any] = {
            "id": conn["id"],
            "appId": conn["app_id"],
            "name": conn["name"],
            "authKind": kind.id,
            "kindLabel": kind.label,
            "sandbox": bool(conn.get("sandbox")),
            "status": status_of(conn, self.clock()),
            "statusDetail": conn.get("status_detail"),
            "teamId": conn["team_id"],
            "usedBy": conn.get("used_by") or [],
            "revision": conn["revision"],
            "updatedAt": _iso(conn["updated_at"]),
            "mayManage": who.principal is None or self.access.may(who.principal, "connections", "manage"),
            "signIn": conn.get("sign_in") or "team",
            "teamBackup": bool(conn.get("team_backup")),
            "health": conn.get("health"),
            "category": conn.get("category"),
            "description": conn.get("description"),
            "docsUrl": conn.get("docs_url"),
            "accountName": conn.get("account_name"),
        }
        if not detail:
            return out
        meta = await self._secret_meta(who.tenant_id, str(conn["team_id"]), list(_names(conn).values()))
        team = await self.store.token(who.tenant_id, str(conn["id"]), SHARED)
        out |= self._keys(kind, conn, meta, team)
        if self.plugin_settings is not None and plugin_of(conn):
            out |= await self.plugin_settings(who.tenant_id, str(conn["id"]))
        out["redirectUri"] = self._redirect() if kind.signs_in and self.console_url else None
        mine = own_key(who)
        out["people"] = [
            {
                "personId": p["person_id"],
                "account": p.get("account"),
                "since": _iso(p.get("refreshed_at")),
                "expiresAt": _iso(p.get("expires_at")),
                "scopes": p.get("scopes") or [],
            }
            for p in await self.store.people(who.tenant_id, str(conn["id"]))
            if out["mayManage"] or p["person_id"] == mine
        ]
        out["activity"] = [
            {"action": a["action"], "actor": a["actor"], "at": _iso(a["at"]), "detail": a["detail"]}
            for a in await self.store.audit(who.tenant_id, str(conn["id"]))
        ]
        return out

    def kinds(self) -> dict[str, Any]:
        return views() | {"redirectUri": self._redirect() if self.console_url else None}

    async def detail(self, who: Caller, connection_id: str) -> dict[str, Any]:
        self._can(who, "view")
        return await self._view(who, await self._get(who, connection_id), detail=True)

    async def team_rows(self, who: Caller) -> list[dict[str, Any]]:
        """The caller's team's accounts as stored, with the modules that use them, for the Apps grid to join;
        secrets stay names, never values."""
        self._can(who, "view")
        teams = [who.team.id]
        return await self.store.page(
            who.tenant_id, teams, "", 0, max(await self.store.count(who.tenant_id, teams, ""), 1)
        )

    def may_manage(self, who: Caller) -> bool:
        return who.principal is None or self.access.may(who.principal, "connections", "manage")

    # ── Changes ───────────────────────────────────────────────────────────

    async def create(self, who: Caller, i: dict[str, Any]) -> dict[str, Any]:
        """A new account. `plugin_id` makes it an account of that plugin's app; `app_id` another account (a sandbox)
        of a custom app the team has; neither, a custom app of its own, whose first account it is."""
        self._can(who, "manage")
        if i["auth_kind"] not in BY_ID:
            raise ValidationFailed(f"{i['auth_kind']} is not a way to sign in. Pick one of {', '.join(BY_ID)}.")
        name = i["name"].strip()
        if not name:
            raise ValidationFailed("Name the connection.")
        sign_in = str(i.get("sign_in") or "team")
        self._sign_in_fits(BY_ID[i["auth_kind"]], sign_in)
        now = self.clock()
        plugin_id, app_id = i.get("plugin_id"), i.get("app_id")
        if app_id:
            app = await self._get(who, str(app_id))
            if plugin_of(app) is not None or app["app_id"] != app["id"]:
                raise ValidationFailed(f"{app['name']} is not a custom app.", code="not_a_custom_app")
        # An app's account is a connected account, `ca_`; a custom app's first account keeps `con_`.
        connection_id = new_id("ca" if plugin_id or app_id else "con")
        row: dict[str, Any] = {
            "tenant_id": who.tenant_id,
            "id": connection_id,
            "team_id": who.team.id,
            "name": name,
            "app_id": plugin_app(str(plugin_id)) if plugin_id else str(app_id or connection_id),
            "sandbox": bool(i.get("sandbox")),
            "account_name": (str(i.get("account_name") or "").strip() or name) if plugin_id or app_id else None,
            "auth_kind": i["auth_kind"],
            "sign_in": sign_in,
            # "Each person, team account as backup" is the backup on: made with it, a run with nobody behind it signs
            # in as the team at once, rather than only after a later change turns the backup on.
            "team_backup": sign_in == "person_or_team",
            **_details(i),
            "settings": {},
            "secrets": {},
            "status": "draft",
            "status_detail": None,
            "revision": 1,
            "created_by": who.name,
            "created_at": now,
            "updated_by": who.name,
            "updated_at": now,
        }
        if not await self.store.create(row, actor=who.name, at=now):
            raise Conflict("Try again; that connection id was just taken.")
        return await self.detail(who, connection_id)

    async def change(
        self, who: Caller, connection_id: str, i: dict[str, Any], *, plugin_settings: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """The account's name, sign-in, card details, sandbox flag, and its settings and secret parts. A secret part
        sent replaces the stored one; one left out keeps it. Settings merge the same way: one sent replaces the stored
        one, an empty one removes it, one left out keeps it, so setting the team's own client id alone keeps the
        account's addresses. Only a person's request reaches here with secret values (`can` refuses a service token's
        manage). A plugin's turn-on also gives the account's own plugin settings; the public route never does."""
        self._can(who, "manage")
        conn = await self._get(who, connection_id)
        values: dict[str, Any] = {}
        if i.get("name") is not None:
            if not i["name"].strip():
                raise ValidationFailed("Name the connection.")
            values["name"] = i["name"].strip()
        if i.get("sign_in") is not None:
            self._sign_in_fits(kind_of(str(conn["auth_kind"])), str(i["sign_in"]))
            values["sign_in"] = i["sign_in"]
        if i.get("team_backup") is not None:
            values["team_backup"] = bool(i["team_backup"])
        if i.get("sandbox") is not None:
            values["sandbox"] = bool(i["sandbox"])
        values |= {k: v for k, v in _details(i).items() if k in i}
        if (
            values.get("team_backup", conn.get("team_backup"))
            and values.get("sign_in", conn.get("sign_in")) != "person_or_team"
        ):
            raise ValidationFailed("The team account is a backup only when each person signs in, team as backup.")
        sealed: dict[str, str] = {}
        drop = False
        detail: dict[str, Any] = {"fields": sorted(values)}
        action = "changed"
        client: dict[str, Any] | None = None
        if "credential_id" in i:
            client = await self._client_of(who, conn, i["credential_id"])
        if i.get("settings") is not None or i.get("secret_values"):
            keys, sealed, drop = await self._new_keys(
                who, conn, dict(i.get("settings") or {}), dict(i.get("secret_values") or {}), client=client
            )
            values |= keys
            status = "healthy" if conn["status"] in ("draft", "needs_reconnect", "error") else conn["status"]
            values |= {"status": status, "status_detail": None}
            detail |= {"settings": sorted(keys["settings"]), "secrets": sorted(i.get("secret_values") or {})}
            action = "secret_set" if sealed else "changed"
        if client is not None:
            values |= {k: client[k] for k in ("credential_id", "platform_app")}
            detail["credentialId"] = client["credential_id"]
            drop = True
        if plugin_settings is not None:
            values["plugin_settings"] = plugin_settings
        # The row (naming its secrets) lands first, against the revision read; a stale write stores no value. A failure
        # before the values below leaves a name with no value, which a call refuses as SECRET_MISSING and the same
        # request again repairs.
        await self._write(who, conn, i["revision"], values, action=action, detail=detail)
        now = self.clock()
        team = str(conn["team_id"])
        for name, v in sealed.items():
            # A secret part belongs to the connection's team, as the connection does.
            if not await self.secrets.create(
                who.tenant_id, team, name, v, actor=who.name, at=now, connection_id=str(conn["id"])
            ):
                await self.secrets.rotate(who.tenant_id, team, name, v, actor=who.name, at=now)
        if drop:
            await self.tokens.drop(who.tenant_id, await self.store.forget_token(who.tenant_id, str(conn["id"])))
        return await self.detail(who, connection_id)

    async def _new_keys(
        self,
        who: Caller,
        conn: dict[str, Any],
        given: dict[str, Any],
        secret_values: dict[str, str],
        *,
        client: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, str], bool]:
        """The account's settings and secret names after a save, the values to seal by secret name, and whether a held
        token is wrong for the system now (it is dropped, so the next call signs in again). `client`: the OAuth client
        the same save picks (`_client_of`), whose secret counts as held."""
        kind = kind_of(str(conn["auth_kind"]))
        each_person = (conn.get("sign_in") or "team") == "person"
        stored = cast(dict[str, Any], conn.get("settings") or {})
        held = {k: v for k, v in stored.items() if (f := kind.field(k)) and not f.secret}
        # A client the same save picks is the account's client id from now on, though the store keeps it on the
        # credential (or the install), never in the account's settings.
        picked = {"clientId": client["client_id"]} if client is not None else {}
        settings = self._checked(kind, {**held, **given, **picked}, each_person=each_person)
        values = {k: v for k, v in secret_values.items() if v}
        for k in values:
            f = kind.field(k)
            if f is None or not f.secret:
                raise ValidationFailed(f"{k} is not a secret part of {kind.label}.", details={"field": k})
        names = _names(conn)
        needs = kind.requires(settings, each_person=each_person)
        held = names | (client or {}).get("names", {})
        if client is not None and client["platform_app"]:
            # Ops AI's app proves itself with the install's secret, never one the team holds.
            held = held | {"clientSecret": ""}
        missing = [f.label for f in needs if f.secret and f.name not in held | values]
        if missing:
            raise ValidationFailed(f"{kind.label} needs {', '.join(missing)}.")
        await self._pair_checked(who, conn, settings, values)
        names |= {k: names.get(k) or secret_name(str(conn["id"]), k) for k in values}
        row: dict[str, Any] = {"settings": settings, "secrets": names}
        # The platform's app stays through a save of the fields it shows (Edit keys); the team's own client
        # secret, or another client id, puts the account on the team's own app.
        own_app = "clientSecret" in values or stored.get("clientId") != settings.get("clientId")
        if conn.get("platform_app") and own_app:
            row["platform_app"] = None
        drop = any(stored.get(k) != settings.get(k) for k in TOKEN_SETTINGS) or bool(
            {"clientSecret", "signingKey"} & set(values)
        )
        return row, {names[k]: v for k, v in values.items()}, drop

    async def _client_of(self, who: Caller, conn: dict[str, Any], credential_id: str | None) -> dict[str, Any]:
        """The OAuth client an account picks: one of the team's app credentials for the account's app, or with none,
        Ops AI's app for a plugin's account when the install has one. Both columns are written, as a token exchange
        prefers Ops AI's app while `platform_app` is set."""
        if kind_of(str(conn["auth_kind"])).field("clientId") is None:
            raise ValidationFailed(f"{conn['name']} signs in with no OAuth app.", code="no_app_credential")
        if credential_id is None:
            plugin = plugin_of(conn)
            installed = self.store.install_client(plugin) if plugin is not None else None
            if plugin is None or installed is None:
                raise ValidationFailed(
                    f"This install has no app of its own for {conn['name']}; pick one of the team's app credentials.",
                    code="client_missing",
                )
            return {"credential_id": None, "platform_app": plugin, "client_id": installed.id, "names": {}}
        found = await self.store.credential(who.tenant_id, credential_id)
        if found is None or found["team_id"] != conn["team_id"]:
            raise _not_found(f"App credential {credential_id}", "credential_not_found")
        if found["app_id"] != conn["app_id"]:
            raise ValidationFailed(
                f"{found['name']} is another app's credential.", code="credential_other_app",
                details={"field": "credentialId"},
            )  # fmt: skip
        secret = {"clientSecret": str(found["secret_name"])} if found.get("secret_name") else {}
        return {"credential_id": credential_id, "platform_app": None, "client_id": found["client_id"], "names": secret}

    @staticmethod
    def _sign_in_fits(kind: Kind, sign_in: str) -> None:
        if sign_in != "team" and not kind.per_person:
            raise ValidationFailed(f"{kind.label} signs in with the team's account only.", code="sign_in_unsupported")

    async def _write(self, who: Caller, conn: dict[str, Any], revision: int, values: dict[str, Any], **kw: Any) -> None:
        try:
            await self.store.change(
                who.tenant_id, str(conn["id"]), revision, values, actor=who.name, at=self.clock(), **kw
            )
        except StaleConnection as e:
            raise Conflict(
                f"{conn['name']} was changed by someone else. Reload it and try again.", code="stale_version"
            ) from e

    def _checked(self, kind: Kind, settings: dict[str, Any], *, each_person: bool = False) -> dict[str, Any]:
        """The account's plain settings, each a field of the kind or of the client certificate. `each_person`: the
        connection signs in as each person only, so a field each person gives (a username) is not asked of the team."""
        out: dict[str, Any] = {}
        for k, v in settings.items():
            f = kind.field(k)
            if f is None:
                raise ValidationFailed(f"{k} is not a setting of {kind.label}.", details={"field": k})
            if f.secret:
                raise ValidationFailed(f"{f.label} is secret; send it in secretValues.", details={"field": k})
            if v in (None, ""):
                continue
            if not isinstance(v, str):
                raise ValidationFailed(f"{f.label} is text.", details={"field": k})
            if f.choices and v not in f.choices:
                raise ValidationFailed(f"{f.label} must be one of {', '.join(f.choices)}.", details={"field": k})
            out[k] = v
        for f in kind.fields:
            if not f.secret and f.default is not None and f.name not in out:
                out[f.name] = f.default
        missing = [f.label for f in kind.requires(out, each_person=each_person) if not f.secret and f.name not in out]
        if missing:
            raise ValidationFailed(f"{kind.label} needs {', '.join(missing)}.")
        for k in ("tokenUrl", "authorizeUrl", "baseUrl"):
            if k in out and urlsplit(str(out[k])).scheme != "https":
                raise ValidationFailed(f"{k} must be an https address.", details={"field": k})
        return out

    async def _pair_checked(
        self, who: Caller, conn: dict[str, Any], settings: dict[str, Any], values: dict[str, str]
    ) -> None:
        """A signing key saved with a certificate it does not belong to fails every sign-in later, so it is refused
        here; when only the certificate changes, the key held is read (audited) and checked against it."""
        cert = settings.get("signingCertificate")
        if not cert:
            return
        try:
            read_certificate(str(cert))
        except SigningError as e:
            raise ValidationFailed(f"Signing certificate: {e}", details={"field": "signingCertificate"}) from e
        key = values.get("signingKey")
        if key is None:
            key = (await self._held(who, conn, ["signingKey"], f"check {conn['name']}")).get("signingKey")
        if key is None:
            return
        try:
            same = key_matches(key, str(cert))
        except SigningError as e:
            raise ValidationFailed(f"Signing key: {e}", details={"field": "signingKey"}) from e
        if not same:
            raise ValidationFailed(
                "The Signing key does not belong to the Signing certificate; upload the pair together.",
                details={"field": "signingKey"},
            )

    async def delete(self, who: Caller, connection_id: str) -> None:
        self._can(who, "manage")
        conn = await self._get(who, connection_id)
        try:
            deleted = await self.store.delete(who.tenant_id, connection_id, actor=who.name, at=self.clock())
        except ConnectionInUse as e:
            used = ", ".join(e.modules)
            raise Conflict(
                f"{conn['name']} is used by {used}. Point them at another connection first.",
                code="connection_in_use",
                details={"modules": e.modules},
            ) from e
        if deleted is None:
            raise NotFound(f"Connection {connection_id}")
        await self.tokens.drop(who.tenant_id, deleted)
        # The client secret of the app credential it signed in with is the credential's, which outlives the account.
        names = {k: v for k, v in _names(conn).items() if not (k == "clientSecret" and conn.get("credential_id"))}
        for name in names.values():
            await self.secrets.delete(who.tenant_id, str(conn["team_id"]), name, actor=who.name, at=self.clock())

    async def connect_mcp(self, who: Caller, i: dict[str, Any]) -> dict[str, Any]:
        """A connection for an MCP server, its sign-in found from the server: `oauth2_auth_code` with the
        server as `resource`. The bank's registered client when given; else one registered
        with the server when its metadata offers registration; else refused naming what is missing."""
        self._can(who, "manage")
        if self.discovery is None:
            raise ServiceUnavailable("This service has no egress policy, so it reaches no MCP server.")
        url = str(i["server_url"]).strip()
        if urlsplit(url).scheme != "https":
            raise ValidationFailed("Enter the MCP server's https address.")
        try:
            found = await self.discovery.find(who.tenant_id, url)
        except AuthFailed as e:
            raise ValidationFailed(
                str(e), code="egress_denied" if e.code == "EGRESS_DENIED" else "sign_in_not_found"
            ) from e
        host = urlsplit(url).hostname or url
        if found is None:
            raise ValidationFailed(f"{host} answers without sign-in; add it with no connection.", code="no_sign_in")
        client_id, secret = i.get("client_id"), i.get("client_secret")
        if not client_id:
            if found.registration_url is None:
                raise ValidationFailed(
                    f"{host}'s sign-in needs a registered client. Give its client ID and secret.",
                    code="client_required",
                )
            try:
                client_id = await self.discovery.register(
                    who.tenant_id, found.registration_url, self._redirect(), "Ops AI"
                )
            except AuthFailed as e:
                raise ValidationFailed(str(e), code="sign_in_not_found") from e
        made = await self.create(
            who,
            {
                "name": i.get("name") or host,
                "auth_kind": "oauth2_auth_code",
                "app_id": i.get("app_id"),
                "sandbox": i.get("sandbox"),
            },
        )
        settings = {
            # The server's own address, path included: an MCP module's calls go to it, and its sign-in is
            # sent only to its origin.
            "baseUrl": url.rstrip("/"),
            "authorizeUrl": found.authorize_url,
            "tokenUrl": found.token_url,
            "clientId": str(client_id),
            "resource": found.resource,
            **({"scopes": found.scopes} if found.scopes else {}),
        }
        body = {
            "revision": made["revision"],
            "settings": settings,
            "secret_values": {"clientSecret": secret} if secret else {},
        }
        return await self.change(who, str(made["id"]), body)

    # ── Sign-in (authorization code with PKCE) ────────────────────────────

    def _redirect(self) -> str:
        if not self.console_url:
            raise ServiceUnavailable("The console's address is not set, so no sign-in can return to it.")
        return self.console_url.rstrip("/") + SIGN_IN_RETURN_PATH

    async def _signs_in(self, who: Caller, connection_id: str, *, right: str = "manage") -> dict[str, Any]:
        self._can(who, right)
        conn = await self._get(who, connection_id)
        if not kind_of(str(conn["auth_kind"])).signs_in:
            raise ValidationFailed(f"{conn['name']} does not sign in with an account.")
        if not conn["settings"]:
            raise ValidationFailed(f"Set {conn['name']}'s settings before signing in.")
        return conn

    async def start_sign_in(
        self,
        who: Caller,
        connection_id: str,
        account: str = "self",
        *,
        scopes: list[str] | None = None,
        hint: str | None = None,
        check: bool = False,
    ) -> dict[str, Any]:
        """The address to send the person's browser to. The sign-in address must be https on a listed host, so the
        console never sends a person somewhere the tenant has not allowed. On a connection each person signs in to,
        the caller signs in their own account (OWN); the team's account needs connections.manage.
        `scopes` are asked for beside the connection's, and `hint` is the email the system's sign-in starts with.
        `check`: an admin's Test with my account of the app credential, which keeps no token."""
        found = await self._get(who, connection_id)
        personal = (found.get("sign_in") or "team") != "team" and account == "self" and not check
        conn = await self._signs_in(who, connection_id, right=OWN if personal else "manage")
        settings: dict[str, Any] = dict(conn["settings"])
        url = str(settings["authorizeUrl"])
        if self.egress is None:
            raise ServiceUnavailable("This service has no egress policy, so it starts no sign-in.")
        try:
            await self.egress.check_url(who.tenant_id, url, await self.tokens.hosts(who.tenant_id, connection_id))
        except EgressDenied as e:
            raise ValidationFailed(f"The sign-in address: {e}", code="egress_denied") from e
        # The state starts with the account's team, so the return page finishes it in that team whatever the window it
        # lands in remembers; the rest is the secret part, which only the system and this sign-in hold.
        state, secret = f"{conn['team_id']}.{random.token_urlsafe(32)}", verifier()
        redirect = self._redirect()
        now = self.clock()
        # The team's account signs calls nobody can be asked for, so it asks up front for every scope its operations
        # need; a person's own sign-in asks for the connection's and is asked again when an operation needs more.
        needed = [] if personal else await self.store.operation_scopes(who.tenant_id, str(conn["id"]))
        # A plugin's permissions follow the tools its team switched on; any other account asks what its settings list.
        derived = await self.sign_in_scopes(who.tenant_id, str(conn["id"])) if self.sign_in_scopes else None
        listed = derived if derived is not None else str(settings.get("scopes") or "").split()
        wanted: list[str] = [*listed, *(scopes or []), *needed]
        asked = list(dict.fromkeys(wanted))
        expired = await self.store.add_state(
            {
                "tenant_id": who.tenant_id,
                "state_hash": _hash(state),
                "connection_id": conn["id"],
                "person_id": _person(who),
                "token_for": CHECK if check else own_key(who) if personal else SHARED,
                "verifier_ct": await self.credentials.put(
                    secret, context=verifier_context(who.tenant_id, _hash(state))
                ),
                "redirect_uri": redirect,
                "expires_at": now + SIGN_IN_TTL,
                "scopes": " ".join(asked),
            },
            now=now,
        )
        # Expired sign-ins never finished, so their verifiers are read by nobody.
        await self.tokens.drop(who.tenant_id, expired)
        query = {
            "response_type": "code",
            "client_id": str(settings["clientId"]),
            "redirect_uri": redirect,
            "state": state,
            "code_challenge": challenge(secret),
            "code_challenge_method": "S256",
        }
        if asked:
            query["scope"] = " ".join(asked)
        if hint:
            query["login_hint"] = hint
        if settings.get("resource"):
            query["resource"] = str(settings["resource"])
        # A system's own sign-in parameters (Atlassian's audience and prompt); never one the platform sets.
        extra = parse_qsl(str(settings.get("authorizeParams") or ""), keep_blank_values=True)
        query = {**{k: v for k, v in extra if k.lower() not in PLATFORM_AUTHORIZE_PARAMS}, **query}
        sep = "&" if urlsplit(url).query else "?"
        return {
            "authorizeUrl": f"{url}{sep}{urlencode(query)}",
            "redirectUri": redirect,
            "expiresAt": _iso(now + SIGN_IN_TTL),
            "connectionId": str(conn["id"]),
            "appId": str(conn["app_id"]),
        }

    async def _taken(
        self, who: Caller, connection_id: str, state: str, *, check: bool
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """The sign-in `state` started, used once, within ten minutes, by the person who started it, with its
        account. Any other answer is the same refusal, so a guess learns nothing; a credential
        check's state never finishes a sign-in, nor a sign-in's a check, so a check can never replace an account."""
        self._can(who, OWN)
        taken = await self.store.take_state(
            who.tenant_id, _hash(state), connection_id=connection_id, person=_person(who), now=self.clock()
        )
        if taken is None or (str(taken.get("token_for")) == CHECK) != check:
            raise ValidationFailed(
                "This sign-in has expired or was already used. Start it again.", code="sign_in_expired"
            )
        token_for = str(taken.get("token_for") or SHARED)
        right = OWN if token_for not in (SHARED, CHECK) else "manage"
        conn = await self._signs_in(who, connection_id, right=right)
        return taken, conn

    async def _code_answer(self, who: Caller, taken: dict[str, Any], conn: dict[str, Any], code: str) -> dict[str, Any]:
        """The system's token answer for the code, through the account's app; raises AuthFailed."""
        settings: dict[str, Any] = dict(conn["settings"])
        proof = await self._client_proof(who, conn, f"sign-in {conn['name']}")
        # The state was taken once (used_at set), so its verifier is never read again.
        pkce = verifier_context(who.tenant_id, str(taken["state_hash"]))
        code_verifier = await self.credentials.get(str(taken["verifier_ct"]), context=pkce)
        await self.credentials.delete(str(taken["verifier_ct"]), context=pkce)
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": str(taken["redirect_uri"]),
            "code_verifier": code_verifier,
        }
        if settings.get("resource"):
            form["resource"] = str(settings["resource"])
        hosts = await self.tokens.hosts(who.tenant_id, str(conn["id"]))
        return await self.tokens.post(who.tenant_id, str(settings["tokenUrl"]), form, settings, proof, hosts=hosts)

    async def check_credential(self, who: Caller, connection_id: str, state: str, code: str) -> dict[str, Any]:
        """Finishes an admin's Test with my account: the code is exchanged through the account's app, and
        the answer says whether it worked and as whom. No token is kept and the team account is not touched, so a
        check never changes what calls sign in with. A refused exchange is a failed check, answered 200."""
        taken, conn = await self._taken(who, connection_id, state, check=True)
        try:
            answer = await self._code_answer(who, taken, conn, code)
            health = {"status": "ok", "account": account_of(answer)}
        except AuthFailed as e:
            health = {"status": "failed", "account": None, "message": str(e)}
        detail = {"status": health["status"], "account": health["account"]}
        await self.store.note(who.tenant_id, connection_id, self._event(who, "credential_checked", detail))
        return {"health": {**health, "at": _iso(self.clock()), "by": who.name}}

    async def complete_sign_in(self, who: Caller, connection_id: str, state: str, code: str) -> dict[str, Any]:
        """Exchanges the code the console was handed. A person's own sign-in needs OWN, the team's
        connections.manage (`_taken`)."""
        taken, conn = await self._taken(who, connection_id, state, check=False)
        token_for = str(taken.get("token_for") or SHARED)
        settings: dict[str, Any] = dict(conn["settings"])
        try:
            answer = await self._code_answer(who, taken, conn, code)
        except AuthFailed as e:
            if e.provider_error is not None:
                # The system refused the code (a wrong client secret, a code already spent): said as a refusal on the
                # redirect is, by the same table.
                refusal = (e.provider_error, e.provider_description)
                raise await self._refused(who, conn, taken, *refusal, token_exchange=True) from e
            await self.store.note(who.tenant_id, connection_id, self._event(who, "sign_in_failed", {"code": e.code}))
            raise ValidationFailed(f"{conn['name']} did not finish the sign-in: {e}", code="sign_in_failed") from e
        extra: dict[str, Any] = {}
        if self.on_token is not None:
            try:
                extra = await self.on_token(who.tenant_id, connection_id, answer, token_for != SHARED) or {}
            except ValueError as e:
                code = str(getattr(e, "code", "token_host"))
                await self.store.note(who.tenant_id, connection_id, self._event(who, "sign_in_failed", {"code": code}))
                raise ValidationFailed(f"{conn['name']} did not finish the sign-in: {e}", code="sign_in_failed") from e
        requested = str(taken.get("scopes") or "").split()
        named = extra.pop(SIGNED_IN_AS, None)
        token = await self.tokens.store_answer(who.tenant_id, connection_id, answer, token_for, requested=requested)
        if isinstance(named, str):
            await self.store.name_token(who.tenant_id, connection_id, token_for, named)
        if token_for == SHARED:
            await self.store.set_status(who.tenant_id, connection_id, "healthy", None)
        if self.on_signed_in is not None:
            await self.on_signed_in(who.tenant_id, connection_id, who.name)
        if extra:
            # Where Test connection reads, from what the token said (the instance), never typed by a person.
            fresh = await self._get(who, connection_id)
            await self._write(
                who,
                fresh,
                int(fresh["revision"]),
                {"settings": {**dict(fresh["settings"] or {}), **extra}},
                action="changed",
                detail={"settings": sorted(extra)},
            )
        detail = {"account": token.account, **({"own": True} if token_for != SHARED else {})}
        own = connected_event(conn, token_for) if token_for != SHARED else None
        event = self._event(who, "signed_in", detail)
        await self.store.note(who.tenant_id, connection_id, event, report=own)
        now_set = {**settings, **extra}
        if str(now_set.get("testPath") or "").startswith("/") or is_mcp_server(now_set):
            # The sign-in alone connects the account; its test follows without holding the answer, and its outcome
            # is kept on the account's row.
            account = "self" if token_for != SHARED else "team"
            task = asyncio.create_task(self._test_after_sign_in(who, connection_id, account))
            self._after_sign_in.add(task)
            task.add_done_callback(self._after_sign_in.discard)
        return await self.detail(who, connection_id)

    async def finish(
        self, who: Caller, state: str, *, code: str | None, error: str | None, description: str | None
    ) -> dict[str, Any]:
        """The return page's one call: the sign-in its state was sent out for, finished from the state alone, so a
        window with no record of it (another tab, a fresh browser) finishes it too. A sign-in finishes as signed in,
        a Test with my account as its check; a refusal answers 422 sign_in_refused as `refuse_sign_in` says. An
        unknown, used or another person's state is refused as sign_in_expired."""
        found = await self.store.state_account(who.tenant_id, _hash(state))
        if found is None:
            raise ValidationFailed(
                "This sign-in has expired or was already used. Start it again.", code="sign_in_expired"
            )
        connection_id = str(found["connection_id"])
        conn = await self._get(who, connection_id)
        out: dict[str, Any] = {
            "appId": str(conn["app_id"]),
            "accountId": connection_id,
            "check": found["token_for"] == CHECK,
        }
        if out["check"]:
            if code is None:
                message, _ = await self._refusal_words(who, conn, str(error), description, token_exchange=False)
                taken, _ = await self._taken(who, connection_id, state, check=True)
                await self.credentials.delete(
                    str(taken["verifier_ct"]), context=verifier_context(who.tenant_id, str(taken["state_hash"]))
                )
                return out | {
                    "health": {"status": "failed", "message": message, "at": _iso(self.clock()), "by": who.name}
                }
            return out | await self.check_credential(who, connection_id, state, code)
        if code is None:
            await self.refuse_sign_in(who, connection_id, state, str(error), description)
        assert code is not None
        return out | {"account": await self.complete_sign_in(who, connection_id, state, code)}

    async def refuse_sign_in(
        self, who: Caller, connection_id: str, state: str, error: str, description: str | None
    ) -> NoReturn:
        """The system refused the sign-in on its redirect back (`error`, `error_description`): the state is used up as
        a code's would be, so the same refusal cannot be handed back twice, and the refusal is answered and recorded
        as `_refused` says. An unknown, used or another person's state is refused as a code's is."""
        taken, conn = await self._taken(who, connection_id, state, check=False)
        # No code will be exchanged, so the verifier is dropped here; left, it would stay in the vault for good.
        await self.credentials.delete(
            str(taken["verifier_ct"]), context=verifier_context(who.tenant_id, str(taken["state_hash"]))
        )
        raise await self._refused(who, conn, taken, error, description, token_exchange=False)

    async def _refused(
        self,
        who: Caller,
        conn: dict[str, Any],
        taken: dict[str, Any],
        error: str,
        description: str | None,
        *,
        token_exchange: bool,
    ) -> Unprocessable:
        """A refused sign-in: what it means in one plain sentence and who acts on it, recorded on the account (its
        health, and the account read as refused: the team's status, or the person's own sign-in when they hold one)
        and answered as 422 sign_in_refused."""
        message, whose = await self._refusal_words(who, conn, error, description, token_exchange=token_exchange)
        token_for = str(taken.get("token_for") or SHARED)
        own = token_for != SHARED
        now = self.clock()
        health = {
            "status": "failed",
            "account": "own" if own else "team",
            "at": _iso(now),
            "by": who.name,
            "code": "SIGN_IN_REFUSED",
            "message": message,
        }
        connection_id = str(conn["id"])
        await self.store.set_health(who.tenant_id, connection_id, health, None if own else ("needs_reconnect", message))
        if own:
            await self.store.mark_refused(who.tenant_id, connection_id, token_for, reason=message, at=now)
        detail = {"code": error, "who": whose, **({"own": True} if own else {})}
        await self.store.note(who.tenant_id, connection_id, self._event(who, "sign_in_refused", detail))
        app = (await self._app_display(who, str(conn["app_id"]), {**conn, "connection_id": conn["id"]}))[0]
        return Unprocessable(
            message,
            code="sign_in_refused",
            # The app, so the return page's Try again names it.
            details={"message": message, "who": whose, "providerCode": error, "appId": str(conn["app_id"]), "app": app},
        )

    async def _refusal_words(
        self, who: Caller, conn: dict[str, Any], error: str, description: str | None, *, token_exchange: bool
    ) -> tuple[str, str]:
        """The plugin's sentence for this code (its first sign_in_errors entry that matches), else the platform's:
        access not given, a wrong client secret at the token exchange, or the system's own words."""
        app = (await self._app_display(who, str(conn["app_id"]), {**conn, "connection_id": conn["id"]}))[0]
        credential = await self._credential_name(who, conn)
        if token_exchange and error in WRONG_SECRET and not await self._holds_secret(who, conn):
            # Known here, so said before any guess from the system's code: the team's app was never given a secret.
            return f"{credential} has no client secret yet. Add it on its Credentials page.", "admin"
        said = (
            await self.sign_in_errors(who.tenant_id, str(conn["id"]), error, description)
            if self.sign_in_errors is not None
            else None
        )
        if said is not None and said.say and said.who:
            return said.say.replace("{app}", app).replace("{credential}", credential), said.who
        if error == "access_denied":
            return f"{app} access was not given. Connect again to retry.", "person"
        if token_exchange and error in WRONG_SECRET:
            return f"The client secret for {credential} is wrong. Replace it on its Credentials page.", "admin"
        return f"{app} refused the sign-in: {description or error}", "person"

    async def _holds_secret(self, who: Caller, conn: dict[str, Any]) -> bool:
        """Whether the account's OAuth app has a client secret to send: Ops AI's app always does (the install's)."""
        if conn.get("platform_app") or not conn.get("credential_id"):
            return True
        found = await self.store.credential(who.tenant_id, str(conn["credential_id"]))
        return found is None or bool(found.get("secret_name"))

    async def _credential_name(self, who: Caller, conn: dict[str, Any]) -> str:
        """The OAuth app the account signs in with, as the Credentials page names it."""
        if conn.get("credential_id"):
            found = await self.store.credential(who.tenant_id, str(conn["credential_id"]))
            if found is not None:
                return str(found["name"])
        return "Ops AI's app" if conn.get("platform_app") else "the app credential"

    async def change_kind(self, who: Caller, connection_id: str, kind_id: str) -> bool:
        """Moves a custom app's account to another sign-in kind. What it held for the old kind goes: its secret parts,
        its token and each person's sign-in, its app credential and the old kind's fields, so no old key is sent or
        left unseen; the address and test path stay. The account then reads as needing its new sign-in. False when it
        already signs in that way."""
        self._can(who, "manage")
        conn = await self._get(who, connection_id)
        if plugin_of(conn):
            raise ValidationFailed(f"{conn['name']}'s sign-in is its plugin's; it is chosen once.", code="kind_fixed")
        if kind_id not in BY_ID:
            raise ValidationFailed(f"{kind_id} is not a way to sign in. Pick one of {', '.join(BY_ID)}.")
        if conn["auth_kind"] == kind_id:
            return False
        kind = BY_ID[kind_id]
        kept = {k: v for k, v in dict(conn.get("settings") or {}).items() if k in ("baseUrl", "testPath")}
        sign_in = str(conn.get("sign_in") or "team") if kind.per_person else "team"
        values: dict[str, Any] = {
            "auth_kind": kind_id,
            "settings": kept,
            "secrets": {},
            "credential_id": None,
            "platform_app": None,
            "sign_in": sign_in,
            "team_backup": bool(conn.get("team_backup")) and sign_in == "person_or_team",
        }
        await self._write(who, conn, int(conn["revision"]), values, action="changed", detail={"kind": kind_id})
        now = self.clock()
        # A credential's client secret is the credential's, which other accounts may still sign in with.
        for field, name in _names(conn).items():
            if not (field == "clientSecret" and conn.get("credential_id")):
                await self.secrets.delete(who.tenant_id, str(conn["team_id"]), name, actor=who.name, at=now)
        await self.sign_in_again(who, connection_id, f"It signs in with {kind.label} now: set it up and sign in again.")
        return True

    async def sign_in_again(self, who: Caller, connection_id: str, why: str) -> None:
        """Marks an account to sign in again (the app registration it signs in with changed): the team's sign-in is
        dropped and the account reads as needing a reconnect, with `why`; each person's own sign-in is marked refused,
        so their next call asks them to connect again."""
        self._can(who, "manage")
        conn = await self._get(who, connection_id)
        now = self.clock()
        await self.tokens.drop(who.tenant_id, await self.store.forget_token(who.tenant_id, connection_id))
        for p in await self.store.people(who.tenant_id, connection_id):
            await self.store.mark_refused(who.tenant_id, connection_id, str(p["person_id"]), reason=why, at=now)
        await self.store.set_status(who.tenant_id, connection_id, "needs_reconnect", why)
        await self.store.note(who.tenant_id, str(conn["id"]), self._event(who, "credential_changed"))

    async def _test_after_sign_in(self, who: Caller, connection_id: str, account: str) -> None:
        try:
            await self.test(who, connection_id, account)
        except Exception as e:  # a test that cannot run leaves the account connected and untested
            log.warning("test_after_sign_in_failed", connection=connection_id, error=type(e).__name__)

    async def use_platform_app(
        self,
        who: Caller,
        connection_id: str,
        plugin_id: str,
        settings: dict[str, Any],
        *,
        plugin_settings: dict[str, Any] | None = None,
    ) -> None:
        """Puts a plugin's account on Ops AI's own OAuth app: the account's settings, and its
        `platform_app` naming the plugin, whose token exchange uses the install's client (plugin_clients), with no
        client secret of the team's. Only a plugin's team switch calls this: the public settings route has no way to
        name Ops AI's app, so no team points a connection at it by hand."""
        self._can(who, "manage")
        conn = await self._get(who, connection_id)
        status = "healthy" if conn["status"] in ("draft", "needs_reconnect", "error") else conn["status"]
        await self._write(
            who,
            conn,
            int(conn["revision"]),
            {
                "status": status,
                "status_detail": None,
                "settings": settings,
                "secrets": {},
                "platform_app": plugin_id,
                "plugin_settings": plugin_settings,
            },
            action="changed",
            detail={"settings": sorted(settings), "platformApp": plugin_id},
        )
        await self.tokens.drop(who.tenant_id, await self.store.forget_token(who.tenant_id, str(conn["id"])))

    async def _client_proof(self, who: Caller, conn: dict[str, Any], tool: str) -> ClientProof:
        """How the OAuth app proves itself, from the connection's team, each secret's use audited as `tool`: its client
        secret (none for a public client) or the platform app's, and the signing pair when it signs an assertion."""
        settings = dict(conn.get("settings") or {})
        held = await self._held(who, conn, ["clientSecret", "signingKey"], tool)
        secret = held.get("clientSecret")
        if (app := conn.get("platform_app")) and (installed := self.store.install_client(str(app))):
            secret = installed.secret.get_secret_value()
        cert = settings.get("signingCertificate")
        return ClientProof(secret, held.get("signingKey"), str(cert) if cert else None)

    async def _held(self, who: Caller, conn: dict[str, Any], parts: list[str], tool: str) -> dict[str, str]:
        """The account's secret parts named, in clear, each use audited as `tool`; a part not held is left out."""
        names = {p: n for p in parts if (n := _names(conn).get(p))}
        if not names:
            return {}
        found = await self.secrets.present(
            who.tenant_id, str(conn["team_id"]), list(names.values()), actor=who.name, tool=tool, at=self.clock()
        )
        return {p: found[n] for p, n in names.items() if n in found}

    async def mine(self, who: Caller, *, every: bool = False) -> list[dict[str, Any]]:
        """The caller's own sign-ins on their team's connections: Your connections, each with how the person
        signs in and never a value. `every`: also each account of the team a person signs in to that the
        caller has not connected yet, so the page offers its key form or sign-in."""
        self._can(who, OWN)
        mine = own_key(who)
        if every:
            kinds = [k.id for k in BY_ID.values() if k.per_person]
            rows = await self.store.connectable(who.tenant_id, who.team.id, mine, kinds)
        else:
            rows = await self.store.mine(who.tenant_id, who.team.id, mine)
        out: list[dict[str, Any]] = []
        apps: dict[str, tuple[str, str | None]] = {}
        for r in rows:
            kind = kind_of(str(r["auth_kind"]))
            app_id = str(r["app_id"])
            if app_id not in apps:
                apps[app_id] = await self._app_display(who, app_id, r)
            out.append(
                {
                    "connectionId": str(r["connection_id"]),
                    "appId": app_id,
                    "app": apps[app_id][0],
                    "logo": apps[app_id][1],
                    "connection": str(r["name"]),
                    "connectionStatus": str(r["status"]),
                    "sandbox": bool(r.get("sandbox")),
                    "method": kind.label,
                    "authKind": kind.id,
                    "personFields": list(kind.person_fields),
                    "connected": not every or r.get("person_id") is not None,
                    "docsUrl": r.get("docs_url"),
                    "account": r.get("account"),
                    "scopes": r.get("scopes") or [],
                    "since": _iso(r.get("refreshed_at")),
                    "expiresAt": _iso(r.get("expires_at")),
                    "test": r.get("test"),
                    "refused": r.get("refused_at") is not None,
                    "refusedAt": _iso(r.get("refused_at")),
                    "refusedReason": r.get("refused_reason"),
                    "authConfig": OPS_AI_APP if r.get("platform_app") else r.get("credential_name"),
                    "state": (
                        "not_connected"
                        if every and r.get("person_id") is None
                        else "expired"
                        if r.get("refused_at") is not None
                        else "connected"
                    ),
                }
            )
        return out

    async def _app_display(self, who: Caller, app_id: str, row: dict[str, Any]) -> tuple[str, str | None]:
        """An account's app as people know it: a plugin's title and logo, or a custom app's name, which its first
        account carries. The account's own name ("GitHub · Operations") names the account, not the app."""
        shown = self.app_display(app_id) if self.app_display is not None else None
        if shown is not None:
            return shown
        if str(row["connection_id"]) == app_id:
            return str(row["name"]), None
        first = await self.store.get(who.tenant_id, app_id)
        return str((first or row)["name"]), None

    async def give_own(self, who: Caller, connection_id: str, given: dict[str, str]) -> dict[str, Any]:
        """A person's own key, password or token, sealed in their own row: only on a connection each person
        signs in to, with a kind that takes them, every person field given and no other."""
        self._can(who, OWN)
        conn = await self._get(who, connection_id)
        kind = kind_of(str(conn["auth_kind"]))
        if (conn.get("sign_in") or "team") == "team" or not kind.person_fields:
            raise ValidationFailed(
                f"{conn['name']} signs in with the team's account or a sign-in at the system, not your own "
                f"{kind.label.lower()}.",
                code="sign_in_unsupported",
            )
        if not conn["settings"]:
            raise ValidationFailed(f"{conn['name']} is not set up yet; ask its admin to set it.")
        for k, v in given.items():
            if k not in kind.person_fields:
                raise ValidationFailed(f"{k} is not yours to give for {kind.label}.", details={"field": k})
            if len(v) > 2000:
                raise ValidationFailed(f"{k} is longer than 2,000 characters.", details={"field": k})
        missing = [f for f in kind.person_fields if not given.get(f, "").strip()]
        if missing:
            labels = [field.label if (field := kind.field(f)) else f for f in missing]
            raise ValidationFailed(f"{kind.label} needs your {', '.join(labels)}.", details={"field": missing[0]})
        mine = own_key(who)
        values = {f: given[f] for f in kind.person_fields}
        await self.tokens.store_own(who.tenant_id, str(conn["id"]), mine, values)
        detail = {"own": True, "method": kind.id}
        event = self._event(who, "signed_in", detail)
        await self.store.note(who.tenant_id, str(conn["id"]), event, report=connected_event(conn, mine))
        rows = await self.mine(who)
        return next(r for r in rows if r["connectionId"] == str(conn["id"]))

    async def disconnect(self, who: Caller, connection_id: str) -> None:
        """Disconnect: deletes the caller's own sign-in, so their next call asks them to connect again, after
        ending it at the system's revocation address when the connection has one. A system that refuses or cannot be
        reached does not keep the row; the activity notes whether it was revoked there."""
        self._can(who, OWN)
        conn = await self._get(who, connection_id)
        mine = own_key(who)
        held = await self.store.token(who.tenant_id, str(conn["id"]), mine)
        if held is None:
            raise NotFound("Your sign-in")
        settings: dict[str, Any] = dict(conn["settings"] or {})
        revoked = False
        if settings.get("revokeUrl"):
            proof = await self._client_proof(who, conn, f"disconnect {conn['name']}")
            revoked = await self.tokens.revoke(who.tenant_id, str(conn["id"]), held, settings=settings, proof=proof)
        await self.tokens.drop(who.tenant_id, await self.store.forget_token(who.tenant_id, str(conn["id"]), mine))
        detail = {"own": True, "revoked": revoked}
        await self.store.note(who.tenant_id, str(conn["id"]), self._event(who, "disconnected", detail))

    async def open_link(self, who: Caller, link: str) -> dict[str, Any]:
        """Starts the sign-in a connect link asks for: only the person it was made for, in its team, once and
        within fifteen minutes; another person's attempt neither starts a sign-in nor spends the link."""
        found = await self.store.link(who.tenant_id, _hash(link))
        if found is None:
            raise ValidationFailed(
                "This connect link has expired. Ask again for a new one.", code="connect_link_expired"
            )
        if found["person_id"] != own_key(who) or found["team_id"] != who.team.id:
            # As another person's record answers: the link's existence tells them nothing.
            raise _not_found("This connect link", "connect_link_not_yours")
        if await self.store.take_link(who.tenant_id, _hash(link), now=self.clock()) is None:
            raise ValidationFailed(
                "This connect link has expired. Ask again for a new one.", code="connect_link_expired"
            )
        return await self.start_sign_in(
            who,
            str(found["connection_id"]),
            scopes=str(found["scopes"]).split(),
            hint=str(found["email"]) or None,
        )

    async def test(self, who: Caller, connection_id: str, account: str = "self") -> dict[str, Any]:
        """Test connection: reads the account's `testPath` signed in as a call would be, with the caller's
        own sign-in (OWN) on a connection each person signs in to, else the team's (connections.manage), and stores
        the result on the connection. Only the team's sign-in decides the connection's status: one person's missing
        or refused sign-in is theirs alone."""
        conn = await self._get(who, connection_id)
        own = (conn.get("sign_in") or "team") != "team" and account == "self"
        self._can(who, OWN if own else "manage")
        if self.auth is None or self.http is None or self.egress is None:
            raise ServiceUnavailable("This service has no egress policy, so it tests no connection.")
        settings: dict[str, Any] = dict(conn["settings"] or {})
        path = str(settings.get("testPath") or "")
        mcp = is_mcp_server(settings)
        if mcp:
            # An MCP server is tested as its tools use it: it lists them to the account's token. Its address keeps
            # its path, so a test address appended to it would read somewhere else.
            path = ""
        elif not path.startswith("/") and plugin_of(conn):
            # A plugin's test address comes with its sign-in, which names the instance: nobody types one.
            raise ValidationFailed(
                f"Sign {conn['name']} in first: its test reads the system its sign-in names.", code="not_signed_in"
            )
        if not mcp and not path.startswith("/"):
            raise ValidationFailed(
                f"Set {conn['name']}'s test address, a read on the system such as /services/oauth2/userinfo.",
                code="test_path_missing",
            )
        url = str(settings["baseUrl"]).rstrip("/") + path
        probe = {"tenant_id": who.tenant_id, "connection_id": conn["id"], "team_id": conn["team_id"], "endpoint": url}
        person = (
            ActingForPerson(
                sub=own_key(who),
                email=who.principal.email if who.principal else who.name,
                name=who.name,
                team_id=who.team.id,
            )
            if own
            else None
        )
        now = self.clock()
        health: dict[str, Any] = {
            "account": "own" if own else "team",
            "at": _iso(now),
            "by": who.name,
        }
        started = time.perf_counter()
        refused_sign_in = False
        try:
            # A test reads the account it names, a sandbox one too: it signs in as a test run's call would.
            prepared = await self.auth.prepare(
                probe, TEST, tool="test connection", actor=who.name, acting_for=person, team_account=not own
            )
            hosts = await self.tokens.hosts(who.tenant_id, connection_id)
            await self.egress.check_url(who.tenant_id, url, hosts)
            res = await self._probe(url, prepared, who.tenant_id, hosts, mcp=mcp)
            if res.status_code == 401 and prepared is not None and prepared.renewable:
                # A token the system no longer takes (expired early, or revoked) is fetched again once, as a tool
                # call's read is (executor.py), so the test reports the sign-in, not a token's age.
                prepared = await self.auth.prepare(
                    probe,
                    TEST,
                    tool="test connection",
                    actor=who.name,
                    acting_for=person,
                    team_account=not own,
                    stale_rotation=prepared.rotation,
                )
                res = await self._probe(url, prepared, who.tenant_id, mcp=mcp)
        except AuthFailed as e:
            health |= {"status": "failed", "code": e.code, "message": str(e)}
            refused_sign_in = e.side == "upstream"
        except EgressDenied as e:
            health |= {"status": "failed", "code": "EGRESS_DENIED", "message": str(e)}
        except httpx.HTTPError as e:
            # Named by the phase that failed, as a tool call's are: a refused certificate reads TLS_FAILED here too.
            failed = transport_failure(urlsplit(url).hostname, e, int(TEST_TIMEOUT_S * 1000)).output["error"]
            health |= {"status": "failed", "code": failed["code"], "message": failed["message"]}
        else:
            health["latencyMs"] = round((time.perf_counter() - started) * 1000)
            health["httpStatus"] = res.status_code
            refusal = mcp_error(res) if mcp and res.status_code < 400 else None
            if refusal is not None:
                health |= {
                    "status": "failed",
                    "code": "UPSTREAM_STATUS",
                    "message": f"The server refused to list its tools: {refusal}",
                }
            elif res.status_code < 400:
                health["status"] = "ok"
                # A test read often names who signed in (GitHub's /user: login), kept when the sign-in did not.
                try:
                    named = person_named(res.json())
                except ValueError:
                    named = None
                if named:
                    await self.store.name_token(who.tenant_id, connection_id, own_key(who) if own else SHARED, named)
            else:
                message = f"{urlsplit(url).hostname} answered {res.status_code} to the test address."
                health |= {"status": "failed", "code": "UPSTREAM_STATUS", "message": message}
                if res.status_code == 401 and person is not None and prepared is not None and prepared.person:
                    # The person's own key, refused: marked on their row as a call's refusal is.
                    await self.auth.refused(probe, prepared, person, message)
        status: tuple[str, str | None] | None = None
        if not own and conn["status"] != "revoked":
            # A sign-in the system refused was marked needs_reconnect by Authenticator.prepare, after `conn` was read.
            if health["status"] == "ok":
                status = ("healthy", None)
            elif not refused_sign_in and health["code"] != "NOT_SIGNED_IN" and conn["status"] != "needs_reconnect":
                status = ("error", str(health["message"]))
        await self.store.set_health(who.tenant_id, connection_id, health, status)
        # Also on the tested account's own row, so one person's test never reads as the team's or another's.
        outcome = {"status": health["status"], "message": health.get("message"), "at": health["at"]}
        await self.store.set_token_test(who.tenant_id, connection_id, own_key(who) if own else SHARED, outcome)
        detail = {k: health[k] for k in ("status", "account") if k in health} | (
            {"code": health["code"]} if "code" in health else {}
        )
        await self.store.note(who.tenant_id, connection_id, self._event(who, "tested", detail))
        return await self.detail(who, connection_id)

    async def _probe(
        self, url: str, prepared: Prepared | None, tenant_id: str, hosts: list[str] | None = None, *, mcp: bool = False
    ) -> httpx.Response:
        assert self.http is not None
        if mcp:
            return await self.http.post(
                url,
                json=MCP_LIST_TOOLS,
                headers={**(prepared.headers if prepared else {}), "Accept": "application/json, text/event-stream"},
                timeout=TEST_TIMEOUT_S,
                extensions=for_tenant(tenant_id, prepared.certificate if prepared else None, hosts or ()),
            )
        return await self.http.get(
            url,
            params=(prepared.params or None) if prepared else None,
            headers=prepared.headers if prepared else None,
            timeout=TEST_TIMEOUT_S,
            extensions=for_tenant(tenant_id, prepared.certificate if prepared else None, hosts or ()),
        )

    async def pin_default(self, who: Caller, connection_id: str) -> dict[str, Any]:
        """Makes the caller's own sign-in on this account their default among the app's accounts: a call
        naming no account uses it. Refused on an account they have not signed in to."""
        conn = await self._get(who, connection_id)
        accounts = await self.store.accounts(who.tenant_id, str(conn["team_id"]), str(conn["app_id"]))
        ids = [str(a["id"]) for a in accounts]
        if not await self.store.pin(who.tenant_id, own_key(who), connection_id, ids):
            raise ValidationFailed(f"Sign in to {conn['name']} first.", code="not_signed_in")
        return await self.detail(who, connection_id)

    async def sign_out(self, who: Caller, connection_id: str) -> dict[str, Any]:
        await self._signs_in(who, connection_id)
        forgotten = await self.store.forget_token(who.tenant_id, connection_id)
        await self.tokens.drop(who.tenant_id, forgotten)
        if forgotten:
            await self.store.note(who.tenant_id, connection_id, self._event(who, "signed_out"))
        return await self.detail(who, connection_id)
