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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit

import httpx

from ops_policy import Cipher, CipherError, context_of

from ..egress import EgressDenied, EgressPolicy, for_tenant
from ..store.connections import SHARED, ConnectionStore

# A token this close to its expiry is refreshed before use, so a call never carries one that lapses on the way.
EARLY = timedelta(seconds=60)
TOKEN_TIMEOUT_S = 10.0


class AuthFailed(Exception):
    """The call cannot be signed in. `code` and `side` are the call's failure; the message names hosts and fields,
    never a value."""

    def __init__(self, code: str, message: str, side: str = "ours", status: int | None = None) -> None:
        super().__init__(message)
        self.code, self.side, self.status = code, side, status


@dataclass(frozen=True)
class Token:
    access: str
    rotation: int
    expires_at: datetime | None
    account: str | None


def _context(tenant_id: str, part: str, connection_id: str, environment: str, person: str) -> str:
    return context_of(tenant_id, f"{part}/{connection_id}/{environment}/{person or 'shared'}")


def account_of(answer: dict[str, Any]) -> str | None:
    """Who signed in, for display only: the id token's email or subject when the system sends one. The id token is not
    verified here; nothing is decided from it."""
    raw = answer.get("id_token")
    if not isinstance(raw, str) or raw.count(".") < 1:
        return None
    try:
        body = raw.split(".")[1]
        claims: Any = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        return None
    if not isinstance(claims, dict):
        return None
    c = cast(dict[str, Any], claims)
    found = c.get("email") or c.get("preferred_username") or c.get("sub")
    return str(found) if found else None


