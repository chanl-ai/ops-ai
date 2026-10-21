"""A run's startedBy (c-201): who or what started it, named on the server, so the Runs list never shows a raw id or
looks names up itself. By failure mode: a run another run started shows that run's id instead of its workflow; a
mail-triggered run shows the address instead of the mailbox's name; one row's lookup misses and drops the field."""

from __future__ import annotations

from typing import Any

from ops_agents.api.key_summaries import PlatformKeySummaries
from ops_agents.api.people_names import PlatformPeopleNames
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.mailboxes import MailboxRow, MailboxStore
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import RunStore
from tests.api.test_case_routes import started_run
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, TENANT


async def started_by(s: Stack, run_id: str) -> dict[str, Any]:
    c, _ = s
    listed = (await c.get("/v1/runs", params={"pageSize": 100}, headers=BUILDER)).json()["data"]["data"]
    row = next(r for r in listed if r["id"] == run_id)
    detail = (await c.get(f"/v1/runs/{run_id}", headers=BUILDER)).json()["data"]
    assert row["startedBy"] == detail["startedBy"], (row["startedBy"], detail["startedBy"])
    return dict(row["startedBy"])


async def test_each_starter_is_named(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    parent = await started_run(c, BUILDER, "ops_check")
    tx = EngineTransactions(rt.db)
    with tenant_scope(TENANT):
        await MailboxStore(rt.db).create(
            MailboxRow(
                id="mbx_levy",
                team_id="team_ops",
                name="Levy notices",
                address="levy@harborpine.example",
                provider="imap",
                created_by="b",
                created_at="n",
                updated_at="n",
            )
        )
        base = await RunStore(tx).get(parent)
        assert base is not None
        same = {k: base[k] for k in ("team_id", "workflow_id", "version", "digest", "mode", "input")}
        await RunStore(tx).create(same | {"id": "wfrun_child", "run_key": "k1", "created_by": f"run:{parent}"})
        await RunStore(tx).create(
            same | {"id": "wfrun_mail", "run_key": "k2", "created_by": "trigger:email:levy@harborpine.example"}
        )
    assert await started_by(stack, parent) == {
        "kind": "person",
        "id": "james@harborpine.example",
        "name": "james@harborpine.example",
    }
    child = await started_by(stack, "wfrun_child")
    assert (child["kind"], child["runId"], child["name"]) == ("run", parent, "Refund check"), child
    mail = await started_by(stack, "wfrun_mail")
    assert (mail["kind"], mail["id"], mail["name"]) == ("trigger", "levy@harborpine.example", "Levy notices"), mail


class Platform:
    """platform-service's GET /v1/people-names, as ServiceClient returns its data."""

    def __init__(self) -> None:
        self.reads = 0

    async def get(self, path: str) -> list[dict[str, str]]:
        assert path == "/v1/people-names"
        self.reads += 1
        return [{"email": "james@harborpine.example", "name": "James Richardson"}]


async def test_a_person_who_started_a_run_is_named(stack: Stack) -> None:  # noqa: F811
    # The Runs list showed a person's email, which the console may not look up itself.
    c, rt = stack
    platform = Platform()
    rt.people_names = PlatformPeopleNames(platform)  # pyright: ignore[reportArgumentType]
    run = await started_run(c, BUILDER, "ops_check")
    assert (await started_by(stack, run))["name"] == "James Richardson"
    await started_by(stack, run)
    assert platform.reads == 1, "the names are read once a minute, not per request"


class KeyPlatform:
    """platform-service's GET /v1/api-key-summaries, a revoked key among them."""

    async def get(self, path: str) -> list[dict[str, str]]:
        assert path == "/v1/api-key-summaries"
        return [{"id": "key_sync", "name": "billing-sync", "status": "revoked"}]


async def test_a_run_an_api_key_started_is_named_by_its_label(stack: Stack) -> None:  # noqa: F811
    # The Runs list and Activity showed `key_sync`, which says nothing to the person reading it.
    c, rt = stack
    rt.key_summaries = PlatformKeySummaries(KeyPlatform())  # pyright: ignore[reportArgumentType]
    parent = await started_run(c, BUILDER, "ops_check")
    with tenant_scope(TENANT):
        base = await RunStore(EngineTransactions(rt.db)).get(parent)
        assert base is not None
        same = {k: base[k] for k in ("team_id", "workflow_id", "version", "digest", "mode", "input")}
        await RunStore(EngineTransactions(rt.db)).create(
            same | {"id": "wfrun_bykey", "run_key": "kk", "created_by": "key:key_sync"}
        )
    assert await started_by(stack, "wfrun_bykey") == {"kind": "key", "id": "key_sync", "name": "billing-sync"}
