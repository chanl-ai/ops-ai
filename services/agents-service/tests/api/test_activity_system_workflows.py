"""A shipped system workflow's change in Activity (c-317), by failure mode, through the real seed follow
(api/service_events.py) and GET /v1/activity: an update to a shipped workflow never shows; an update decided in review
still reads as waiting; a team that kept its own version is not told an update exists."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.store import DefinitionStore
from ops_service_kit.ids import now_iso
from tests.api.test_activity import activity
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_event_workflow_follow import provision, shipped
from tests.engine.test_lifecycle_rights import BUILDER, TENANT, person

ADMIN = person("ana", "team_ops", "admin")


def renamed(note: str, wid: str) -> dict[str, Any]:
    """The test event workflow under its own id, so this test's versions are its own on a shared database."""
    return shipped(note) | {"id": wid, "name": "Purge a deleted file's reads"}


def rows(page: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in page["data"] if r["kind"] == "system_workflow"]


async def test_a_shipped_update_shows_waiting_for_review_then_updated_once_approved(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    wid = f"sys_{uuid4().hex[:8]}"
    await provision(rt.db, TENANT, renamed("purged", wid))
    await provision(rt.db, TENANT, renamed("purged_v2", wid))
    page = await activity(c, BUILDER, kind="system_workflow", source=f"workflow:{wid}")
    [row] = rows(page)
    assert (row["title"], row["status"], row["outcome"], row["ref"]["kind"]) == (
        "Shipped update waiting for review",
        "waiting",
        "pending",
        "review",
    ), row
    assert row["source"] == {"type": "workflow", "id": wid, "name": "Purge a deleted file's reads"}, row["source"]
    assert row["teamId"] is None and row["actor"]["kind"] == "event", row
    assert page["facets"]["kind"] == {"system_workflow": 1}, page["facets"]
    url = f"/v1/publish-requests/{row['ref']['id']}/decision"
    decided = await c.post(url, json={"decision": "approved"}, headers=ADMIN)
    assert decided.status_code == 200, decided.text
    [after] = rows(await activity(c, BUILDER, kind="system_workflow", source=f"workflow:{wid}"))
    assert (after["title"], after["status"], after["outcome"], after["ref"]) == (
        "Updated to the shipped version",
        "done",
        "approved",
        {"kind": "workflow", "id": wid},
    ), after


async def test_a_team_that_kept_its_own_version_is_told_an_update_waits(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    wid = f"sys_{uuid4().hex[:8]}"
    await provision(rt.db, TENANT, renamed("purged", wid))
    mine = parse(renamed("purged_by_us", wid))
    store = DefinitionStore(EngineTransactions(rt.db))
    with tenant_scope(TENANT):
        version, _ = await store.publish(
            wid, name="Ours", definition=mine.wire(), digest=mine.digest(), now=now_iso(), by="ana@harborpine.example"
        )
        await store.go_live(wid, version)
    await provision(rt.db, TENANT, renamed("purged_v2", wid), review={"": {"workflows": "never"}})
    [row] = rows(await activity(c, BUILDER, kind="system_workflow", source=f"workflow:{wid}"))
    assert (row["title"], row["status"], row["outcome"], row["ref"]) == (
        "Shipped update available, own version kept",
        "waiting",
        "update_available",
        {"kind": "workflow", "id": wid},
    ), row
