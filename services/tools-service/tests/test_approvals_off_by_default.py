"""Approvals are off by default and roles decide when they are on, by failure mode:

- a write nobody turned approval on for still waits for a token;
- a team that lists an app in appWritesNeedApproval has that app's writes run without one;
- a person who decides the team's reviews is asked to approve their own write, or one who does not is let through
  (the dev caller's Real write runs, test_test_console_reads; an imported write starts with its switch off,
  test_import).

Decided by the real Rego in OPA, on a seeded tenant's registry.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_access import Access
from ops_identity import Principal
from ops_tools.modules.policy import WriteApprovals, approves_own_writes
from ops_tools.store.modules import ModuleStore

from .test_write_approval_gateway import Call, _gateway, reasons  # pyright: ignore[reportPrivateUsage]

CASE = {"subject": "Card stopped working abroad"}


class ListsCaseApp(WriteApprovals):
    """The team listed the app holding open_case in appWritesNeedApproval, as the live read answers it."""

    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__(cast(Any, None))
        self.engine = engine

    async def all_writes(self, tenant_id: str, team_id: str | None) -> bool:
        return False

    async def apps(self, tenant_id: str, team_id: str | None) -> list[str] | None:
        mods = await ModuleStore(self.engine).all_teams(tenant_id)
        return [f"module:{m['id']}" for m in mods if any(o["name"] == "open_case" for o in m["operations"])]


@pytest.fixture
async def gateway(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Call]:
    async for call in _gateway(engine, seed, tenant, catalog_tools, None):
        yield call


@pytest.fixture
async def listed(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Call]:
    async for call in _gateway(engine, seed, tenant, catalog_tools, ListsCaseApp(engine)):
        yield call


async def test_a_write_nobody_turned_approval_on_for_runs_without_a_token(gateway: Call) -> None:
    """open_case's switch is off, and the team set no policy: it runs."""
    r = await gateway("open_case", CASE, "off-1")
    assert r.status_code == 200 and r.json()["data"]["decision"] == "allow", r.text


async def test_a_listed_apps_write_waits_for_a_token(listed: Call) -> None:
    r = await listed("open_case", CASE, "off-2")
    assert (r.status_code, reasons(r)) == (403, ["write needs an approval token"]), r.text


def _person(role: str, policies: dict[str, Any] | None = None) -> Principal:
    return Principal(
        kind="person",
        sub="usr_x",
        email="x@bank.example",
        name="X",
        tenant_id="t",
        team_id="team_ops",
        team_ids=["team_ops"],
        roles={"team_ops": role},
        scopes=[],
        auth_method="session",
        policies=policies or {},
    )


def test_only_a_person_who_decides_the_teams_reviews_approves_their_own_write() -> None:
    access = Access(security_team="team_security")
    assert approves_own_writes(access, _person("admin")) and approves_own_writes(access, _person("approver"))
    assert not approves_own_writes(access, _person("viewer")), "a viewer is asked like anyone else"
    assert not approves_own_writes(access, _person("viewer"))
    # The four-eyes rule: with requesterMayDecide off, someone else decides even an admin's write.
    assert not approves_own_writes(access, _person("admin", {"requesterMayDecide": False}))
