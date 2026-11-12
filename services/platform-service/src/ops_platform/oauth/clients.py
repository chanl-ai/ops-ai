"""Dynamic client registration (RFC 7591): any assistant may register, so what it may register is limited. A redirect
is https, http on the loopback (any port), or an app's own scheme; a fragment or a scheme that runs script is refused.
At most 10 registrations a minute per source address; a client nobody allowed within 24 hours is deleted by the next
registration."""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit

from ops_service_kit.ids import new_id

from ..store.identity import Client, IdentityStore
from . import OAuthError, iso

LOOPBACK = {"127.0.0.1", "localhost", "[::1]", "::1"}
# Schemes that run or read something in the browser rather than hand the code to an app.
REFUSED_SCHEMES = {"javascript", "data", "file", "vbscript", "blob", "about", "ftp", "ws", "wss"}
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*$")
PER_MINUTE = 10
UNUSED_HOURS = 24
MAX_REDIRECTS = 10


def check_redirect(uri: str) -> None:
    refusal = OAuthError("invalid_redirect_uri", f"{uri[:80]} is not an address an assistant may return to.")
    if len(uri) > 500 or any(ch.isspace() for ch in uri):
        raise refusal
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    if parts.fragment or "#" in uri or not SCHEME.match(scheme) or scheme in REFUSED_SCHEMES:
        raise refusal
    if scheme == "https":
        if not parts.hostname:
            raise refusal
    elif scheme == "http":
        if parts.hostname not in LOOPBACK and f"[{parts.hostname}]" not in LOOPBACK:
            raise refusal
    elif parts.username or parts.password:
        raise refusal


def redirect_allowed(client: Client, uri: str) -> bool:
    """Exact match with a registered address; for a loopback one, any port (RFC 8252)."""
    if uri in client.redirect_uris:
        return True
    given = urlsplit(uri)
    if given.scheme != "http" or given.hostname not in LOOPBACK:
        return False
    for known in client.redirect_uris:
        k = urlsplit(known)
        if k.scheme == "http" and k.hostname == given.hostname and k.path == given.path and k.query == given.query:
            return True
    return False


@dataclass
class RegistrationLimit:
    """Registrations per source address in the last minute, held by this process. A bank runs one platform-service
    replica; with more, each replica counts its own, which loosens the limit by the replica count."""

    per_minute: int = PER_MINUTE
    clock: Any = time.monotonic
    seen: dict[str, deque[float]] = field(default_factory=dict[str, deque[float]])

    def retry_after(self, address: str) -> int:
        """0 and counts this registration, or the seconds until the address may register again."""
        now = self.clock()
        window = self.seen.setdefault(address, deque())
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= self.per_minute:
            return max(1, int(60 - (now - window[0])) + 1)
        window.append(now)
        if len(self.seen) > 10_000:
            self.seen = {a: w for a, w in self.seen.items() if w and now - w[-1] < 60}
        return 0


@dataclass
class Clients:
    store: IdentityStore
    limit: RegistrationLimit = field(default_factory=RegistrationLimit)

    async def register(self, body: dict[str, Any], *, address: str) -> dict[str, Any]:
        given: object = body.get("redirect_uris")
        listed = cast(list[object], given) if isinstance(given, list) else []
        uris = [u for u in listed if isinstance(u, str)]
        if not 0 < len(listed) <= MAX_REDIRECTS or len(uris) != len(listed):
            raise OAuthError("invalid_redirect_uri", f"Give between 1 and {MAX_REDIRECTS} redirect addresses.")
        for u in uris:
            check_redirect(u)
        if body.get("token_endpoint_auth_method", "none") != "none":
            raise OAuthError(
                "invalid_client_metadata", "Only public clients are taken: token_endpoint_auth_method none."
            )
        raw = body.get("client_name")
        name = " ".join(raw.split())[:100] if isinstance(raw, str) and raw.strip() else "Unnamed assistant"
        wait = self.limit.retry_after(address)
        if wait:
            raise OAuthError(
                "temporarily_unavailable",
                "Too many registrations from this address.",
                status=429,
                headers={"Retry-After": str(wait)},
            )
        now = datetime.now(UTC)
        client = Client(new_id("cli"), name, list(dict.fromkeys(uris)), None, None)
        await self.store.register_client(client, at=iso(now), stale_before=iso(now - timedelta(hours=UNUSED_HOURS)))
        return {
            "client_id": client.id,
            "client_name": client.name,
            "redirect_uris": client.redirect_uris,
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "client_id_issued_at": int(now.timestamp()),
        }
