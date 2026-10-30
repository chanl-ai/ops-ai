"""How a call signs in: the module's connection, the call's environment, and the strategy its auth kind names.

The executor asks `Authenticator.prepare` for every operation of a module that has a connection and adds what comes
back (headers, query values, a client certificate) to the request; the values it resolved join the call's scrub set.
Strategies are a table keyed by kind (`STRATEGIES`), so no tool or operation carries its own branch, and a kind is a row
in `kinds.KINDS` plus one entry here.

Which environment a call uses is the run's: live runs use production, everything else uses test (owner,
2026-10-19). A connection record with no environment set at all is an older integration record (the dev seed's); it
adds nothing and the operation's own headers apply as before. Once any environment is set, a call in an environment
that is not set is refused rather than sent without its credential.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from ops_identity import ActingForPerson

from ..secrets import SecretMissing, SecretResolver
from ..store.connections import SHARED, ConnectionStore
from .assertion import SigningError, read_certificate
from .kinds import TEST, Kind, kind_of, origin
from .tokens import AuthFailed, ClientProof, Tokens, scope_list

# The account's own OAuth app secret for a plugin (c-565): (tenant, plugin id) to the value, or None.
AppSecret = Callable[[str, str], Awaitable[str | None]]

if TYPE_CHECKING:
    from ..connections.connect_links import ConnectLinks

__all__ = ["STRATEGIES", "AuthFailed", "Authenticator", "ClientCertificate", "Prepared", "Tokens"]


@dataclass(frozen=True)
class ClientCertificate:
    """What the egress transport uses on the TLS handshake: a client certificate to present and a CA to trust for the
    system's own certificate, either or both. `fingerprint` keys the connection pool, so a certificate is never
    presented on another connection's calls and a replaced one opens new connections."""

    fingerprint: str
    cert_pem: str | None = None
    key_pem: str | None = None
    ca_pem: str | None = None


# Whose sign-in signed the call this task is running (person or team), for the gateway's call log (c-558): the
# executor answers with the operation's outcome only, so the authenticator leaves it here.
SIGNED_WITH: ContextVar[str | None] = ContextVar("ops_tools_signed_with", default=None)


@dataclass
class Prepared:
    connection_id: str
    environment: str
    headers: dict[str, str] = field(default_factory=dict[str, str])
    params: dict[str, str] = field(default_factory=dict[str, str])
    certificate: ClientCertificate | None = None
    # Every value resolved for this call (secret parts, tokens): what the caller scrubs from everything it returns.
    values: list[str] = field(default_factory=list[str])
    # The rotation of the token sent, so a 401 replaces that token and no newer one.
    rotation: int | None = None
    # The kind holds a token the gateway can get again: a read refused with 401 is retried once.
    renewable: bool = False
    # Whose sign-in signed the call, for the call log: person or team; None for a kind that holds no token (c-558).
    credential: str | None = None


@dataclass(frozen=True)
class StrategyInput:
    tenant_id: str
    connection_id: str
    environment: str
    settings: dict[str, Any]
    secrets: dict[str, str]
    tokens: Tokens
    stale_rotation: int | None
    # Whose token row a token-holding kind uses: SHARED for the team's, a person's id for their own (c-558).
    person: str = SHARED


Strategy = Callable[[StrategyInput, Prepared], Awaitable[None]]


async def _none(_i: StrategyInput, _p: Prepared) -> None:
    return None


async def _api_key(i: StrategyInput, p: Prepared) -> None:
    name = str(i.settings.get("name") or "X-Api-Key")
    if i.settings.get("placement") == "query":
        p.params[name] = i.secrets["key"]
    else:
        p.headers[name] = i.secrets["key"]


async def _basic(i: StrategyInput, p: Prepared) -> None:
    pair = f"{i.settings.get('username') or ''}:{i.secrets['password']}".encode()
    encoded = base64.b64encode(pair).decode()
    p.headers["Authorization"] = f"Basic {encoded}"
    # An upstream that repeats the header shows the encoded pair, not the password.
    p.values.append(encoded)


