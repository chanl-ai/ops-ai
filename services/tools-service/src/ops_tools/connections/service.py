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
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode, urlsplit

from ops_access import Access
from ops_identity import Principal
from ops_policy import Cipher, context_of
from ops_service_kit.errors import Conflict, NotFound, ServiceUnavailable, ValidationFailed
from ops_service_kit.http import page_window, paged
from ops_service_kit.ids import new_id

from ..auth import AuthFailed
from ..auth.discovery import Discovery
from ..auth.kinds import BY_ID, CERTIFICATE, COMMON, ENVIRONMENTS, Kind, kind_of, origin, views
from ..auth.pkce import challenge, verifier
from ..auth.tokens import Tokens
from ..egress import EgressDenied, EgressPolicy
from ..modules.directory import Directory
from ..modules.service import Caller
from ..store.connections import SHARED, ConnectionInUse, ConnectionStore, StaleConnection
from ..store.secrets import SecretStore
from .records import status_of

# Where the identity provider sends the browser back: a console page, which hands the code and state to
# `complete_sign_in` under the person's own token.
SIGN_IN_RETURN_PATH = "/connections/sign-in/return"
SIGN_IN_TTL = timedelta(minutes=10)
# Settings changes that make a held token wrong for the system: it is dropped, so the next call signs in again.
TOKEN_SETTINGS = ("tokenUrl", "clientId", "scopes", "audience", "resource", "authorizeUrl")
_NOT_UPPER = re.compile(r"[^A-Z0-9]+")


