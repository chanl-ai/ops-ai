"""Connect links (c-558): what a call that needed someone's own sign-in hands back, so that person can give it.

A link carries a random token; only its hash is kept, bound to the person the call acted for, the connection's team,
the connection and the environment. It opens the person's own sign-in once, within fifteen minutes, and only for them
(`ConnectionService.open_link`), so a link forwarded to someone else or found later starts nothing.
"""

from __future__ import annotations

import hashlib
import secrets as random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ops_identity import ActingForPerson

from ..store.connections import ConnectionStore

CONNECT_LINK_TTL = timedelta(minutes=15)


class ConnectLinks:
    def __init__(
        self, store: ConnectionStore, console_url: str, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self.store = store
        self.console_url = console_url.rstrip("/")
        self.clock = clock

    async def make(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        environment: str,
        team_id: str,
        person: ActingForPerson,
        scopes: list[str],
        reason: str,
    ) -> dict[str, str]:
        """A new link for `person`; its address and when it stops working."""
        token, now = random.token_urlsafe(32), self.clock()
        expires = now + CONNECT_LINK_TTL
        await self.store.add_link(
            {
                "tenant_id": tenant_id,
                "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                "connection_id": connection_id,
                "environment": environment,
                "team_id": team_id,
                "person_id": person.sub,
                "email": person.email,
                "scopes": " ".join(dict.fromkeys(scopes)),
                "reason": reason,
                "created_at": now,
                "expires_at": expires,
            },
            now=now,
        )
        return {
            "connectUrl": f"{self.console_url}/connections/connect?link={token}",
            "expiresAt": expires.isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
