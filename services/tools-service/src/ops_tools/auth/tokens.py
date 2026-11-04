"""OAuth tokens a connection holds: fetched and refreshed through the egress client, stored encrypted, one refresh at a
time per token row.

Every token request is an ordinary outbound request: https to a host on the tenant's allow-list, dialled at a checked
address (`egress`), made with no database lock held. Tokens never leave this module in clear except as the value a
strategy puts on one request, and each is added to the call's scrub set by the caller.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit

import httpx

from ops_policy import CipherError, CredentialStore

from ..egress import EgressDenied, EgressPolicy, for_tenant
from ..store.connections import SHARED, ConnectionStore, Row, held_of
from ..store.connections import token_context as _context
from .assertion import SigningError, sign

# A token this close to its expiry is refreshed before use, so a call never carries one that lapses on the way.
EARLY = timedelta(seconds=60)
TOKEN_TIMEOUT_S = 10.0
CLIENT_ASSERTION = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
JWT_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"


class AuthFailed(Exception):
    """The call cannot be signed in. `code` and `side` are the call's failure; the message names hosts and fields,
    never a value."""

    def __init__(
        self,
        code: str,
        message: str,
        side: str = "ours",
        status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code, self.side, self.status = code, side, status
        # What the caller acts on: a connect link and the connection it is for (CONNECTION_NOT_LINKED).
        self.details = details or {}
        # The system's own `error` and `error_description` when its token answer named them (RFC 6749 5.2): what a
        # refused sign-in's message is chosen by, and how the keep-alive tells an ended grant from a passing fault.
        self.provider_error: str | None = None
        self.provider_description: str | None = None


@dataclass(frozen=True)
class Token:
    access: str
    rotation: int
    expires_at: datetime | None
    account: str | None


@dataclass
class ClientProof:
    """How the client proves itself to the system's sign-in: its secret, or an assertion signed with its key (RFC 7523)
    when `clientAuth` is `private_key_jwt`. Each assertion signed for a request is kept in `signed`, so the
    caller adds it to the call's scrub set."""

    secret: str | None = None
    signing_key: str | None = None
    signing_certificate: str | None = None
    signed: list[str] = field(default_factory=list[str])


def _claims(raw: Any) -> dict[str, Any]:
    """A JWT's claims, unverified; empty when `raw` is not one."""
    if not isinstance(raw, str) or raw.count(".") < 1:
        return {}
    try:
        body = raw.split(".")[1]
        claims: Any = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        return {}
    return cast(dict[str, Any], claims) if isinstance(claims, dict) else {}


def account_of(answer: dict[str, Any]) -> str | None:
    """Who signed in, for display only: the id token's email or subject when the system sends one. The id token is not
    verified here; nothing is decided from it."""
    c = _claims(answer.get("id_token"))
    found = c.get("email") or c.get("preferred_username") or c.get("sub")
    return str(found) if found else None


def scope_list(value: Any) -> list[str]:
    """Scopes as stored on a token row or an operation: a JSON list, or nothing."""
    return [str(x) for x in cast(list[Any], value)] if isinstance(value, list) else []


def granted_scopes(answer: dict[str, Any], requested: list[str]) -> list[str]:
    """The scopes a token answer granted: its `scope`, else the access token's `scope` or `scp` claim, else the
    scopes asked for, as RFC 6749 5.1 says an answer that omits them granted. Unverified: it only decides whether a
    person is asked to sign in again; the system still refuses what the token was not granted."""
    scope = answer.get("scope")
    if isinstance(scope, str):
        return scope.split()
    c = _claims(answer.get("access_token"))
    claim = c.get("scope", c.get("scp"))
    if isinstance(claim, str):
        return claim.split()
    if isinstance(claim, list):
        return scope_list(claim)
    return list(requested)