async def _bearer(i: StrategyInput, p: Prepared) -> None:
    prefix = str(i.settings.get("prefix") if i.settings.get("prefix") is not None else "Bearer").strip()
    p.headers["Authorization"] = f"{prefix} {i.secrets['token']}".strip()


def _unexpired(cert: str) -> None:
    """An expired signing certificate is refused before any request, as the system's side, so a team connection is
    marked as needing a new certificate rather than read as broken."""
    try:
        info = read_certificate(cert)
    except SigningError as e:
        raise AuthFailed("CONNECTION_NOT_SET", f"Signing certificate: {e}") from e
    if info.expired(datetime.now(UTC)):
        day = info.not_after.date().isoformat()
        raise AuthFailed("AUTH_FAILED", f"The signing certificate expired on {day}; upload a new one.", side="upstream")


def _token_strategy(grant: str) -> Strategy:
    async def apply(i: StrategyInput, p: Prepared) -> None:
        cert = i.settings.get("signingCertificate")
        if cert and (grant == "jwt_bearer" or i.settings.get("clientAuth") == "private_key_jwt"):
            _unexpired(str(cert))
        proof = ClientProof(i.secrets.get("clientSecret"), i.secrets.get("signingKey"), str(cert) if cert else None)
        try:
            token = await i.tokens.access(
                i.tenant_id,
                i.connection_id,
                i.environment,
                i.settings,
                proof,
                grant=grant,
                stale_rotation=i.stale_rotation,
                person=i.person,
            )
        finally:
            # An assertion signed for a refused request is scrubbed too.
            p.values.extend(proof.signed)
        p.headers["Authorization"] = f"Bearer {token.access}"
        p.values.append(token.access)
        p.rotation, p.renewable = token.rotation, True

    return apply


STRATEGIES: dict[str, Strategy] = {
    "none": _none,
    "api_key": _api_key,
    "basic": _basic,
    "bearer": _bearer,
    "oauth2_client_credentials": _token_strategy("client_credentials"),
    # Only a person starts this sign-in; the gateway refreshes it and never starts one.
    "oauth2_auth_code": _token_strategy("none"),
    "oauth2_jwt_bearer": _token_strategy("jwt_bearer"),
}


def certificate_of(settings: dict[str, Any], secrets: dict[str, str]) -> ClientCertificate | None:
    """The environment's TLS settings: a client certificate (both its PEM and its private key) and a CA to trust."""
    cert, key, ca = settings.get("clientCertificate"), secrets.get("clientKey"), settings.get("trustedCa")
    if not cert or not key:
        cert = key = None
    if not cert and not ca:
        return None
    digest = hashlib.sha256(f"{cert or ''}\0{key or ''}\0{ca or ''}".encode()).hexdigest()
    return ClientCertificate(digest, str(cert) if cert else None, key, str(ca) if ca else None)


def may_use(connection: dict[str, Any], team_id: str | None) -> bool:
    """A connection serves its own team's modules only (c-509): another team that needs the system holds its own
    connection, with its own sign-in."""
    return team_id is not None and connection["team_id"] == team_id