class Tokens:
    def __init__(
        self,
        store: ConnectionStore,
        cipher: Cipher,
        http: httpx.AsyncClient | None,
        policy: EgressPolicy | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.cipher = cipher
        self.http = http
        self.policy = policy
        self.clock = clock
        # One token request at a time per token in this process; across processes the store's CAS decides.
        self._flight: dict[tuple[str, str, str], asyncio.Lock] = {}

    async def post(
        self, tenant_id: str, url: str, form: dict[str, str], settings: dict[str, Any], secret: str | None
    ) -> dict[str, Any]:
        """A token request: the form, with the client sent in the body or as basic auth (`clientAuth`). Raises
        AuthFailed naming the host and the system's error code, never the secret."""
        if self.http is None or self.policy is None:
            raise AuthFailed("EGRESS_DENIED", "This gateway has no egress policy, so it fetches no token.")
        host = urlsplit(url).hostname
        body = {**form, "client_id": str(settings.get("clientId") or "")}
        headers: dict[str, str] = {"Accept": "application/json"}
        if secret:
            if settings.get("clientAuth") == "basic":
                pair = f"{body.pop('client_id')}:{secret}".encode()
                headers["Authorization"] = "Basic " + base64.b64encode(pair).decode()
            else:
                body["client_secret"] = secret
        try:
            await self.policy.check_url(tenant_id, url)
            res = await self.http.post(
                url, data=body, headers=headers, timeout=TOKEN_TIMEOUT_S, extensions=for_tenant(tenant_id)
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
            error = cast(dict[str, Any], answer).get("error") if isinstance(answer, dict) else None
            reason = str(error) if isinstance(error, str) and error.isidentifier() else f"status {res.status_code}"
            raise AuthFailed(
                "AUTH_FAILED", f"{host} refused the sign-in ({reason}).", side="upstream", status=res.status_code
            )
        return cast(dict[str, Any], answer)

    def _row(
        self,
        tenant_id: str,
        key: tuple[str, str, str],
        answer: dict[str, Any],
        rotations: int,
        *,
        keep_refresh: str | None,
    ) -> dict[str, Any]:
        connection_id, environment, person = key
        now = self.clock()
        expires = answer.get("expires_in")
        refresh = answer.get("refresh_token")
        scope = answer.get("scope")
        return {
            "access_ct": self.cipher.encrypt(
                str(answer["access_token"]), context=_context(tenant_id, "access", connection_id, environment, person)
            ),
            # A system that does not rotate keeps the refresh token it gave before.
            "refresh_ct": self.cipher.encrypt(
                str(refresh), context=_context(tenant_id, "refresh", connection_id, environment, person)
            )
            if isinstance(refresh, str) and refresh
            else keep_refresh,
            "expires_at": now + timedelta(seconds=float(expires)) if isinstance(expires, (int, float)) else None,
            "scopes": str(scope).split() if isinstance(scope, str) else [],
            "account": account_of(answer),
            "rotations": rotations,
            "refreshed_at": now,
        }

    def _token(self, tenant_id: str, row: dict[str, Any], key: tuple[str, str, str]) -> Token:
        connection_id, environment, person = key
        try:
            access = self.cipher.decrypt(
                str(row["access_ct"]), context=_context(tenant_id, "access", connection_id, environment, person)
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
        environment: str,
        settings: dict[str, Any],
        secret: str | None,
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
        key = (connection_id, environment, person)
        async with self._flight.setdefault(key, asyncio.Lock()):
            row = await self.store.token(tenant_id, connection_id, environment, person)
            if self._fresh(row, stale_rotation):
                assert row is not None
                return self._token(tenant_id, row, key)
            read = int(row["rotations"]) if row else None
            try:
                fresh = await self._fetch(tenant_id, key, row, settings, secret=secret, grant=grant)
            except AuthFailed:
                again = await self.store.token(tenant_id, connection_id, environment, person)
                if again is not None and int(again["rotations"]) != read and self._fresh(again, None):
                    return self._token(tenant_id, again, key)
                raise
            if not await self.store.put_token(
                tenant_id, connection_id, environment, fresh, expected_rotations=read, person=person
            ):
                fresh = await self.store.token(tenant_id, connection_id, environment, person) or fresh
            return self._token(tenant_id, fresh, key)

    async def _fetch(
        self,
        tenant_id: str,
        key: tuple[str, str, str],
        row: dict[str, Any] | None,
        settings: dict[str, Any],
        *,
        secret: str | None,
        grant: str,
    ) -> dict[str, Any]:
        connection_id, environment, person = key
        rotations = int(row["rotations"]) + 1 if row else 1
        refresh_ct = row.get("refresh_ct") if row else None
        if refresh_ct:
            try:
                refresh = self.cipher.decrypt(
                    str(refresh_ct), context=_context(tenant_id, "refresh", connection_id, environment, person)
                )
            except CipherError as e:
                raise AuthFailed("NOT_SIGNED_IN", "The stored sign-in no longer decrypts; sign in again.") from e
            form = {"grant_type": "refresh_token", "refresh_token": refresh}
            if settings.get("resource"):
                # The token stays bound to the server it was issued for (RFC 8707), as the MCP spec asks.
                form["resource"] = str(settings["resource"])
            answer = await self.post(tenant_id, str(settings["tokenUrl"]), form, settings, secret)
            return self._row(tenant_id, key, answer, rotations, keep_refresh=str(refresh_ct))
        if grant != "client_credentials":
            raise AuthFailed("NOT_SIGNED_IN", "Nobody has signed in to this connection for this environment yet.")
        form = {"grant_type": "client_credentials"}
        for name in ("scopes", "audience"):
            if settings.get(name):
                form["scope" if name == "scopes" else name] = str(settings[name])
        answer = await self.post(tenant_id, str(settings["tokenUrl"]), form, settings, secret)
        return self._row(tenant_id, key, answer, rotations, keep_refresh=None)

    async def store_answer(
        self, tenant_id: str, connection_id: str, environment: str, answer: dict[str, Any], person: str = SHARED
    ) -> Token:
        """Keeps the token a finished sign-in returned, replacing any held for the same row."""
        key = (connection_id, environment, person)
        held = await self.store.token(tenant_id, connection_id, environment, person)
        values = self._row(tenant_id, key, answer, int(held["rotations"]) + 1 if held else 1, keep_refresh=None)
        await self.store.replace_token(tenant_id, connection_id, environment, values, person)
        return self._token(tenant_id, values, key)