def _client(
    form: dict[str, str], settings: dict[str, Any], proof: ClientProof | None
) -> tuple[dict[str, str], dict[str, str]]:
    """The form and headers of a request to the system's sign-in: the client sent in the body or as basic auth."""
    client_id = str(settings.get("clientId") or "")
    body = {**form, "client_id": client_id}
    headers: dict[str, str] = {"Accept": "application/json"}
    if settings.get("clientAuth") == "private_key_jwt":
        # RFC 7523 2.2: the client is its signed assertion, and a secret held beside it is never sent.
        body["client_assertion_type"] = CLIENT_ASSERTION
        body["client_assertion"] = _signed(settings, proof, subject=client_id)
        return body, headers
    secret = proof.secret if proof else None
    if secret:
        if settings.get("clientAuth") == "basic":
            pair = f"{body.pop('client_id')}:{secret}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(pair).decode()
        else:
            body["client_secret"] = secret
    return body, headers


def _signed(
    settings: dict[str, Any], proof: ClientProof | None, *, subject: str | None, extra: dict[str, Any] | None = None
) -> str:
    """An assertion naming the client as its issuer and the token address as its audience (or the `audience` the
    system names, as DocuSign's account host), kept in `proof.signed` for the scrub set."""
    if proof is None or not proof.signing_key:
        raise AuthFailed("CONNECTION_NOT_SET", "This connection signs in with its certificate and has no Signing key.")
    try:
        token = sign(
            proof.signing_key,
            issuer=str(settings.get("clientId") or ""),
            subject=subject,
            audience=str(settings.get("audience") or settings["tokenUrl"]),
            cert_pem=proof.signing_certificate,
            extra=extra,
        )
    except SigningError as e:
        raise AuthFailed("CONNECTION_NOT_SET", str(e)) from e
    proof.signed.append(token)
    return token


