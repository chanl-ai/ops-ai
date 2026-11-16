"""Every background process platform-service runs reports a failed pass on /health/background, by failure mode: the
database goes away under a loop and the health report still reads as running, so nobody learns the relay, the purge
or the certificate watch has stopped working."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_platform.signin_settings import ProviderMetadata
from ops_platform.signin_watch import SecurityNotices, SignInWatch
from ops_platform.store.holders import HolderStore
from ops_platform.store.lifecycle import LifecycleStore
from ops_platform.store.relay import platform_relay
from ops_platform.store.signin import SignInStore
from ops_platform.store.tenancy import TenantDb
from ops_platform.store.workspace import WorkspaceStore
from ops_platform.workspace_lifecycle import WorkspacePurge
from ops_store.background import LOCAL
from ops_store.background import run as run_background
from ops_store.outbox import run_relay
from ops_store.testing import loop_reports_failure

from .conftest import Platform


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


async def test_the_relay_reports_a_failed_pass(platform: Platform) -> None:
    relay = platform_relay(platform.engine, {"agents": Agents()})
    gone = create_async_engine("sqlite+aiosqlite://")
    try:
        async with _running(lambda stop: run_relay(relay, key="platform_relay", stop=stop)):
            await loop_reports_failure(platform.public, "platform_relay", lambda: setattr(relay, "engine", gone))
    finally:
        await gone.dispose()


def _gone_under(store: TenantDb, gone: AsyncEngine) -> Callable[[], None]:
    return lambda: setattr(store, "engine", gone)


def _every(key: str, once: Callable[[], Awaitable[int | None]]) -> Callable[[asyncio.Event], Coroutine[Any, Any, None]]:
    # The listed intervals are a day and fifteen minutes; a short one lets the pass after the trip come within the wait.
    return lambda stop: run_background(key, once, stop=stop, store=LOCAL, every_s=0.2)


async def test_the_workspace_purge_reports_a_failed_pass(platform: Platform) -> None:
    lifecycle = LifecycleStore(platform.engine)
    purge = WorkspacePurge(lifecycle, restore_days=30)
    gone = create_async_engine("sqlite+aiosqlite://")
    try:
        async with _running(_every("workspace_lifecycle", purge.once)):
            trip = _gone_under(lifecycle, gone)
            await loop_reports_failure(platform.public, "workspace_lifecycle", trip, within_s=5.0)
    finally:
        await gone.dispose()


async def test_the_certificate_watch_reports_a_failed_pass(platform: Platform) -> None:
    store = SignInStore(platform.engine)

    async def fetch(url: str) -> bytes:
        raise AssertionError(f"no provider is read in this test: {url}")

    watch = SignInWatch(
        store,
        ProviderMetadata(store, fetch),
        SecurityNotices(store, HolderStore(store), WorkspaceStore(store), None, None),
    )
    gone = create_async_engine("sqlite+aiosqlite://")
    try:
        async with _running(_every("signin_watch", watch.once)):
            await loop_reports_failure(platform.public, "signin_watch", _gone_under(store, gone), within_s=5.0)
    finally:
        await gone.dispose()
