"""How a call signs in: the module's account, and the strategy its auth kind names.

The executor asks `Authenticator.prepare` for every operation of a module that has a connection and adds what comes
back (headers, query values, a client certificate) to the request; the values it resolved join the call's scrub set.
Strategies are a table keyed by kind (`STRATEGIES`), so no tool or operation carries its own branch, and a kind is a row
in `kinds.KINDS` plus one entry here.

Which account a call uses is chosen where the module is resolved (connections.records.account_for): a test run takes
the app's sandbox account when it has one. A live run is never signed in with a sandbox account. An account with no
settings at all is an older integration record (the dev seed's); it adds nothing and the operation's own headers
apply as before.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import urlsplit

from ops_identity import ActingForPerson

from ..connections.account_events import CONNECTED, connected_key, needs_reconnect_event
from ..connections.records import EXPIRED, REFUSED
from ..environments import LIVE
from ..secrets import SecretMissing, SecretResolver
from ..store.connections import SHARED, ConnectionStore
from .assertion import SigningError, read_certificate
from .kinds import Kind, kind_of, origin
from .tokens import AuthFailed, ClientProof, Tokens, scope_list

# Why a call is refused CONNECTION_NOT_LINKED: never connected, a scope missing, an operation that needs a person
# while the team backs the rest, a call with nobody behind it, or the system refused the person's own key or sign-in.
# The console's CONNECTION_REQUIRED_REASONS is this list (lib/types/connections.ts), held equal by
# tests/test_person_credentials.py.
NotLinkedReason = Literal["not_connected", "insufficient_scope", "needs_person", "no_person", "refused"]

if TYPE_CHECKING:
    from ..connections.connect_links import ConnectLinks

__all__ = ["STRATEGIES", "AuthFailed", "Authenticator", "ClientCertificate", "NotLinkedReason", "Prepared", "Tokens"]


@dataclass(frozen=True)
class ClientCertificate:
    """What the egress transport uses on the TLS handshake: a client certificate to present and a CA to trust for the
    system's own certificate, either or both. `fingerprint` keys the connection pool, so a certificate is never
    presented on another connection's calls and a replaced one opens new connections."""

    fingerprint: str
    cert_pem: str | None = None
    key_pem: str | None = None
    ca_pem: str | None = None


# Whose sign-in signed the call this task is running (person or team), for the gateway's call log: the
# executor answers with the operation's outcome only, so the authenticator leaves it here.
SIGNED_WITH: ContextVar[str | None] = ContextVar("ops_tools_signed_with", default=None)


@dataclass
class Prepared:
    connection_id: str
    headers: dict[str, str] = field(default_factory=dict[str, str])
    params: dict[str, str] = field(default_factory=dict[str, str])
    certificate: ClientCertificate | None = None
    # Every value resolved for this call (secret parts, tokens): what the caller scrubs from everything it returns.
    values: list[str] = field(default_factory=list[str])
    # The rotation of the token sent, so a 401 replaces that token and no newer one.
    rotation: int | None = None
    # The kind holds a token the gateway can get again: a read refused with 401 is retried once.
    renewable: bool = False
    # Whose sign-in signed the call, for the call log: person or team; None for a kind that holds no token.
    credential: str | None = None
    # The person whose own row signed the call, so a refusal marks theirs alone; None for the team's.
    person: str | None = None


@dataclass(frozen=True)
class StrategyInput:
    tenant_id: str
    connection_id: str
    settings: dict[str, Any]
    secrets: dict[str, str]
    tokens: Tokens
    stale_rotation: int | None
    # Whose token row a token-holding kind uses: SHARED for the team's, a person's id for their own.
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
    """The account's TLS settings: a client certificate (both its PEM and its private key) and a CA to trust."""
    cert, key, ca = settings.get("clientCertificate"), secrets.get("clientKey"), settings.get("trustedCa")
    if not cert or not key:
        cert = key = None
    if not cert and not ca:
        return None
    digest = hashlib.sha256(f"{cert or ''}\0{key or ''}\0{ca or ''}".encode()).hexdigest()
    return ClientCertificate(digest, str(cert) if cert else None, key, str(ca) if ca else None)