def secret_name(connection_id: str, environment: str, field: str) -> str:
    """The tool_secrets name of one secret part: upper snake case, as every secret name is."""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", field)
    parts = (connection_id, environment, snake)
    return "CONN_" + "_".join(_NOT_UPPER.sub("_", p.upper()).strip("_") for p in parts)


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
    ) -> None:
        """`console_url` is where a sign-in returns (`SIGN_IN_RETURN_PATH` on it); without it no sign-in starts.
        `discovery` finds an MCP server's sign-in (c-331); without it no MCP connection is made from an address."""
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

    # ── Who may ───────────────────────────────────────────────────────────

    def _can(self, who: Caller, action: str, what: str = "connections") -> None:
        if who.principal is not None:
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
        return {"set": True, "settings": dict(env["settings"] or {}), "secrets": secrets, "signedIn": signed}

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
        return views()

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

    # ── Changes ───────────────────────────────────────────────────────────

    async def create(self, who: Caller, i: dict[str, Any]) -> dict[str, Any]:
        self._can(who, "manage")
        if i["auth_kind"] not in BY_ID:
            raise ValidationFailed(f"{i['auth_kind']} is not a way to sign in. Pick one of {', '.join(BY_ID)}.")
        name = i["name"].strip()
        if not name:
            raise ValidationFailed("Name the connection.")
        now = self.clock()
        row = {
            "tenant_id": who.tenant_id,
            "id": new_id("con"),
            "team_id": who.team.id,
            "name": name,
            "auth_kind": i["auth_kind"],
            "available_to": None,
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
        await self._write(who, conn, i["revision"], values, detail={"fields": sorted(values)})
        return await self.detail(who, connection_id)

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
        missing = [f.label for f in (*kind.fields, *COMMON) if not f.secret and f.required and f.name not in out]
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
        missing = [f.label for f in kind.fields if f.secret and f.required and f.name not in names | values]
        if missing:
            raise ValidationFailed(f"{kind.label} needs {', '.join(missing)} for {environment}.")
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
        if any(old.get(k) != settings.get(k) for k in TOKEN_SETTINGS) or {"clientSecret"} & set(values):
            await self.store.forget_token(who.tenant_id, str(conn["id"]), environment)
        return await self.detail(who, connection_id)

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
        self, who: Caller, connection_id: str, environment: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self._can(who, "manage")
        if environment not in ENVIRONMENTS:
            raise NotFound(f"Environment {environment}")
        conn = await self._get(who, connection_id)
        if not kind_of(str(conn["auth_kind"])).signs_in:
            raise ValidationFailed(f"{conn['name']} does not sign in with an account.")
        env = conn["environments"].get(environment)
        if env is None:
            raise ValidationFailed(f"Set {conn['name']}'s {environment} settings before signing in.")
        return conn, env

    async def start_sign_in(self, who: Caller, connection_id: str, environment: str) -> dict[str, Any]:
        """The address to send the person's browser to. The sign-in address must be https on a listed host, so the
        console never sends a person somewhere the tenant has not allowed."""
        conn, env = await self._signs_in(who, connection_id, environment)
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
        await self.store.add_state(
            {
                "tenant_id": who.tenant_id,
                "state_hash": _hash(state),
                "connection_id": conn["id"],
                "environment": environment,
                "person_id": _person(who),
                "verifier_ct": self.cipher.encrypt(secret, context=context_of(who.tenant_id, f"pkce/{_hash(state)}")),
                "redirect_uri": redirect,
                "expires_at": now + SIGN_IN_TTL,
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
        if settings.get("scopes"):
            query["scope"] = str(settings["scopes"])
        if settings.get("resource"):
            query["resource"] = str(settings["resource"])
        sep = "&" if urlsplit(url).query else "?"
        return {
            "authorizeUrl": f"{url}{sep}{urlencode(query)}",
            "redirectUri": redirect,
            "expiresAt": _iso(now + SIGN_IN_TTL),
        }

    async def complete_sign_in(self, who: Caller, connection_id: str, state: str, code: str) -> dict[str, Any]:
        """Exchanges the code the console was handed. The state is used once, within ten minutes, by the person who
        started it; any other answer is the same refusal, so a guess learns nothing."""
        self._can(who, "manage")
        taken = await self.store.take_state(
            who.tenant_id, _hash(state), connection_id=connection_id, person=_person(who), now=self.clock()
        )
        if taken is None:
            raise ValidationFailed(
                "This sign-in has expired or was already used. Start it again.", code="sign_in_expired"
            )
        environment = str(taken["environment"])
        conn, env = await self._signs_in(who, connection_id, environment)
        settings: dict[str, Any] = dict(env["settings"])
        secret_name_ = _names(env).get("clientSecret")
        client_secret = None
        if secret_name_:
            found = await self.secrets.use(
                who.tenant_id,
                str(conn["team_id"]),
                [secret_name_],
                actor=who.name,
                tool=f"sign-in {conn['name']}",
                at=self.clock(),
            )
            if secret_name_ in found:
                client_secret = self.cipher.decrypt(
                    found[secret_name_][0], context=context_of(who.tenant_id, secret_name_)
                )
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
            answer = await self.tokens.post(who.tenant_id, str(settings["tokenUrl"]), form, settings, client_secret)
        except AuthFailed as e:
            await self.store.note(
                who.tenant_id, connection_id, self._event(who, "sign_in_failed", environment, {"code": e.code})
            )
            raise ValidationFailed(f"{conn['name']} did not finish the sign-in: {e}", code="sign_in_failed") from e
        token = await self.tokens.store_answer(who.tenant_id, connection_id, environment, answer)
        await self.store.set_status(who.tenant_id, connection_id, "healthy", None)
        await self.store.note(
            who.tenant_id, connection_id, self._event(who, "signed_in", environment, {"account": token.account})
        )
        return await self.detail(who, connection_id)

    async def sign_out(self, who: Caller, connection_id: str, environment: str) -> dict[str, Any]:
        await self._signs_in(who, connection_id, environment)
        if await self.store.forget_token(who.tenant_id, connection_id, environment):
            await self.store.note(who.tenant_id, connection_id, self._event(who, "signed_out", environment))
        return await self.detail(who, connection_id)