class Authenticator:
    def __init__(
        self,
        connections: ConnectionStore,
        secrets: SecretResolver | None,
        tokens: Tokens,
        links: ConnectLinks | None = None,
        app_secret: AppSecret | None = None,
    ) -> None:
        self.connections = connections
        self.secrets = secrets
        self.tokens = tokens
        # A plugin connection on the platform's own OAuth app reads its secret from the account, never a team.
        self.app_secret = app_secret
        # Makes the link a call hands back when the person it acts for has not signed in (c-558).
        self.links = links

    async def prepare(
        self,
        module: dict[str, Any],
        environment: str | None,
        *,
        tool: str,
        actor: str,
        stale_rotation: int | None = None,
        acting_for: ActingForPerson | None = None,
        team_account: bool = False,
        needs_person: bool = False,
        scopes: Sequence[str] = (),
    ) -> Prepared | None:
        """What the module's connection adds to a call in `environment` (test when None); None for a module with no
        connection or one whose record has no environment set. Raises AuthFailed when the call cannot be signed in.
        `acting_for` is the verified person the call acts for; on a connection each person signs in to, their own
        sign-in signs the call, and a person who has none gets CONNECTION_NOT_LINKED with a link made for them.
        `team_account` signs with the team's sign-in whatever the setting: an admin's Test connection of it only.
        `needs_person`: the operation is signed in only as a person, never with the team backup. `scopes`: the ones a
        person's own sign-in must hold for the operation; one lacking any gets CONNECTION_NOT_LINKED with reason
        insufficient_scope and a link asking for them beside those it has."""
        connection_id = module.get("connection_id")
        if not connection_id:
            return None
        tenant_id = str(module["tenant_id"])
        env = environment or TEST
        conn = await self.connections.get(tenant_id, str(connection_id))
        if conn is None:
            raise AuthFailed("CONNECTION_MISSING", "This module's connection no longer exists.")
        if not conn["environments"]:
            return None
        name = conn["name"]
        if not may_use(conn, module.get("team_id")):
            raise AuthFailed("CONNECTION_OUT_OF_SCOPE", f"{name} is not available to this module's team.")
        if conn["status"] == "revoked":
            raise AuthFailed("CONNECTION_REVOKED", f"{name} is revoked; reconnect it before tools use it.")
        setting = conn["environments"].get(env)
        if setting is None:
            raise AuthFailed("CONNECTION_NOT_SET", f"{name} is not set for {env}; set it before tools use it there.")
        # A credential goes to its own system only: the module's address must be the connection's, scheme, host and
        # port, before any secret is read; another allow-listed host gets nothing.
        plain: dict[str, Any] = dict(setting["settings"] or {})
        base = str(plain.get("baseUrl") or "")
        target = str(module.get("endpoint") or "")
        if not base:
            raise AuthFailed("CONNECTION_NOT_SET", f"{name} names no system address for {env}.")
        if origin(target) != origin(base):
            raise AuthFailed(
                "CONNECTION_HOST_MISMATCH",
                f"{name} signs in to {urlsplit(base).hostname} only; this module calls {urlsplit(target).hostname}.",
            )
        names: dict[str, str] = dict(setting["secrets"] or {})
        values = await self._secret_values(tenant_id, str(conn["team_id"]), names, tool=tool, actor=actor)
        if (app := plain.get("platformApp")) and self.app_secret is not None:
            found = await self.app_secret(tenant_id, str(app))
            if found is not None:
                values = {**values, "clientSecret": found}
        prepared = Prepared(str(connection_id), env, values=list(values.values()))
        kind = kind_of(str(conn["auth_kind"]))
        missing = [f.label for f in kind.requires(plain) if f.secret and f.name not in values]
        if missing:
            raise AuthFailed("CONNECTION_NOT_SET", f"{name} has no {', '.join(missing)} for {env}.")
        settings = plain
        person = SHARED if team_account else self._whose(conn, kind, acting_for, needs_person)
        if person != SHARED and acting_for is not None and scopes:
            held = await self.connections.token(tenant_id, str(connection_id), env, person)
            granted = scope_list((held or {}).get("scopes"))
            if held is not None and not set(scopes) <= set(granted):
                raise await self._not_linked(
                    conn, env, acting_for, settings, scopes=[*granted, *scopes], reason="insufficient_scope"
                )
        given = StrategyInput(
            tenant_id, str(connection_id), env, settings, values, self.tokens, stale_rotation, person=person
        )
        try:
            await STRATEGIES[kind.id](given, prepared)
        except AuthFailed as e:
            if person != SHARED and acting_for is not None and e.code == "NOT_SIGNED_IN":
                raise await self._not_linked(conn, env, acting_for, settings, scopes=list(scopes)) from e
            if e.side == "upstream":
                # The system refused the sign-in. The team's: the connection needs a person, and its activity says
                # when and why. A person's own: only that person's sign-in is spent, everyone else's keeps working.
                if person == SHARED:
                    await self.connections.set_status(tenant_id, str(connection_id), "needs_reconnect", str(e))
                else:
                    await self.connections.forget_token(tenant_id, str(connection_id), env, person)
                event = {"action": "refresh_failed", "environment": env, "actor": actor, "at": datetime.now(UTC)}
                detail = {"code": e.code, **({"own": True} if person != SHARED else {})}
                await self.connections.note(tenant_id, str(connection_id), {**event, "detail": detail})
            raise
        prepared.credential = ("person" if person != SHARED else "team") if kind.holds_token else None
        SIGNED_WITH.set(prepared.credential)
        prepared.certificate = certificate_of(settings, values)
        return prepared

    @staticmethod
    def _whose(conn: dict[str, Any], kind: Kind, acting_for: ActingForPerson | None, needs_person: bool) -> str:
        """The token row a call uses: the team's on a team connection; on one each person signs in to, the person's
        the call acts for, or the team's for a call with nobody behind it while the backup is on and the operation
        does not need a person."""
        sign_in = str(conn.get("sign_in") or "team")
        if sign_in == "team" or not kind.per_person:
            return SHARED
        if acting_for is not None:
            return acting_for.sub
        backed = sign_in == "person_or_team" and conn.get("team_backup")
        if backed and not needs_person:
            return SHARED
        name = conn["name"]
        message = (
            f"This operation signs in to {name} as a person only, and this call acts for nobody."
            if backed
            else f"{name} signs in as each person, and this call acts for nobody."
        )
        details = {"connectionId": str(conn["id"]), "connection": str(name)}
        raise AuthFailed(
            "CONNECTION_NOT_LINKED", message, details={**details, "reason": "needs_person" if backed else "no_person"}
        )

    async def _not_linked(
        self,
        conn: dict[str, Any],
        env: str,
        person: ActingForPerson,
        settings: dict[str, Any],
        *,
        scopes: list[str],
        reason: str = "not_connected",
    ) -> AuthFailed:
        """CONNECTION_NOT_LINKED with a link only `person` can use to sign in their own account, asking for the
        connection's scopes and `scopes` (the operation's, and on insufficient_scope those already granted)."""
        details: dict[str, Any] = {
            "connectionId": str(conn["id"]),
            "connection": str(conn["name"]),
            "reason": reason,
        }
        if self.links is not None:
            details |= await self.links.make(
                tenant_id=str(conn["tenant_id"]),
                connection_id=str(conn["id"]),
                environment=env,
                team_id=str(conn["team_id"]),
                person=person,
                scopes=[*str(settings.get("scopes") or "").split(), *scopes],
                reason=reason,
            )
        who = person.email or "this person"
        message = (
            f"{conn['name']} needs {who} to connect their own account again, allowing more."
            if reason == "insufficient_scope"
            else f"{conn['name']} needs {who} to connect their own account."
        )
        return AuthFailed("CONNECTION_NOT_LINKED", message, details=details)

    async def _secret_values(
        self, tenant_id: str, team_id: str, names: dict[str, str], *, tool: str, actor: str
    ) -> dict[str, str]:
        """Each secret field's value from the connection's team, its use audited on the secret store as any
        secret's is."""
        if not names:
            return {}
        if self.secrets is None:
            raise AuthFailed("SECRET_UNAVAILABLE", "This gateway has no secrets store, so no connection signs in.")
        try:
            found = await self.secrets.lookup(tenant_id, team_id, list(names.values()), tool=tool, actor=actor)
        except SecretMissing as e:
            raise AuthFailed("SECRET_MISSING", f"A secret part of this connection is not set ({e}).") from e
        return {fieldname: found[secret] for fieldname, secret in names.items() if secret in found}
