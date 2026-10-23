"""Background processes (c-516), by failure mode, through the real routes: the Background page shows to a team admin,
or misses a listed process; a team reads another team's background jobs in Activity; the health check carries data."""

from __future__ import annotations

from typing import Any

from ops_agents.store.background import BackgroundJobs
from ops_agents.store.tenancy import tenant_scope
from ops_policy import mint
from ops_store.background import PROCESSES
from tests.api.test_activity import activity
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, PLATFORM, TENANT, TEST_TOKEN_TTL_S, person

TEAM_ADMIN = person("ana", "team_ops", "admin")


def account_admin() -> dict[str, str]:
    claims: dict[str, Any] = {
        "sub": "priya",
        "email": "priya@harborpine.example",
        "name": "priya",
        "kind": "person",
        "aud": ["agents"],
        "tenant_id": TENANT,
        "team_ids": ["team_ops"],
        "roles": {"team_ops": "admin"},
        "access": {"*": ["admin"]},
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": "team_ops"}


async def _jobs(s: Stack) -> None:
    _, rt = s
    jobs = BackgroundJobs(rt.db)
    with tenant_scope(TENANT):
        await jobs.record(
            "timer_poller", "Woke a run that was waiting for a time or a reminder", "done", team_id="team_ops"
        )
        await jobs.record(
            "mail_listener", "Started Insurance claim intake from a new email", "done", team_id="team_claims"
        )


async def test_an_account_admin_sees_every_listed_process_and_every_team_s_jobs(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await _jobs(stack)
    r = await c.get("/v1/background", headers=account_admin())
    assert r.status_code == 200, r.text
    page = r.json()["data"]
    assert [p["key"] for p in page["processes"]] == [p.key for p in PROCESSES]
    by_key = {p["key"]: p for p in page["processes"]}
    # Not configured in tests, so their processes read not reported rather than vanishing.
    assert {by_key[k]["state"] for k in ("files_relay", "documents_relay", "tools_relay", "document_reading")} == {
        "not_reported"
    }
    summaries = {(j["summary"], j["teamId"]) for j in page["jobs"]}
    assert ("Started Insurance claim intake from a new email", "team_claims") in summaries
    assert ("Woke a run that was waiting for a time or a reminder", "team_ops") in summaries


async def test_a_team_admin_is_told_the_background_page_does_not_exist(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    r = await c.get("/v1/background", headers=TEAM_ADMIN)
    assert r.status_code == 404, r.text


async def test_a_team_sees_only_its_own_background_jobs_in_activity(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await _jobs(stack)
    page = await activity(c, BUILDER, kind="background")
    titles = {(row["title"], row["teamId"]) for row in page["data"]}
    assert ("Woke a run that was waiting for a time or a reminder", "team_ops") in titles
    assert all(team == "team_ops" for _, team in titles), titles
    row = next(r for r in page["data"] if r["kind"] == "background")
    assert row["source"]["type"] == "process" and row["source"]["name"] == "Timer poller", row
    assert row["actor"] == {"kind": "event", "id": "background/timer_poller", "name": "Timer poller"}, row["actor"]


async def test_the_health_check_lists_agents_processes_with_no_record_data(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    r = await c.get("/health/background")
    assert r.status_code == 200, r.text
    keys = [p["key"] for p in r.json()["processes"]]
    assert keys == [p.key for p in PROCESSES if p.service == "agents"]