class Tokens:
    def __init__(
        self,
        store: ConnectionStore,
        credentials: CredentialStore,
        http: httpx.AsyncClient | None,
        policy: EgressPolicy | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.credentials = credentials
        self.http = http
        self.policy = policy
        self.clock = clock
        # One token request at a time per token in this process; across processes the store's CAS decides.
        self._flight: dict[tuple[str, str], asyncio.Lock] = {}
        # The hosts a plugin's account may reach unlisted (tenant, account), set once plugins load.
        self.plugin_hosts: Callable[[str, str], Awaitable[list[str]]] | None = None

    async def hosts(self, tenant_id: str, connection_id: str) -> list[str]:
        """The plugin's own hosts for a plugin's account; none for any other."""
        return await self.plugin_hosts(tenant_id, connection_id) if self.plugin_hosts else []

    async def post(
        self,
        tenant_id: str,
        url: str,
        form: dict[str, str],
        settings: dict[str, Any],
        proof: ClientProof | None,
        *,
        client: bool = True,
        hosts: Iterable[str] = (),
    ) -> dict[str, Any]:
        """A token request: the form, with the client sent as `clientAuth` says, or not at all (`client` False, for a
        JWT grant). `hosts` are a plugin's own, reached unlisted. Raises AuthFailed naming the host and the system's
        error code, never the secret."""
        if self.http is None or self.policy is None:
            raise AuthFailed("EGRESS_DENIED", "This gateway has no egress policy, so it fetches no token.")
        host = urlsplit(url).hostname
        body, headers = _client(form, settings, proof) if client else (form, {"Accept": "application/json"})
        try:
            await self.policy.check_url(tenant_id, url, hosts)
            res = await self.http.post(
                url, data=body, headers=headers, timeout=TOKEN_TIMEOUT_S, extensions=for_tenant(tenant_id, hosts=hosts)
            )
        except EgressDenied as e:
            raise AuthFailed("EGRESS_DENIED", f"The token address: {e}") from e
        except httpx.HTTPError as e:
            raise AuthFailed("AUTH_FAILED", f"{host} could not be reached for a token ({type(e).__name__}).") from e
        try:
            answer: Any = res.json()
        except ValueError:
            answer = {}
        if (
            res.status_code >= 400
            or not isinstance(answer, dict)
            or not cast(dict[str, Any], answer).get("access_token")
        ):
            said = cast(dict[str, Any], answer) if isinstance(answer, dict) else {}
            error, description = said.get("error"), said.get("error_description")
            # Only an error code made of word characters is named back: it reaches a message a person reads.
            code = str(error) if isinstance(error, str) and error.isidentifier() else None
            failed = AuthFailed(
                "AUTH_FAILED",
                f"{host} refused the sign-in ({code or f'status {res.status_code}'}).",
                side="upstream",
                status=res.status_code,
            )
            failed.provider_error = code
            failed.provider_description = str(description)[:500] if isinstance(description, str) else None
            raise failed
        return cast(dict[str, Any], answer)

    async def _row(
        self,
        tenant_id: str,
        key: tuple[str, str],
        answer: dict[str, Any],
        rotations: int,
        *,
        keep_refresh: str | None,
        requested: list[str],
    ) -> dict[str, Any]:
        connection_id, person = key
        now = self.clock()
        expires = answer.get("expires_in")
        refresh = answer.get("refresh_token")
        return {
            "access_ct": await self.credentials.put(
                str(answer["access_token"]), context=_context(tenant_id, "access", connection_id, person)
            ),
            # A system that does not rotate keeps the refresh token it gave before.
            "refresh_ct": await self.credentials.put(
                str(refresh), context=_context(tenant_id, "refresh", connection_id, person)
            )
            if isinstance(refresh, str) and refresh
            else keep_refresh,
            "expires_at": now + timedelta(seconds=float(expires)) if isinstance(expires, (int, float)) else None,
            "scopes": granted_scopes(answer, requested),
            "account": account_of(answer),
            "rotations": rotations,
            "refreshed_at": now,
        }

    async def _token(self, tenant_id: str, row: dict[str, Any], key: tuple[str, str]) -> Token:
        connection_id, person = key
        try:
            access = await self.credentials.get(
                str(row["access_ct"]), context=_context(tenant_id, "access", connection_id, person)
            )
        except CipherError as e:
            raise AuthFailed("NOT_SIGNED_IN", "The stored token no longer decrypts; sign in again.") from e
        return Token(access, int(row["rotations"]), row.get("expires_at"), row.get("account"))

    def _fresh(self, row: dict[str, Any] | None, stale_rotation: int | None) -> bool:
        if row is None or (stale_rotation is not None and int(row["rotations"]) == stale_rotation):
            return False
        expires: datetime | None = row.get("expires_at")
        return expires is None or expires - EARLY > self.clock()

    async def access(
        self,
        tenant_id: str,
        connection_id: str,
        settings: dict[str, Any],
        proof: ClientProof | None,
        *,
        grant: str,
        stale_rotation: int | None = None,
        person: str = SHARED,
    ) -> Token:
        """A token to send: the stored one while it is fresh, else a new one. `grant` is how a new one is got when there
        is no refresh token: `client_credentials`, or `none` for a sign-in only a person can start. `stale_rotation` is
        the rotation a system just refused with 401: that token is replaced, a newer one is used as it is.

        No lock is held while the token request is in flight. Calls in this process wait for one another per token, so
        they refresh once; a refresh from another process is stored against the rotation it replaced, and the one that
        loses reads the winner's token, also when the system refused its spent refresh token."""
        key = (connection_id, person)
        async with self._flight.setdefault(key, asyncio.Lock()):
            row = await self.store.token(tenant_id, connection_id, person)
            if self._fresh(row, stale_rotation):
                assert row is not None
                return await self._token(tenant_id, row, key)
            read = int(row["rotations"]) if row else None
            try:
                fresh = await self._fetch(tenant_id, key, row, settings, proof=proof, grant=grant)
            except AuthFailed:
                again = await self.store.token(tenant_id, connection_id, person)
                if again is not None and int(again["rotations"]) != read and self._fresh(again, None):
                    return await self._token(tenant_id, again, key)
                raise
            if not await self.store.put_token(tenant_id, connection_id, fresh, expected_rotations=read, person=person):
                await self._forget(tenant_id, key, fresh, keep=row)
                fresh = await self.store.token(tenant_id, connection_id, person) or fresh
            elif row is not None:
                await self._forget(tenant_id, key, row, keep=fresh)
            return await self._token(tenant_id, fresh, key)

    async def drop(self, tenant_id: str, rows: Sequence[Row]) -> None:
        """Drops from the credential store what deleted token and sign-in state rows held (ConnectionStore's
        forget_token, forget_person, delete and add_state): a row deleted alone leaves its value in a vault."""
        for ref, context in held_of(tenant_id, rows):
            await self.credentials.delete(ref, context=context)

    async def _forget(
        self, tenant_id: str, key: tuple[str, str], row: dict[str, Any], *, keep: dict[str, Any] | None
    ) -> None:
        """Lets the credential store drop the references a row no longer names: the token a refresh replaced, or the
        one a lost race wrote and nobody stored. A refresh token the system did not rotate is kept."""
        connection_id, person = key
        for part in ("access", "refresh"):
            ref = row.get(f"{part}_ct")
            if ref and (keep is None or keep.get(f"{part}_ct") != ref):
                context = _context(tenant_id, part, connection_id, person)
                await self.credentials.delete(str(ref), context=context)

    async def _fetch(
        self,
        tenant_id: str,
        key: tuple[str, str],
        row: dict[str, Any] | None,
        settings: dict[str, Any],
        *,
        proof: ClientProof | None,
        grant: str,
    ) -> dict[str, Any]:
        connection_id, person = key
        rotations = int(row["rotations"]) + 1 if row else 1
        refresh_ct = row.get("refresh_ct") if row else None
        if refresh_ct:
            try:
                refresh = await self.credentials.get(
                    str(refresh_ct), context=_context(tenant_id, "refresh", connection_id, person)
                )
            except CipherError as e:
                raise AuthFailed("NOT_SIGNED_IN", "The stored sign-in no longer decrypts; sign in again.") from e
            form = {"grant_type": "refresh_token", "refresh_token": refresh}
            if settings.get("resource"):
                # The token stays bound to the server it was issued for (RFC 8707), as the MCP spec asks.
                form["resource"] = str(settings["resource"])
            hosts = await self.hosts(tenant_id, connection_id)
            answer = await self.post(tenant_id, str(settings["tokenUrl"]), form, settings, proof, hosts=hosts)
            # A refresh grants what the sign-in did unless it says otherwise (RFC 6749 6).
            held = scope_list((row or {}).get("scopes"))
            return await self._row(tenant_id, key, answer, rotations, keep_refresh=str(refresh_ct), requested=held)
        if grant == "jwt_bearer":
            return await self._jwt_grant(tenant_id, key, settings, proof, rotations)
        if grant != "client_credentials":
            raise AuthFailed("NOT_SIGNED_IN", "Nobody has signed in to this account yet.")
        form = {"grant_type": "client_credentials"}
        for name in ("scopes", "audience"):
            if settings.get(name):
                form["scope" if name == "scopes" else name] = str(settings[name])
        hosts = await self.hosts(tenant_id, connection_id)
        answer = await self.post(tenant_id, str(settings["tokenUrl"]), form, settings, proof, hosts=hosts)
        asked = str(settings.get("scopes") or "").split()
        return await self._row(tenant_id, key, answer, rotations, keep_refresh=None, requested=asked)

    async def _jwt_grant(
        self,
        tenant_id: str,
        key: tuple[str, str],
        settings: dict[str, Any],
        proof: ClientProof | None,
        rotations: int,
    ) -> dict[str, Any]:
        """RFC 7523 2.1: the signed JWT is the grant, with no client sent and no refresh token, so a new one is signed
        when the token expires. Scopes go in the form, or as a `scope` claim where Google reads them."""
        scopes = str(settings.get("scopes") or "")
        claim = settings.get("scopeIn") == "claim"
        subject = str(settings["subject"]) if settings.get("subject") else None
        form = {"grant_type": JWT_GRANT}
        form["assertion"] = _signed(
            settings, proof, subject=subject, extra={"scope": scopes} if claim and scopes else None
        )
        if scopes and not claim:
            form["scope"] = scopes
        hosts = await self.hosts(tenant_id, key[0])
        answer = await self.post(tenant_id, str(settings["tokenUrl"]), form, settings, proof, client=False, hosts=hosts)
        return await self._row(tenant_id, key, answer, rotations, keep_refresh=None, requested=scopes.split())

    async def revoke(
        self,
        tenant_id: str,
        connection_id: str,
        row: dict[str, Any],
        *,
        settings: dict[str, Any],
        proof: ClientProof | None,
    ) -> bool:
        """Ends a held sign-in at the system's `revokeUrl` (RFC 7009): its refresh token, which ends the grant, else its
        access token. True when the system accepted it; False when it refused or could not be reached, which never
        keeps the row: a person who disconnects has the token gone here either way."""
        url = str(settings.get("revokeUrl") or "")
        if not url or self.http is None or self.policy is None:
            return False
        person = str(row["person_id"])
        part, hint = ("refresh", "refresh_token") if row.get("refresh_ct") else ("access", "access_token")
        try:
            token = await self.credentials.get(
                str(row[f"{part}_ct"]), context=_context(tenant_id, part, connection_id, person)
            )
        except CipherError:
            return False
        body, headers = _client({"token": token, "token_type_hint": hint}, settings, proof)
        hosts = await self.hosts(tenant_id, connection_id)
        try:
            await self.policy.check_url(tenant_id, url, hosts)
            res = await self.http.post(
                url, data=body, headers=headers, timeout=TOKEN_TIMEOUT_S, extensions=for_tenant(tenant_id, hosts=hosts)
            )
        except (EgressDenied, httpx.HTTPError):
            return False
        return res.status_code < 400

    async def store_own(self, tenant_id: str, connection_id: str, person: str, values: dict[str, str]) -> None:
        """A person's own key, password or token for a connection each person signs in to: their row in
        connection_tokens, the fields sealed together under the person's own context, with no expiry and nothing to
        refresh. The account shown is the username, when the kind has one."""
        if person == SHARED:
            raise ValueError("a person's own credentials are never the team's row")
        held = await self.store.token(tenant_id, connection_id, person)
        sealed = await self.credentials.put(
            json.dumps(values), context=_context(tenant_id, "access", connection_id, person)
        )
        row: dict[str, Any] = {
            "access_ct": sealed,
            "refresh_ct": None,
            "expires_at": None,
            "scopes": [],
            "account": values.get("username"),
            "rotations": int(held["rotations"]) + 1 if held else 1,
            "refreshed_at": self.clock(),
        }
        await self.store.replace_token(tenant_id, connection_id, row, person)
        if held is not None:
            await self._forget(tenant_id, (connection_id, person), held, keep=row)

    async def own(
        self, tenant_id: str, connection_id: str, person: str, *, row: dict[str, Any] | None = None
    ) -> dict[str, str] | None:
        """The person's own credential fields, or None when they gave none or the row no longer opens. `row`: the
        row already read for this call."""
        row = row if row is not None else await self.store.token(tenant_id, connection_id, person)
        if row is None:
            return None
        try:
            opened = await self.credentials.get(
                str(row["access_ct"]), context=_context(tenant_id, "access", connection_id, person)
            )
            found = json.loads(opened)
        except (CipherError, ValueError):
            return None
        if not isinstance(found, dict):
            return None
        return {str(k): str(v) for k, v in cast(dict[Any, Any], found).items()}

    async def store_answer(
        self,
        tenant_id: str,
        connection_id: str,
        answer: dict[str, Any],
        person: str = SHARED,
        *,
        requested: list[str] | None = None,
    ) -> Token:
        """Keeps the token a finished sign-in returned, replacing any held for the same row. `requested` are the scopes
        the sign-in asked for: what it granted when the answer does not say."""
        key = (connection_id, person)
        held = await self.store.token(tenant_id, connection_id, person)
        rotations = int(held["rotations"]) + 1 if held else 1
        values = await self._row(tenant_id, key, answer, rotations, keep_refresh=None, requested=requested or [])
        await self.store.replace_token(tenant_id, connection_id, values, person)
        if held is not None:
            await self._forget(tenant_id, key, held, keep=values)
        return await self._token(tenant_id, values, key)