def may_use(connection: dict[str, Any], team_id: str | None) -> bool:
    """A connection serves its own team's modules only: another team that needs the system holds its own
    connection, with its own sign-in."""
    return team_id is not None and connection["team_id"] == team_id


class Authenticator:
    def __init__(
        self,
        connections: ConnectionStore,
        secrets: SecretResolver | None,
        tokens: Tokens,
        links: ConnectLinks | None = None,
    ) -> None:
        self.connections = connections
        self.secrets = secrets
        self.tokens = tokens
        # Makes the link a call hands back when the person it acts for has not signed in.
        self.links = links

    async def addressed(self, module: dict[str, Any]) -> dict[str, Any]:
        """The module as a call reaches it: its address is its account's, the only home an address has. Empty
        with no account, or one naming none, and `prepare` says why."""
        connection_id = module.get("connection_id")
        conn = await self.connections.get(str(module["tenant_id"]), str(connection_id)) if connection_id else None
        settings: dict[str, Any] = (conn or {}).get("settings") or {}
        return {**module, "endpoint": str(settings.get("baseUrl") or "")}

    async def prepare(
        self,
        module: dict[str, Any],
        run: str,
        *,
        tool: str,
        actor: str,
        stale_rotation: int | None = None,
        acting_for: ActingForPerson | None = None,
        team_account: bool = False,
        needs_person: bool = False,
        scopes: Sequence[str] = (),
    ) -> Prepared | None:
        """What the module's account adds to a call made in `run` (test or production); None for a module with no
        account or one whose record has no settings. Raises AuthFailed when the call cannot be signed in; a live run on
        a sandbox account is refused.
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
        conn = await self.connections.get(tenant_id, str(connection_id))
        if conn is None:
            raise AuthFailed("CONNECTION_MISSING", "This module's connection no longer exists.")
        if not conn["settings"] and not conn["secrets"]:
            return None
        name = conn["name"]
        if not may_use(conn, module.get("team_id")):
            raise AuthFailed("CONNECTION_OUT_OF_SCOPE", f"{name} is not available to this module's team.")
        if conn["status"] == "revoked":
            raise AuthFailed("CONNECTION_REVOKED", f"{name} is revoked; reconnect it before tools use it.")
        if run == LIVE and conn.get("sandbox"):
            raise AuthFailed(
                "CONNECTION_NOT_SET",
                f"{name} is a test account, which only test runs use. A team admin connects a live account on the "
                "app's page.",
            )
        # A credential goes to its own system only: the module's address must be the account's, scheme, host and
        # port, before any secret is read; another allow-listed host gets nothing.
        plain: dict[str, Any] = dict(conn["settings"] or {})
        base = str(plain.get("baseUrl") or "")
        target = str(module.get("endpoint") or "")
        if not base:
            raise AuthFailed("CONNECTION_NOT_SET", f"{name} names no system address.")
        if origin(target) != origin(base):
            raise AuthFailed(
                "CONNECTION_HOST_MISMATCH",
                f"{name} signs in to {urlsplit(base).hostname} only; this module calls {urlsplit(target).hostname}.",
            )
        names: dict[str, str] = dict(conn["secrets"] or {})
        values = await self._secret_values(tenant_id, str(conn["team_id"]), names, tool=tool, actor=actor)
        # An account on Ops AI's app signs in with the install's client secret, never one of a team's.
        if (app := conn.get("platform_app")) and (installed := self.connections.install_client(str(app))):
            values = {**values, "clientSecret": installed.secret.get_secret_value()}
        prepared = Prepared(str(connection_id), values=list(values.values()))
        kind = kind_of(str(conn["auth_kind"]))
        # Whose sign-in is chosen before the team's parts are checked: a person who gives their own key needs none of
        # the team's.
        person = SHARED if team_account else self._whose(conn, kind, acting_for, needs_person)
        # A call a person started is signed as them only, even where the team account backs runs nobody started: one
        # with no sign-in of their own is asked to connect rather than quietly acting as the team.
        held_own: dict[str, Any] | None = None
        if person != SHARED and acting_for is not None:
            held_own = await self.connections.token(tenant_id, str(connection_id), person)
        missing = [
            f.label for f in kind.requires(plain, each_person=person != SHARED) if f.secret and f.name not in values
        ]
        if missing:
            raise AuthFailed("CONNECTION_NOT_SET", f"{name} has no {', '.join(missing)}.")
        settings = plain
        if person != SHARED and acting_for is not None and held_own is not None and held_own.get("refused_at"):
            # The system refused this key or sign-in before: ask for a new one rather than send it again.
            raise await self._not_linked(conn, acting_for, settings, scopes=list(scopes), reason="refused")
        if person != SHARED and kind.person_fields:
            own = await self.tokens.own(tenant_id, str(connection_id), person, row=held_own)
            if own is None:
                assert acting_for is not None
                raise await self._not_linked(conn, acting_for, settings, scopes=list(scopes))
            secret = {f: v for f, v in own.items() if (k := kind.field(f)) is not None and k.secret}
            settings = {**plain, **{f: v for f, v in own.items() if f not in secret}}
            values = {**values, **secret}
            prepared.values.extend(secret.values())
        if person != SHARED and acting_for is not None and scopes and kind.holds_token:
            held = await self.connections.token(tenant_id, str(connection_id), person)
            granted = scope_list((held or {}).get("scopes"))
            if held is not None and not set(scopes) <= set(granted):
                raise await self._not_linked(
                    conn, acting_for, settings, scopes=[*granted, *scopes], reason="insufficient_scope"
                )
        given = StrategyInput(
            tenant_id, str(connection_id), settings, values, self.tokens, stale_rotation, person=person
        )
        try:
            await STRATEGIES[kind.id](given, prepared)
        except AuthFailed as e:
            if person != SHARED and acting_for is not None and e.code == "NOT_SIGNED_IN":
                # A sign-in they hold that has ended is reconnected, as a refused one is; with none they connect.
                reason: NotLinkedReason = "refused" if held_own is not None else "not_connected"
                raise await self._not_linked(conn, acting_for, settings, scopes=list(scopes), reason=reason) from e
            if person == SHARED and (stopped := await self._team_account_stopped(conn, e, actor)) is not None:
                raise stopped from e
            if e.side == "upstream":
                # The system refused a person's own sign-in: only theirs is spent, everyone else's keeps working. Kept
                # and marked, so Your connections says the sign-in expired and offers Reconnect.
                at = datetime.now(UTC)
                await self.connections.mark_refused(tenant_id, str(connection_id), person, reason=str(e), at=at)
                event = {"action": "refresh_failed", "actor": actor, "at": at}
                await self.connections.note(
                    tenant_id, str(connection_id), {**event, "detail": {"code": e.code, "own": True}}
                )
                if person != SHARED and acting_for is not None:
                    # Asked to reconnect now, with a link, rather than on their next call.
                    raise await self._not_linked(
                        conn, acting_for, settings, scopes=list(scopes), reason="refused"
                    ) from e
            raise
        # A team key is not logged as a sign-in; a person's own key is, as their token is.
        prepared.credential = "person" if person != SHARED else ("team" if kind.holds_token else None)
        prepared.person = person if person != SHARED else None
        SIGNED_WITH.set(prepared.credential)
        prepared.certificate = certificate_of(settings, values)
        return prepared

    async def keep_alive(self, tenant_id: str, connection_id: str, person: str, rotation: int, *, actor: str) -> bool:
        """Refreshes one held sign-in now, whether or not its access token is still fresh, so a system that ends a
        sign-in left unused (Salesforce, after 30 days) keeps it. True when it was refreshed. A refresh the system
        refuses with invalid_grant (the grant ended) marks the sign-in as a call's refusal would: the team's account
        needs reconnecting, or the person's own sign-in is refused. Any other failure leaves it for the next pass."""
        conn = await self.connections.get(tenant_id, connection_id)
        if conn is None or conn["status"] == "revoked" or not kind_of(str(conn["auth_kind"])).holds_token:
            return False
        settings: dict[str, Any] = dict(conn["settings"] or {})
        values = await self._secret_values(
            tenant_id, str(conn["team_id"]), dict(conn["secrets"] or {}), tool="sign-in keep-alive", actor=actor
        )
        if (app := conn.get("platform_app")) and (installed := self.connections.install_client(str(app))):
            values = {**values, "clientSecret": installed.secret.get_secret_value()}
        cert = settings.get("signingCertificate")
        proof = ClientProof(values.get("clientSecret"), values.get("signingKey"), str(cert) if cert else None)
        try:
            # The rotation held is passed as stale, so the stored token is replaced even while it is fresh.
            await self.tokens.access(
                tenant_id, connection_id, settings, proof, grant="none", stale_rotation=rotation, person=person
            )
        except AuthFailed as e:
            if e.provider_error != "invalid_grant":
                raise
            if person == SHARED:
                await self._team_account_stopped(conn, e, actor)
            else:
                at = datetime.now(UTC)
                await self.connections.mark_refused(tenant_id, connection_id, person, reason=str(e), at=at)
                event = {"action": "refresh_failed", "actor": actor, "at": at}
                await self.connections.note(
                    tenant_id, connection_id, {**event, "detail": {"code": e.code, "own": True}}
                )
            return False
        return True

    async def _team_account_stopped(self, conn: dict[str, Any], e: AuthFailed, actor: str) -> AuthFailed | None:
        """A team account the system refused, or whose sign-in ended with no refresh token to renew it: the
        call says which app needs reconnecting and who does it, and the team's admins are told once per breakage
        through the outbox. None for any other failure, such as a team account nobody has signed in to yet, which is
        setup still to do rather than a breakage."""
        tenant_id, connection_id, name = str(conn["tenant_id"]), str(conn["id"]), str(conn["name"])
        held = await self.connections.token(tenant_id, connection_id, SHARED)
        at = datetime.now(UTC)
        ended: datetime | None = (held or {}).get("expires_at")
        if e.side == "upstream":
            state, why, since = REFUSED, str(e), (held or {}).get("refreshed_at")
        elif e.code == "NOT_SIGNED_IN" and ended is not None and ended <= at:
            state, why, since = EXPIRED, f"the team account's sign-in ended on {ended.day} {ended:%b %Y}.", ended
        else:
            return None
        notice = needs_reconnect_event(conn, state=state, reason=why, since=since, at=at)
        await self.connections.needs_reconnect(tenant_id, connection_id, str(e) if state == REFUSED else None, notice)
        if state == REFUSED:
            event = {"action": "refresh_failed", "actor": actor, "at": at}
            await self.connections.note(tenant_id, connection_id, {**event, "detail": {"code": e.code}})
        message = (
            f"{name} needs reconnecting: {why} An admin reconnects its team account under Apps, then runs it again."
        )
        details = {
            "connectionId": connection_id, "appId": str(conn["app_id"]), "app": name, "account": "team", "state": state
        }  # fmt: skip
        return AuthFailed(e.code, message, side=e.side, status=e.status, details=details)

    @staticmethod
    def _backed(conn: dict[str, Any]) -> bool:
        """Each person may sign in with their own account, and the team's sign-in serves runs nobody started."""
        return str(conn.get("sign_in") or "team") == "person_or_team" and bool(conn.get("team_backup"))

    @staticmethod
    def _whose(conn: dict[str, Any], kind: Kind, acting_for: ActingForPerson | None, needs_person: bool) -> str:
        """The token row a call uses: the team's on a team connection; on one each person signs in to, the person's
        the call acts for, always, or the team's for a call with nobody behind it while the backup is on and the
        operation does not need a person."""
        sign_in = str(conn.get("sign_in") or "team")
        if sign_in == "team" or not kind.per_person:
            return SHARED
        if acting_for is not None:
            return acting_for.sub
        backed = Authenticator._backed(conn)
        if backed and not needs_person:
            return SHARED
        name = conn["name"]
        message = (
            f"This operation signs in to {name} as a person only, and this call acts for nobody."
            if backed
            else f"{name} signs in as each person, and this call acts for nobody."
        )
        reason: NotLinkedReason = "needs_person" if backed else "no_person"
        details = {
            "connectionId": str(conn["id"]),
            "appId": str(conn["app_id"]),
            "connection": str(name),
            "reason": reason,
        }
        raise AuthFailed("CONNECTION_NOT_LINKED", message, details=details)

    async def refused(
        self, module: dict[str, Any], prepared: Prepared, acting_for: ActingForPerson, reason: str
    ) -> AuthFailed:
        """The system refused a person's own key with 401: their row alone is marked, so their next call asks
        for a new key, and this call answers CONNECTION_NOT_LINKED with reason `refused` for the card to ask now. The
        connection's status and everyone else's rows are left as they are."""
        tenant_id, connection_id = str(module["tenant_id"]), prepared.connection_id
        assert prepared.person is not None
        at = datetime.now(UTC)
        await self.connections.mark_refused(tenant_id, connection_id, prepared.person, reason=reason, at=at)
        event = {"action": "refresh_failed", "actor": acting_for.email, "at": at}
        await self.connections.note(tenant_id, connection_id, {**event, "detail": {"code": "REFUSED", "own": True}})
        conn = await self.connections.get(tenant_id, connection_id)
        if conn is None:
            return AuthFailed("CONNECTION_MISSING", "This module's connection no longer exists.")
        settings = cast(dict[str, Any], conn.get("settings") or {})
        return await self._not_linked(conn, acting_for, settings, scopes=[], reason="refused")

    async def _not_linked(
        self,
        conn: dict[str, Any],
        person: ActingForPerson,
        settings: dict[str, Any],
        *,
        scopes: list[str],
        reason: NotLinkedReason = "not_connected",
    ) -> AuthFailed:
        """CONNECTION_NOT_LINKED with a link only `person` can use to sign in their own account, asking for the
        connection's scopes and `scopes` (the operation's, and on insufficient_scope those already granted)."""
        kind = kind_of(str(conn["auth_kind"]))
        # The kind and the fields a person gives, so the console asks for a key in place of a sign-in it cannot start.
        details: dict[str, Any] = {
            "connectionId": str(conn["id"]),
            # The account's app: the console's Connect my account opens the account under it.
            "appId": str(conn["app_id"]),
            "connection": str(conn["name"]),
            "reason": reason,
            "authKind": kind.id,
            "personFields": list(kind.person_fields),
            # What a run that waits for this person to connect waits on: their connecting reports it.
            "connectedEvent": {"name": CONNECTED, "key": connected_key(str(conn["id"]), person.sub)},
            # Whether the team account serves runs nobody started (`_whose`); a call this person started never uses it.
            "teamAccount": str(conn.get("sign_in") or "team") == "person_or_team" and bool(conn.get("team_backup")),
        }
        if self.links is not None:
            details |= await self.links.make(
                tenant_id=str(conn["tenant_id"]),
                connection_id=str(conn["id"]),
                team_id=str(conn["team_id"]),
                person=person,
                scopes=[*str(settings.get("scopes") or "").split(), *scopes],
                reason=reason,
            )
        who = person.email or "this person"
        message = {
            "insufficient_scope": f"{conn['name']} needs {who} to connect their own account again, allowing more.",
            "refused": f"{conn['name']} refused the key or sign-in of {who}; they connect again to go on.",
        }.get(reason, f"{conn['name']} needs {who} to connect their own account.")
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
