"""Connections: create, change, set an environment's settings and secret parts, sign in and out (c-330).

Who may: reading needs `connections.view`, every change and every sign-in `connections.manage`, which admins hold by
default (owner, 2026-10-19); `can()` decides, and a service token holds neither unless its scopes list them. A
connection belongs to the team it was created in; a team sees its own, an all-scope team sees every one, and a record
outside the caller's team answers 404.

Secret parts are written once, from the request that sets them, into the one secret store (`tool_secrets`, named
`CONN_<ID>_<ENV>_<FIELD>`, its `connection_id` set), and never come back: a read says which are set, by whom and when.
"""

from __future__ import annotations

import hashlib
import re
import secrets as random
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode, urlsplit

import httpx

from ops_access import Access
from ops_identity import ActingForPerson, Principal
from ops_policy import Cipher, context_of
from ops_service_kit.errors import Conflict, NotFound, ServiceUnavailable, ValidationFailed
from ops_service_kit.http import page_window, paged
from ops_service_kit.ids import new_id

from ..auth import AppSecret, Authenticator, AuthFailed, Prepared
from ..auth.assertion import SigningError, key_matches, read_certificate
from ..auth.discovery import Discovery
from ..auth.kinds import BY_ID, CERTIFICATE, ENVIRONMENTS, Kind, kind_of, origin, views
from ..auth.pkce import challenge, verifier
from ..auth.tokens import ClientProof, Tokens
from ..egress import EgressDenied, EgressPolicy, for_tenant
from ..executor import transport_failure
from ..modules.directory import Directory
from ..modules.service import Caller
from ..store.connections import SHARED, ConnectionInUse, ConnectionStore, StaleConnection
from ..store.secrets import SecretStore
from .records import status_of

# Where the identity provider sends the browser back: a console page, which hands the code and state to
# `complete_sign_in` under the person's own token.
SIGN_IN_RETURN_PATH = "/connections/sign-in/return"
SIGN_IN_TTL = timedelta(minutes=10)
# How long Test connection waits for the system's answer.
TEST_TIMEOUT_S = 10.0
# The right to sign in your own account on a connection each person signs in to (c-558); see ConnectionService._can.
OWN = "own"
# Settings changes that make a held token wrong for the system: it is dropped, so the next call signs in again.
# (tenant, connection id, token answer) -> environment settings to add, or None; raises ValueError to refuse it.
# tenant, connection, the token answer, and the environment signed in (c-580).
OnToken = Callable[[str, str, dict[str, Any], str], Awaitable[dict[str, Any] | None]]
TOKEN_SETTINGS = (
    "tokenUrl", "clientId", "scopes", "audience", "resource", "authorizeUrl", "clientAuth", "signingCertificate",
    "subject", "scopeIn",
)  # fmt: skip
_NOT_UPPER = re.compile(r"[^A-Z0-9]+")


def _details(i: dict[str, Any]) -> dict[str, Any]:
    """A connection's card details as given (c-580), blanks stored as none."""
    return {
        "category": (str(i.get("category") or "").strip() or None),
        "description": (str(i.get("description") or "").strip() or None),
        "docs_url": (str(i.get("docs_url") or "").strip() or None),
    }


def secret_name(connection_id: str, environment: str, field: str) -> str:
    """The tool_secrets name of one secret part: upper snake case, as every secret name is."""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", field)
    parts = (connection_id, environment, snake)
    return "CONN_" + "_".join(_NOT_UPPER.sub("_", p.upper()).strip("_") for p in parts)


_ENVIRONMENT_LABELS = {"test": "Test", "production": "Production"}


def environment_views() -> list[dict[str, Any]]:
    """Each environment a connection is set for, with its name and whether live runs call it."""
    return [{"id": e, "label": _ENVIRONMENT_LABELS[e], "production": e == "production"} for e in ENVIRONMENTS]


def _iso(at: datetime | None) -> str | None:
    return at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z") if at else None


def connection_rights(p: Principal, action: str, *, security_team: str, what: str = "connections") -> None:
    """`can(connections, action)`: the one check every connection route runs, or Forbidden."""
    Access(security_team=security_team).can(p, "connections", action, what=what)


