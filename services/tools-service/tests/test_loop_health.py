"""Every background process tools-service runs reports a failed pass on /health/background, by failure mode: the
database goes away under a loop and the health report still reads as running, so nobody learns the relay, the sign-in
keep-alive or the secret audit sweep has stopped working."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_store.background import LOCAL, run_sweep
from ops_store.background import run as run_background
from ops_store.outbox import run_relay
from ops_store.store import Store
from ops_store.testing import loop_reports_failure
from ops_tools.connections.keepalive import KEY as KEEPALIVE
from ops_tools.connections.keepalive import SignInKeepalive
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.relay import KEY as RELAY
from ops_tools.store.relay import tools_relay
from ops_tools.store.secrets import AUDIT_RETENTION, AUDIT_SWEEP, SecretStore
from ops_tools.store.team_defaults import TeamDefaults

from .conftest import Api


class Agents:
    async def post(self, path: str, body: Any, /, *, tenant: str, team: str) -> None: ...


@asynccontextmanager
async def _running(loop: Callable[[asyncio.Event], Coroutine[Any, Any, None]]) -> AsyncGenerator[None]:
    """`loop` runs for the block, and is stopped and awaited after it."""
    stop = asyncio.Event()
    task = asyncio.create_task(loop(stop))
    try:
        yield
    finally:
        stop.set()
        await task


@asynccontextmanager
async def _gone() -> AsyncGenerator[AsyncEngine]:
    gone = create_async_engine("sqlite+aiosqlite://")
    try:
        yield gone
    finally:
        await gone.dispose()


def _under(store: Any, gone: AsyncEngine) -> Callable[[], None]:
    return lambda: setattr(store, "engine", gone)


async def test_the_relay_reports_a_failed_pass(api: Api, engine: AsyncEngine) -> None:
    relay = tools_relay(engine, Agents())
    async with _gone() as gone, _running(lambda stop: run_relay(relay, key=RELAY, stop=stop)):
        await loop_reports_failure(api.client, "tools_relay", _under(relay, gone))


async def test_the_sign_in_keepalive_reports_a_failed_pass(api: Api, engine: AsyncEngine) -> None:
    teams = TeamDefaults(engine)
    keepalive = SignInKeepalive(teams, ConnectionStore(engine), cast(Any, None))
    once = keepalive.once
    async with (
        _gone() as gone,
        _running(lambda stop: run_background(KEEPALIVE, once, stop=stop, store=LOCAL, every_s=0.2)),
    ):
        await loop_reports_failure(api.client, "sign_in_keepalive", _under(teams, gone), within_s=5.0)


async def test_the_secret_audit_sweep_reports_a_failed_pass(api: Api, engine: AsyncEngine) -> None:
    store: Store = SecretStore(engine)
    async with (
        _gone() as gone,
        _running(
            lambda stop: run_sweep(
                AUDIT_SWEEP, lambda: store.system_tx(AUDIT_RETENTION), stop=stop, store=LOCAL, every_s=0.2
            )
        ),
    ):
        await loop_reports_failure(api.client, "tools_secret_audit_retention", _under(store, gone), within_s=5.0)
