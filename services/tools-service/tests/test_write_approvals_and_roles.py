"""Write approvals: what makes a write wait and who approves their own, by failure mode:

- a write nobody turned approval on for still waits for a token;
- a team that lists an app in appWritesNeedApproval has that app's writes run without one;
- a team that lists an app in appsChangeWithoutAsking loosens that app's own wait, a failed read does not;
- a person who decides the team's reviews approves their own write only while requesterMayDecide is on (off by
  default), and one who does not is never let through (an imported write starts waiting, test_import).

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

from .test_write_approval_gateway import ADDRESS, Call, _gateway, reasons  # pyright: ignore[reportPrivateUsage]

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


class ChangesWithoutAsking(WriteApprovals):
    """The apps the team listed in appsChangeWithoutAsking (None: the list could not be read)."""

    def __init__(self, engine: AsyncEngine, *, readable: bool = True) -> None:
        super().__init__(cast(Any, None))
        self.engine = engine
        self.readable = readable

    async def all_writes(self, tenant_id: str, team_id: str | None) -> bool:
        return False

    async def apps(self, tenant_id: str, team_id: str | None) -> list[str] | None:
        return []

    async def change_without_asking(self, tenant_id: str, team_id: str | None) -> list[str] | None:
        if not self.readable:
            return None
        mods = await ModuleStore(self.engine).all_teams(tenant_id)
        return [f"module:{m['id']}" for m in mods if any(o["name"] == "update_address" for o in m["operations"])]


@pytest.fixture
async def quiet(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Call]:
    async for call in _gateway(engine, seed, tenant, catalog_tools, ChangesWithoutAsking(engine)):
        yield call


@pytest.fixture
async def unreadable(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Call]:
    async for call in _gateway(engine, seed, tenant, catalog_tools, ChangesWithoutAsking(engine, readable=False)):
        yield call


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


async def test_an_app_listed_in_apps_change_without_asking_runs_its_write_without_a_token(quiet: Call) -> None:
    r = await quiet("update_address", ADDRESS, "quiet-1")
    assert r.status_code == 200 and r.json()["data"]["decision"] == "allow", r.text


async def test_an_unreadable_apps_change_without_asking_leaves_an_unset_write_running(unreadable: Call) -> None:
    r = await unreadable("update_address", ADDRESS, "quiet-2")
    assert r.status_code == 200 and r.json()["data"]["decision"] == "allow", r.text


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
    loose = {"requesterMayDecide": True}
    assert approves_own_writes(access, _person("admin", loose)) and approves_own_writes(
        access, _person("approver", loose)
    )
    assert not approves_own_writes(access, _person("viewer", loose)), "a viewer is asked like anyone else"
    # The four-eyes rule, the default: someone else decides even an admin's write.
    assert not approves_own_writes(access, _person("admin"))
