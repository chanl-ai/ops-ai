"""The sign-in keep-alive: once a day, every account sign-in that holds a refresh token and has not been refreshed for
REFRESH_AFTER is refreshed, so a system that ends sign-ins left unused keeps them (Salesforce ends a refresh token
unused for 30 days). Generic: it refreshes any OAuth sign-in, the team's and each person's, in its own team's scope.
A refresh refused because the grant ended marks the account as needing a reconnect, as a call's would."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ops_service_kit.logging import get_logger
from ops_store import background, isolation

from ..auth import Authenticator
from ..store.connections import ConnectionStore
from ..store.team_defaults import TeamDefaults

log = get_logger("ops_tools.connections.keepalive")

KEY = "sign_in_keepalive"
# Inside the shortest idle limit a system sets (Salesforce's 30 days), with room for a pass that fails for days.
REFRESH_AFTER = timedelta(days=20)
# The first pass waits this long after a start, so a restart's own work comes first.
FIRST_IN_S = 300.0
ACTOR = "sign-in keep-alive"


class SignInKeepalive:
    def __init__(
        self,
        teams: TeamDefaults,
        store: ConnectionStore,
        auth: Authenticator,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.teams, self.store, self.auth, self.clock = teams, store, auth, clock

    async def once(self) -> int:
        """One pass over every team; returns how many sign-ins were refreshed. A sign-in whose refresh fails for any
        reason but an ended grant is logged and left, so the next pass tries it again and the others still run."""
        before = self.clock() - REFRESH_AFTER
        refreshed = 0
        for tenant, team in await self.teams.teams():
            with isolation.scope(tenant, team):
                for row in await self.store.idle_sign_ins(tenant, before):
                    connection, person = str(row["connection_id"]), str(row["person_id"])
                    try:
                        if await self.auth.keep_alive(tenant, connection, person, int(row["rotations"]), actor=ACTOR):
                            refreshed += 1
                    except Exception as e:  # one sign-in's failure never stops the pass
                        log.warning("sign_in_keepalive_failed", connection=connection, error=type(e).__name__)
        return refreshed


async def keep_signed_in(keepalive: SignInKeepalive) -> None:
    """Until the server stops, which cancels the task; a failed pass is retried and shows in /health/background."""
    await background.run(KEY, keepalive.once, stop=asyncio.Event(), store=background.LOCAL, first_in=FIRST_IN_S)