def _person(who: Caller) -> str:
    """Who started a sign-in: the token's subject and email. Dev header callers share one subject and differ by email,
    so both are kept."""
    p = who.principal
    return f"{p.sub}|{p.email}"[:200] if p is not None else who.name


def _names(env: dict[str, Any] | None) -> dict[str, str]:
    """An environment's secret field to secret name map."""
    return {str(k): str(v) for k, v in cast(dict[Any, Any], (env or {}).get("secrets") or {}).items()}


def _not_found(what: str, code: str) -> NotFound:
    """NotFound with its own code, so a caller can tell why without a 403."""
    e = NotFound(what)
    e.code = code
    return e


def own_key(who: Caller) -> str:
    """The id a person's own sign-in is kept under (c-558), as the acting-for token names them, so the call that acts
    for them finds the row: their verified subject, or `dev:<email>` for the dev header caller (dev mode, no roles),
    whose subject every dev person shares. A platform session from the dev sign-in also says `dev` but holds roles,
    and is keyed by its subject."""
    p = who.principal
    if p is None:
        return f"dev:{who.name}"
    return p.sub if who.verified else f"dev:{p.email}"


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


class ConnectionService:
    def __init__(
        self,
        store: ConnectionStore,
        secrets: SecretStore,
        cipher: Cipher,
        tokens: Tokens,
        directory: Directory,
        *,
        egress: EgressPolicy | None,
        console_url: str | None,
        security_team: str = "team_security",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        discovery: Discovery | None = None,
        auth: Authenticator | None = None,
        http: httpx.AsyncClient | None = None,
        on_token: OnToken | None = None,
        app_secret: AppSecret | None = None,
    ) -> None:
        """`console_url` is where a sign-in returns (`SIGN_IN_RETURN_PATH` on it); without it no sign-in starts.
        `discovery` finds an MCP server's sign-in (c-331); without it no MCP connection is made from an address.
        `auth` and `http` (the egress client) run Test connection, signed in as a call is (c-558); without them none
        runs."""
        self.store = store
        self.secrets = secrets
        self.cipher = cipher
        self.tokens = tokens
        self.dir = directory
        self.egress = egress
        self.console_url = console_url
        self.access = Access(security_team=security_team)
        self.security_team = security_team
        self.clock = clock
        self.discovery = discovery
        self.auth = auth
        self.http = http
        # A plugin's connection reads settings from the token answer (Salesforce's instance_url, c-564).
        self.on_token = on_token
        # A plugin connection on the platform's own OAuth app reads its secret from the account (c-565).
        self.app_secret = app_secret

    # ── Who may ───────────────────────────────────────────────────────────

    def _can(self, who: Caller, action: str, what: str = "connections") -> None:
        if who.principal is None:
            return
        if action == OWN:
            # A person's own sign-in gives the gateway nothing their account in the system does not already hold, and
            # running a tool still needs tools.run: anyone who sees the team's connections or chats may connect.
            if self.access.may(who.principal, "chat", "run"):
                return
            action = "view"
        connection_rights(who.principal, action, security_team=self.security_team, what=what)

    def _event(
        self, who: Caller, action: str, environment: str, detail: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {
            "action": action,
            "environment": environment,
            "actor": who.name,
            "at": self.clock(),
            "detail": detail or {},
        }

    def _sees(self, who: Caller, conn: dict[str, Any]) -> bool:
        """A team reads its own connections only (c-509), an all-scope team included."""
        return conn["team_id"] == who.team.id

    async def _get(self, who: Caller, connection_id: str) -> dict[str, Any]:
        conn = await self.store.get(who.tenant_id, connection_id)
        if conn is None or not self._sees(who, conn):
            raise NotFound(f"Connection {connection_id}")
        return conn

    # ── Views ─────────────────────────────────────────────────────────────

    async def _secret_meta(self, tenant_id: str, team_id: str, names: list[str]) -> dict[str, dict[str, Any]]:
        rows = {r["name"]: r for r in await self.secrets.listed(tenant_id, team_id) if r["name"] in names}
        return rows

    def _environment(
        self, kind: Kind, env: dict[str, Any] | None, meta: dict[str, dict[str, Any]], token: dict[str, Any] | None
    ) -> dict[str, Any]:
        if env is None:
            return {"set": False, "settings": {}, "secrets": {}, "signedIn": None}
        named = _names(env)
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
        settings: dict[str, Any] = dict(env["settings"] or {})
        out: dict[str, Any] = {
            "set": True,
            "settings": settings,
            "secrets": secrets,
            "signedIn": signed,
            "health": env.get("health"),
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
            "name": conn["name"],
            "authKind": kind.id,
            "kindLabel": kind.label,
            "status": status_of(conn, self.clock()),
            "statusDetail": conn.get("status_detail"),
            "teamId": conn["team_id"],
            # No other team uses a team's connection (c-509); kept in the answer for one release.
            "availableTo": [],
            "usedBy": conn.get("used_by") or [],
            "environmentsSet": sorted(conn["environments"]),
            "revision": conn["revision"],
            "updatedAt": _iso(conn["updated_at"]),
            "mayManage": who.principal is None or self.access.may(who.principal, "connections", "manage"),
            "signIn": conn.get("sign_in") or "team",
            "teamBackup": bool(conn.get("team_backup")),
            "health": conn.get("health"),
            "category": conn.get("category"),
            "description": conn.get("description"),
            "docsUrl": conn.get("docs_url"),
        }
        if not detail:
            return out
        envs = cast(dict[str, dict[str, Any]], conn["environments"])
        names = [n for env in envs.values() for n in _names(env).values()]
        meta = await self._secret_meta(who.tenant_id, str(conn["team_id"]), names)
        tokens = {
            str(t["environment"]): t
            for t in await self.store.tokens(who.tenant_id, str(conn["id"]))
            if t["person_id"] == SHARED
        }
        out["environments"] = {
            e: self._environment(kind, conn["environments"].get(e), meta, tokens.get(e)) for e in ENVIRONMENTS
        }
        out["redirectUri"] = self._redirect() if kind.signs_in and self.console_url else None
        mine = own_key(who)
        out["people"] = [
            {
                "personId": p["person_id"],
                "environment": p["environment"],
                "account": p.get("account"),
                "since": _iso(p.get("refreshed_at")),
                "expiresAt": _iso(p.get("expires_at")),
                "scopes": p.get("scopes") or [],
            }
            for p in await self.store.people(who.tenant_id, str(conn["id"]))
            if out["mayManage"] or p["person_id"] == mine
        ]
        out["activity"] = [
            {
                "action": a["action"],
                "environment": a["environment"],
                "actor": a["actor"],
                "at": _iso(a["at"]),
                "detail": a["detail"],
            }
            for a in await self.store.audit(who.tenant_id, str(conn["id"]))
        ]
        return out

    def kinds(self) -> dict[str, Any]:
        return views() | {
            "environments": environment_views(),
            "redirectUri": self._redirect() if self.console_url else None,
        }

    async def list(self, who: Caller, *, page: int, page_size: int, search: str) -> dict[str, Any]:
        self._can(who, "view")
        teams = [who.team.id]
        total = await self.store.count(who.tenant_id, teams, search)
        page, offset = page_window(total, page, page_size)
        rows = await self.store.page(who.tenant_id, teams, search, offset, page_size)
        return paged([await self._view(who, r, detail=False) for r in rows], total, page, page_size)

    async def detail(self, who: Caller, connection_id: str) -> dict[str, Any]:
        self._can(who, "view")
        return await self._view(who, await self._get(who, connection_id), detail=True)

    async def team_rows(self, who: Caller) -> list[dict[str, Any]]:
        """The caller's team's connections as stored, with each environment's row and the modules that use them, for
        the systems grid to join (c-580); secrets stay names, never values."""
        self._can(who, "view")
        teams = [who.team.id]
        return await self.store.page(
            who.tenant_id, teams, "", 0, max(await self.store.count(who.tenant_id, teams, ""), 1)
        )

    def may_manage(self, who: Caller) -> bool:
        return who.principal is None or self.access.may(who.principal, "connections", "manage")

    # ── Changes ───────────────────────────────────────────────────────────

    async def create(self, who: Caller, i: dict[str, Any]) -> dict[str, Any]:
        self._can(who, "manage")
        if i["auth_kind"] not in BY_ID:
            raise ValidationFailed(f"{i['auth_kind']} is not a way to sign in. Pick one of {', '.join(BY_ID)}.")
        name = i["name"].strip()
        if not name:
            raise ValidationFailed("Name the connection.")
        sign_in = str(i.get("sign_in") or "team")
        self._sign_in_fits(BY_ID[i["auth_kind"]], sign_in)
        now = self.clock()
        row = {
            "tenant_id": who.tenant_id,
            "id": new_id("con"),
            "team_id": who.team.id,
            "name": name,
            "auth_kind": i["auth_kind"],
            "available_to": None,
            "sign_in": sign_in,
            "team_backup": False,
            **_details(i),
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
        return await self.detail(who, str(row["id"]))

    async def change(self, who: Caller, connection_id: str, i: dict[str, Any]) -> dict[str, Any]:
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
        values |= {k: v for k, v in _details(i).items() if k in i}
        if (
            values.get("team_backup", conn.get("team_backup"))
            and values.get("sign_in", conn.get("sign_in")) != "person_or_team"
        ):
            raise ValidationFailed("The team account is a backup only when each person signs in, team as backup.")
        await self._write(who, conn, i["revision"], values, detail={"fields": sorted(values)})
        return await self.detail(who, connection_id)

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

    def _checked(self, kind: Kind, settings: dict[str, Any]) -> dict[str, Any]:
        """The environment's plain settings, each a field of the kind or of the client certificate."""
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
        missing = [f.label for f in kind.requires(out) if not f.secret and f.name not in out]
        if missing:
            raise ValidationFailed(f"{kind.label} needs {', '.join(missing)}.")
        for k in ("tokenUrl", "authorizeUrl", "baseUrl"):
            if k in out and urlsplit(str(out[k])).scheme != "https":
                raise ValidationFailed(f"{k} must be an https address.", details={"field": k})
        return out

    async def set_environment(
        self, who: Caller, connection_id: str, environment: str, i: dict[str, Any]
    ) -> dict[str, Any]:
        """One environment's settings and secret parts. A secret part sent replaces the stored one; one left out keeps
        it. Only a person's request reaches here with secret values (`can` refuses a service token's manage)."""
        self._can(who, "manage")
        if environment not in ENVIRONMENTS:
            raise NotFound(f"Environment {environment}")
        conn = await self._get(who, connection_id)
        kind = kind_of(str(conn["auth_kind"]))
        settings = self._checked(kind, dict(i.get("settings") or {}))
        given = cast(dict[str, str], i.get("secret_values") or {})
        values = {k: v for k, v in given.items() if v}
        for k in values:
            f = kind.field(k)
            if f is None or not f.secret:
                raise ValidationFailed(f"{k} is not a secret part of {kind.label}.", details={"field": k})
        before = conn["environments"].get(environment)
        names = _names(before)
        missing = [f.label for f in kind.requires(settings) if f.secret and f.name not in names | values]
        if missing:
            raise ValidationFailed(f"{kind.label} needs {', '.join(missing)} for {environment}.")
        await self._pair_checked(who, conn, before, settings, values)
        names |= {k: secret_name(str(conn["id"]), environment, k) for k in values}
        old = dict(before["settings"] or {}) if before else {}
        status = "healthy" if conn["status"] in ("draft", "needs_reconnect", "error") else conn["status"]
        # The environment row (naming its secrets) lands first, against the revision read; a stale write stores no
        # value. A failure before the values below leaves a name with no value, which a call refuses as SECRET_MISSING
        # and the same PUT again repairs.
        await self._write(
            who,
            conn,
            i["revision"],
            {"status": status, "status_detail": None},
            environment=(environment, settings, names),
            action="secret_set" if values else "changed",
            detail={"settings": sorted(settings), "secrets": sorted(values)},
        )
        now = self.clock()
        for k, v in values.items():
            name = names[k]
            blob = self.cipher.encrypt(v, context=context_of(who.tenant_id, name))
            # A secret part belongs to the connection's team, as the connection does (c-509).
            team = str(conn["team_id"])
            if not await self.secrets.create(
                who.tenant_id, team, name, blob, actor=who.name, at=now, connection_id=str(conn["id"])
            ):
                await self.secrets.rotate(who.tenant_id, team, name, blob, actor=who.name, at=now)
        if any(old.get(k) != settings.get(k) for k in TOKEN_SETTINGS) or {"clientSecret", "signingKey"} & set(values):
            await self.store.forget_token(who.tenant_id, str(conn["id"]), environment)
        return await self.detail(who, connection_id)

    async def _pair_checked(
        self,
        who: Caller,
        conn: dict[str, Any],
        before: dict[str, Any] | None,
        settings: dict[str, Any],
        values: dict[str, str],
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
        if key is None and before is not None:
            key = (await self._held(who, conn, before, ["signingKey"], f"check {conn['name']}")).get("signingKey")
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
        if not deleted:
            raise NotFound(f"Connection {connection_id}")
        for env in cast(dict[str, dict[str, Any]], conn["environments"]).values():
            for name in _names(env).values():
                await self.secrets.delete(who.tenant_id, str(conn["team_id"]), name, actor=who.name, at=self.clock())

    async def connect_mcp(self, who: Caller, i: dict[str, Any]) -> dict[str, Any]:
        """A connection for an MCP server, its sign-in found from the server (c-331): `oauth2_auth_code` with the
        server as `resource`, set for one environment. The bank's registered client when given; else one registered
        with the server when its metadata offers registration; else refused naming what is missing."""
        self._can(who, "manage")
        if self.discovery is None:
            raise ServiceUnavailable("This service has no egress policy, so it reaches no MCP server.")
        url = str(i["server_url"]).strip()
        if urlsplit(url).scheme != "https":
            raise ValidationFailed("Enter the MCP server's https address.")
        environment = str(i.get("environment") or "test")
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
        made = await self.create(who, {"name": i.get("name") or host, "auth_kind": "oauth2_auth_code"})
        scheme, server_host, port = origin(found.resource)
        settings = {
            "baseUrl": f"{scheme}://{server_host}" + ("" if port == 443 else f":{port}"),
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
        return await self.set_environment(who, str(made["id"]), environment, body)

    # ── Sign-in (authorization code with PKCE) ────────────────────────────

    def _redirect(self) -> str:
        if not self.console_url:
            raise ServiceUnavailable("The console's address is not set, so no sign-in can return to it.")
        return self.console_url.rstrip("/") + SIGN_IN_RETURN_PATH

    async def _signs_in(
        self, who: Caller, connection_id: str, environment: str, *, right: str = "manage"
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self._can(who, right)
        if environment not in ENVIRONMENTS:
            raise NotFound(f"Environment {environment}")
        conn = await self._get(who, connection_id)
        if not kind_of(str(conn["auth_kind"])).signs_in:
            raise ValidationFailed(f"{conn['name']} does not sign in with an account.")
        env = conn["environments"].get(environment)
        if env is None:
            raise ValidationFailed(f"Set {conn['name']}'s {environment} settings before signing in.")
        return conn, env

    async def start_sign_in(
        self,
        who: Caller,
        connection_id: str,
        environment: str,
        account: str = "self",
        *,
        scopes: list[str] | None = None,
        hint: str | None = None,
    ) -> dict[str, Any]:
        """The address to send the person's browser to. The sign-in address must be https on a listed host, so the
        console never sends a person somewhere the tenant has not allowed. On a connection each person signs in to,
        the caller signs in their own account (OWN); the team's account needs connections.manage.
        `scopes` are asked for beside the connection's, and `hint` is the email the system's sign-in starts with."""
        found = await self._get(who, connection_id)
        personal = (found.get("sign_in") or "team") != "team" and account == "self"
        conn, env = await self._signs_in(who, connection_id, environment, right=OWN if personal else "manage")
        settings: dict[str, Any] = dict(env["settings"])
        url = str(settings["authorizeUrl"])
        if self.egress is None:
            raise ServiceUnavailable("This service has no egress policy, so it starts no sign-in.")
        try:
            await self.egress.check_url(who.tenant_id, url)
        except EgressDenied as e:
            raise ValidationFailed(f"The sign-in address: {e}", code="egress_denied") from e
        state, secret = random.token_urlsafe(32), verifier()
        redirect = self._redirect()
        now = self.clock()
        # The team's account signs calls nobody can be asked for, so it asks up front for every scope its operations
        # need; a person's own sign-in asks for the connection's and is asked again when an operation needs more.
        needed = [] if personal else await self.store.operation_scopes(who.tenant_id, str(conn["id"]))
        wanted: list[str] = [*str(settings.get("scopes") or "").split(), *(scopes or []), *needed]
        asked = list(dict.fromkeys(wanted))
        await self.store.add_state(
            {
                "tenant_id": who.tenant_id,
                "state_hash": _hash(state),
                "connection_id": conn["id"],
                "environment": environment,
                "person_id": _person(who),
                "token_for": own_key(who) if personal else SHARED,
                "verifier_ct": self.cipher.encrypt(secret, context=context_of(who.tenant_id, f"pkce/{_hash(state)}")),
                "redirect_uri": redirect,
                "expires_at": now + SIGN_IN_TTL,
                "scopes": " ".join(asked),
            },
            now=now,
        )
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
        sep = "&" if urlsplit(url).query else "?"
        return {
            "authorizeUrl": f"{url}{sep}{urlencode(query)}",
            "redirectUri": redirect,
            "expiresAt": _iso(now + SIGN_IN_TTL),
            "connectionId": str(conn["id"]),
        }

    async def complete_sign_in(self, who: Caller, connection_id: str, state: str, code: str) -> dict[str, Any]:
        """Exchanges the code the console was handed. The state is used once, within ten minutes, by the person who
        started it; any other answer is the same refusal, so a guess learns nothing. A person's own sign-in needs OWN,
        the team's connections.manage."""
        self._can(who, OWN)
        taken = await self.store.take_state(
            who.tenant_id, _hash(state), connection_id=connection_id, person=_person(who), now=self.clock()
        )
        if taken is None:
            raise ValidationFailed(
                "This sign-in has expired or was already used. Start it again.", code="sign_in_expired"
            )
        environment = str(taken["environment"])
        token_for = str(taken.get("token_for") or SHARED)
        right = "manage" if token_for == SHARED else OWN
        conn, env = await self._signs_in(who, connection_id, environment, right=right)
        settings: dict[str, Any] = dict(env["settings"])
        proof = await self._client_proof(who, conn, env, f"sign-in {conn['name']}")
        code_verifier = self.cipher.decrypt(
            str(taken["verifier_ct"]), context=context_of(who.tenant_id, f"pkce/{taken['state_hash']}")
        )
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": str(taken["redirect_uri"]),
            "code_verifier": code_verifier,
        }
        if settings.get("resource"):
            form["resource"] = str(settings["resource"])
        try:
            answer = await self.tokens.post(who.tenant_id, str(settings["tokenUrl"]), form, settings, proof)
        except AuthFailed as e:
            await self.store.note(
                who.tenant_id, connection_id, self._event(who, "sign_in_failed", environment, {"code": e.code})
            )
            raise ValidationFailed(f"{conn['name']} did not finish the sign-in: {e}", code="sign_in_failed") from e
        extra: dict[str, Any] = {}
        if self.on_token is not None:
            try:
                extra = await self.on_token(who.tenant_id, connection_id, answer, environment) or {}
            except ValueError as e:
                await self.store.note(
                    who.tenant_id,
                    connection_id,
                    self._event(who, "sign_in_failed", environment, {"code": "token_host"}),
                )
                raise ValidationFailed(f"{conn['name']} did not finish the sign-in: {e}", code="sign_in_failed") from e
        requested = str(taken.get("scopes") or "").split()
        token = await self.tokens.store_answer(
            who.tenant_id, connection_id, environment, answer, token_for, requested=requested
        )
        if token_for == SHARED:
            await self.store.set_status(who.tenant_id, connection_id, "healthy", None)
        if extra:
            # Where Test connection reads, from what the token said (the instance), never typed by a person.
            fresh = await self._get(who, connection_id)
            await self._write(
                who,
                fresh,
                int(fresh["revision"]),
                {},
                environment=(environment, {**settings, **extra}, _names(env)),
                action="changed",
                detail={"settings": sorted(extra)},
            )
        detail = {"account": token.account, **({"own": True} if token_for != SHARED else {})}
        await self.store.note(who.tenant_id, connection_id, self._event(who, "signed_in", environment, detail))
        return await self.detail(who, connection_id)

    async def use_platform_app(
        self, who: Caller, connection_id: str, environment: str, plugin_id: str, settings: dict[str, Any]
    ) -> None:
        """Puts a plugin's connection on the platform's own OAuth app (c-565): the environment's settings, with the mark
        that sends a token exchange to the account's sealed secret, and no client secret of the team's. Only a
        plugin's team switch calls this. The public settings route refuses `platformApp` as a setting no sign-in kind
        has, so no team points a connection at the account's app by hand."""
        self._can(who, "manage")
        conn = await self._get(who, connection_id)
        status = "healthy" if conn["status"] in ("draft", "needs_reconnect", "error") else conn["status"]
        marked = {**settings, "platformApp": plugin_id}
        await self._write(
            who,
            conn,
            int(conn["revision"]),
            {"status": status, "status_detail": None},
            environment=(environment, marked, {}),
            action="changed",
            detail={"settings": sorted(marked)},
        )
        await self.store.forget_token(who.tenant_id, str(conn["id"]), environment)

    async def _client_proof(self, who: Caller, conn: dict[str, Any], env: dict[str, Any], tool: str) -> ClientProof:
        """How the OAuth app proves itself, from the connection's team, each secret's use audited as `tool`: its client
        secret (none for a public client) or the platform app's, and the signing pair when it signs an assertion."""
        settings = dict(env.get("settings") or {})
        held = await self._held(who, conn, env, ["clientSecret", "signingKey"], tool)
        secret = held.get("clientSecret")
        if (app := settings.get("platformApp")) and self.app_secret is not None:
            secret = await self.app_secret(who.tenant_id, str(app))
        cert = settings.get("signingCertificate")
        return ClientProof(secret, held.get("signingKey"), str(cert) if cert else None)

    async def _held(
        self, who: Caller, conn: dict[str, Any], env: dict[str, Any], parts: list[str], tool: str
    ) -> dict[str, str]:
        """The environment's secret parts named, in clear, each use audited as `tool`; a part not held is left out."""
        names = {p: n for p in parts if (n := _names(env).get(p))}
        if not names:
            return {}
        found = await self.secrets.use(
            who.tenant_id, str(conn["team_id"]), list(names.values()), actor=who.name, tool=tool, at=self.clock()
        )
        return {
            p: self.cipher.decrypt(found[n][0], context=context_of(who.tenant_id, n))
            for p, n in names.items()
            if n in found
        }

    async def mine(self, who: Caller) -> list[dict[str, Any]]:
        """The caller's own sign-ins on their team's connections (c-558): Your connections."""
        self._can(who, OWN)
        return [
            {
                "connectionId": str(r["connection_id"]),
                "connection": str(r["name"]),
                "connectionStatus": str(r["status"]),
                "environment": str(r["environment"]),
                "account": r.get("account"),
                "scopes": r.get("scopes") or [],
                "since": _iso(r.get("refreshed_at")),
                "expiresAt": _iso(r.get("expires_at")),
            }
            for r in await self.store.mine(who.tenant_id, who.team.id, own_key(who))
        ]

    async def disconnect(self, who: Caller, connection_id: str, environment: str) -> None:
        """Disconnect (c-558): deletes the caller's own sign-in, so their next call asks them to connect again, after
        ending it at the system's revocation address when the connection has one. A system that refuses or cannot be
        reached does not keep the row; the activity notes whether it was revoked there."""
        self._can(who, OWN)
        if environment not in ENVIRONMENTS:
            raise NotFound(f"Environment {environment}")
        conn = await self._get(who, connection_id)
        mine = own_key(who)
        held = await self.store.token(who.tenant_id, str(conn["id"]), environment, mine)
        if held is None:
            raise NotFound("Your sign-in")
        env = conn["environments"].get(environment)
        settings: dict[str, Any] = dict(env["settings"] or {}) if env else {}
        revoked = False
        if settings.get("revokeUrl"):
            assert env is not None
            proof = await self._client_proof(who, conn, env, f"disconnect {conn['name']}")
            revoked = await self.tokens.revoke(
                who.tenant_id, str(conn["id"]), environment, held, settings=settings, proof=proof
            )
        await self.store.forget_token(who.tenant_id, str(conn["id"]), environment, mine)
        detail = {"own": True, "revoked": revoked}
        await self.store.note(who.tenant_id, str(conn["id"]), self._event(who, "disconnected", environment, detail))

    async def open_link(self, who: Caller, link: str) -> dict[str, Any]:
        """Starts the sign-in a connect link asks for (c-558): only the person it was made for, in its team, once and
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
            str(found["environment"]),
            scopes=str(found["scopes"]).split(),
            hint=str(found["email"]) or None,
        )

    async def test(self, who: Caller, connection_id: str, environment: str, account: str = "self") -> dict[str, Any]:
        """Test connection (c-558): reads the environment's `testPath` signed in as a call would be, with the caller's
        own sign-in (OWN) on a connection each person signs in to, else the team's (connections.manage), and stores
        the result on the connection. Only the team's sign-in decides the connection's status: one person's missing
        or refused sign-in is theirs alone."""
        if environment not in ENVIRONMENTS:
            raise NotFound(f"Environment {environment}")
        conn = await self._get(who, connection_id)
        own = (conn.get("sign_in") or "team") != "team" and account == "self"
        self._can(who, OWN if own else "manage")
        if self.auth is None or self.http is None or self.egress is None:
            raise ServiceUnavailable("This service has no egress policy, so it tests no connection.")
        env = conn["environments"].get(environment)
        if env is None:
            raise ValidationFailed(f"Set {conn['name']}'s {environment} settings before testing it.")
        settings: dict[str, Any] = dict(env["settings"] or {})
        path = str(settings.get("testPath") or "")
        if not path.startswith("/"):
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
            "environment": environment,
            "account": "own" if own else "team",
            "at": _iso(now),
            "by": who.name,
        }
        started = time.perf_counter()
        refused_sign_in = False
        try:
            prepared = await self.auth.prepare(
                probe, environment, tool="test connection", actor=who.name, acting_for=person, team_account=not own
            )
            await self.egress.check_url(who.tenant_id, url)
            res = await self._probe(url, prepared, who.tenant_id)
            if res.status_code == 401 and prepared is not None and prepared.renewable:
                # A token the system no longer takes (expired early, or revoked) is fetched again once, as a tool
                # call's read is (executor.py), so the test reports the sign-in, not a token's age.
                prepared = await self.auth.prepare(
                    probe,
                    environment,
                    tool="test connection",
                    actor=who.name,
                    acting_for=person,
                    team_account=not own,
                    stale_rotation=prepared.rotation,
                )
                res = await self._probe(url, prepared, who.tenant_id)
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
            if res.status_code < 400:
                health["status"] = "ok"
            else:
                message = f"{urlsplit(url).hostname} answered {res.status_code} to the test address."
                health |= {"status": "failed", "code": "UPSTREAM_STATUS", "message": message}
        status: tuple[str, str | None] | None = None
        if not own and conn["status"] != "revoked":
            # A sign-in the system refused was marked needs_reconnect by Authenticator.prepare, after `conn` was read.
            if health["status"] == "ok":
                status = ("healthy", None)
            elif not refused_sign_in and health["code"] != "NOT_SIGNED_IN" and conn["status"] != "needs_reconnect":
                status = ("error", str(health["message"]))
        # The deciding environment is production once it is set, else test (c-580): only its result moves the
        # connection's health and status, so a failing sandbox leaves a working production as it was.
        decides = environment == ("production" if "production" in conn["environments"] else "test")
        await self.store.set_health(who.tenant_id, connection_id, health, status if decides else None, decides=decides)
        detail = {k: health[k] for k in ("status", "account") if k in health} | (
            {"code": health["code"]} if "code" in health else {}
        )
        await self.store.note(who.tenant_id, connection_id, self._event(who, "tested", environment, detail))
        return await self.detail(who, connection_id)

    async def _probe(self, url: str, prepared: Prepared | None, tenant_id: str) -> httpx.Response:
        assert self.http is not None
        return await self.http.get(
            url,
            params=(prepared.params or None) if prepared else None,
            headers=prepared.headers if prepared else None,
            timeout=TEST_TIMEOUT_S,
            extensions=for_tenant(tenant_id, prepared.certificate if prepared else None),
        )

    async def sign_out(self, who: Caller, connection_id: str, environment: str) -> dict[str, Any]:
        await self._signs_in(who, connection_id, environment)
        if await self.store.forget_token(who.tenant_id, connection_id, environment):
            await self.store.note(who.tenant_id, connection_id, self._event(who, "signed_out", environment))
        return await self.detail(who, connection_id)
