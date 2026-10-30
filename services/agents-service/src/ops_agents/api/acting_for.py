"""Whom each tool call acts for (c-558), sent to tools-service as a token platform-service signs, never as a field.

The person is the chat turn's (TURN_PERSON), or a run's starter: the email the run's first run records as
`created_by`, so a child run acts for the person who started its parent, and a held write approved by someone else
still acts for the starter (owner decision 2). A run a schedule, mailbox, webhook or API key started has no person,
and its calls carry no token.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from ops_engine.store import RUN_PREFIX, RunStore
from ops_identity import ACTING_FOR_HEADER, ActingForTokens, ServiceClient, service_signer
from ops_service_kit.settings import Settings

from ..activities.gateway import RunContext
from ..store.engine import AsyncEngine, EngineTransactions
from .child_runs import TURN_PERSON
from .engine_runs import first_run


def person_of(created_by: object) -> str | None:
    """A run's starter when it is a person (an email), not `key:<id>`, `run:<parent>` or a trigger's name."""
    text = str(created_by or "")
    return text if "@" in text and ":" not in text.split("@", 1)[0] else None


class CallPeople:
    """The X-Acting-For header for a tool call: the token for the person it acts for, or none. `runs` reads a run
    (a RunStore on the request's or run's tenant), None where no engine runs are read."""

    def __init__(self, tokens: ActingForTokens, runs: Callable[[], Any] | None = None) -> None:
        self.tokens = tokens
        self.runs = runs

    @classmethod
    def on(cls, tokens: ActingForTokens, db: AsyncEngine) -> CallPeople:
        return cls(tokens, lambda: RunStore(EngineTransactions(db)))

    async def email(self, ctx: RunContext) -> str | None:
        turn = TURN_PERSON.get()
        if turn is not None and not turn.is_key and turn.email:
            return turn.email
        # Only an engine run has a starter to act for; a v1 graph thread's config names its journal run (`run_…`).
        if ctx.run_id is None or not ctx.run_id.startswith(RUN_PREFIX) or self.runs is None:
            return None
        runs = self.runs()
        run = await runs.get(ctx.run_id)
        return person_of((await first_run(runs, run)).get("created_by")) if run is not None else None

    async def headers(self, ctx: RunContext, *, tenant_id: str | None, team_id: str | None) -> dict[str, str]:
        email = await self.email(ctx)
        if email is None or not tenant_id or not team_id:
            return {}
        return {ACTING_FOR_HEADER: await self.tokens.token(tenant_id=tenant_id, email=email, team_id=team_id)}


def acting_for_tokens(settings: Settings, http: httpx.AsyncClient) -> ActingForTokens:
    """Minted by platform-service on a platform stack; signed with this service's own key in dev, which only a
    service built for dev accepts."""
    if settings.auth_mode != "platform":
        return ActingForTokens.for_dev(service_signer(settings), service="agents")
    internal = settings.platform_internal_url or f"http://127.0.0.1:{settings.platform_internal_port}"
    del http
    platform = httpx.AsyncClient(base_url=internal, timeout=10)
    return ActingForTokens.from_platform(
        ServiceClient.for_settings(settings, platform, service="agents", audience="platform")
    )
