"""Govern > Evals and an agent's Evals tab on stored data, by failure mode: another team's suites, runs or cases read
or deleted, a repeated run overwriting the first, two people adding a case at once and one case lost, the runs list
leaving out workflows, counts that differ from the rows, tabs with nothing behind them, a failing publish check that
does not block, and who may save cases."""

# ruff: noqa: F811 - the dev_platform fixture is imported, then named as a parameter
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from httpx import AsyncClient

from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint

from .test_agent_registry import _ok  # pyright: ignore[reportPrivateUsage]
from .test_write_approval_policy import (
    PLATFORM,
    dev_platform,  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixture
)


def person(sub: str, role: str, team: str = "team_ops") -> dict[str, str]:
    claims = {
        "sub": sub,
        "email": f"{sub}@harborpine.example",
        "name": sub,
        "kind": "person",
        "security_team": "team_security",
        "aud": ["agents"],
        "tenant_id": "acme",
        "team_ids": [team],
        "roles": {team: role},
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": team}


who = person
LENDING, OPS = person("usr_lend", "admin", "team_lending"), person("usr_ops", "admin")


class _EveryChangeWaits:
    """The team's publishReview setting as platform-service answers it: every agents change waits for a reviewer."""

    async def value(self, key: str) -> Any:
        return {"team_ops": {"agents": "always"}} if key == "publishReview" else None


@asynccontextmanager
async def _same(client: AsyncClient) -> AsyncGenerator[AsyncClient]:
    yield client


PASSING = {"name": "greets", "input": "Hello", "checks": [{"type": "reply_contains", "text": "could not find"}]}
FAILING = {"name": "calls lookup", "input": "Hello", "checks": [{"type": "calls_tool", "tool": "lookup_account"}]}


async def _agent(c: AsyncClient, headers: dict[str, str], name: str = "Payee Checker") -> str:
    made = _ok(await c.post("/v1/agents", json={"name": name, "role": "Checks payees"}, headers=headers), 201)
    return str(made["id"])


async def _save(c: AsyncClient, aid: str, cases: list[dict[str, Any]], headers: dict[str, str]) -> Any:
    return await c.put(f"/v1/agents/{aid}/eval-cases", json={"cases": cases}, headers=headers)


async def _tab(c: AsyncClient, tab: str, headers: dict[str, str], **params: Any) -> Any:
    return _ok(await c.get(f"/v1/assurance/{tab}", params=params, headers=headers))


async def test_another_teams_suites_runs_cases_and_counts_are_never_shown_or_deleted(dev_platform: AsyncClient) -> None:
    async with _same(dev_platform) as c:
        theirs = await _agent(c, LENDING)
        (case,) = _ok(await _save(c, theirs, [PASSING], LENDING))["cases"]
        run = _ok(await c.post(f"/v1/agents/{theirs}/eval-runs", headers=LENDING))
        mine = await _tab(c, "suites", OPS)
        assert mine["data"] == [] and mine["tabCounts"]["suites"] == 0 and mine["tabCounts"]["runs"] == 0
        assert mine["stats"]["notRun"] == 0 and mine["stats"]["failingSuites"] == 0
        assert (await _save(c, theirs, [PASSING], OPS)).status_code == 404
        assert (await c.post(f"/v1/agents/{theirs}/eval-runs", headers=OPS)).status_code == 404
        assert (await c.get(f"/v1/eval-runs/{run['id']}", headers=OPS)).status_code == 404
        assert (await c.delete(f"/v1/eval-cases/{case['id']}", headers=OPS)).status_code == 404
        kept = _ok(await c.get(f"/v1/agents/{theirs}/eval-cases", headers=LENDING))
        assert [x["id"] for x in kept["cases"]] == [case["id"]], "the other team's delete removed nothing"
        assert _ok(await c.get(f"/v1/eval-runs/{run['id']}", headers=LENDING))["id"] == run["id"]


async def test_running_saved_cases_twice_stores_two_runs_newest_first(dev_platform: AsyncClient) -> None:
    async with _same(dev_platform) as c:
        aid = await _agent(c, OPS)
        _ok(await _save(c, aid, [PASSING, FAILING], OPS))
        first = _ok(await c.post(f"/v1/agents/{aid}/eval-runs", headers=OPS))
        second = _ok(await c.post(f"/v1/agents/{aid}/eval-runs", headers=OPS))
        assert first["id"] != second["id"] and second["summary"] == {"passed": 1, "total": 2, "regressions": 0}
        assert (second["version"], second["trigger"], second["startedBy"]) == (
            1,
            "manual",
            "usr_ops@harborpine.example",
        )
        runs = f"/v1/agents/{aid}/eval-runs"
        newest = _ok(await c.get(runs, params={"pageSize": 1}, headers=OPS))
        older = _ok(await c.get(runs, params={"pageSize": 1, "page": 2}, headers=OPS))
        assert newest["data"] == [second] and older["data"] == [first], "each row is the run as it was stored"
        assert newest["pagination"]["total"] == 2 and newest["pagination"]["hasNext"] is True
        assert _ok(await c.get(f"/v1/eval-runs/{first['id']}", headers=OPS)) == first
        suite = (await _tab(c, "suites", OPS))["data"][0]
        assert suite["passRate"] == 0.5 and suite["failing"] is True and suite["cases"] == 2
        assert [r["name"] for r in suite["results"]] == ["greets", "calls lookup"]


async def test_two_people_adding_a_case_each_keep_theirs(dev_platform: AsyncClient) -> None:
    async with _same(dev_platform) as c:
        aid, builder = await _agent(c, OPS), who("usr_b", "builder")
        cases = f"/v1/agents/{aid}/eval-cases"
        added = [await c.post(cases, json={"cases": [x]}, headers=h) for x, h in ((PASSING, OPS), (FAILING, builder))]
        assert [r.status_code for r in added] == [201, 201], [r.text for r in added]
        kept = _ok(await c.get(cases, headers=OPS))["cases"]
        assert [(x["name"], x["createdBy"]) for x in kept] == [
            ("greets", "usr_ops@harborpine.example"),
            ("calls lookup", "usr_b@harborpine.example"),
        ]


async def test_a_workflow_test_run_is_listed_with_agent_runs(dev_platform: AsyncClient) -> None:
    async with _same(dev_platform) as c:
        aid = await _agent(c, OPS)
        _ok(await _save(c, aid, [PASSING], OPS))
        _ok(await c.post(f"/v1/agents/{aid}/eval-runs", headers=OPS))
        wf = _ok(
            await c.post("/v1/workflows", json={"name": "Triage", "trigger": "email"}, headers=OPS),
            201,
        )
        graph = _ok(await c.get(f"/v1/workflows/{wf['id']}", headers=OPS))["draft"]["graph"]
        _ok(await c.post(f"/v1/workflows/{wf['id']}/validate", json={"graph": graph, "target": "draft"}, headers=OPS))
        runs = (await _tab(c, "runs", OPS))["data"]
        assert [r["asset"]["kind"] for r in runs] == ["workflow", "agent"]
        assert runs[0]["asset"]["href"] == f"/build/workflows/{wf['id']}"
        assert {s["asset"]["kind"] for s in (await _tab(c, "suites", OPS))["data"]} == {"agent", "workflow"}


async def test_stats_and_tab_counts_equal_the_rows_each_tab_lists(dev_platform: AsyncClient) -> None:
    async with _same(dev_platform) as c:
        ok_agent, bad_agent, idle = await _agent(c, OPS, "A"), await _agent(c, OPS, "B"), await _agent(c, OPS, "C")
        _ok(await _save(c, ok_agent, [PASSING], OPS))
        _ok(await _save(c, bad_agent, [FAILING], OPS))
        _ok(await _save(c, idle, [PASSING], OPS))
        for aid in (ok_agent, bad_agent):
            _ok(await c.post(f"/v1/agents/{aid}/eval-runs", headers=OPS))
        suites = await _tab(c, "suites", OPS)
        assert suites["tabCounts"] == {"suites": 3, "runs": 2, "gates": 0}
        assert (
            suites["stats"]["failingSuites"]
            == 1
            == len(suites["facets"]["result"] and [s for s in suites["data"] if s["failing"]])
        )
        assert suites["stats"]["notRun"] == 1
        assert suites["facets"]["result"] == {"failing": 1, "passing": 1, "not_run": 1}
        failing = await _tab(c, "suites", OPS, result="failing")
        assert [s["asset"]["name"] for s in failing["data"]] == ["B"]
        assert len((await _tab(c, "runs", OPS))["data"]) == suites["tabCounts"]["runs"]


async def test_evidence_and_judges_are_not_offered_until_something_backs_them(dev_platform: AsyncClient) -> None:
    async with _same(dev_platform) as c:
        assert set((await _tab(c, "suites", OPS))["tabCounts"]) == {"suites", "runs", "gates"}
        for tab in ("evidence", "judges"):
            assert (await c.get(f"/v1/assurance/{tab}", headers=OPS)).status_code == 404


async def test_a_publish_request_with_a_failing_pass_rate_is_blocked_and_names_the_step(
    dev_platform: AsyncClient,
) -> None:
    async with _same(dev_platform) as c:
        aid = await _agent(c, OPS)
        _ok(await _save(c, aid, [PASSING, FAILING], OPS))
        _ok(await c.post(f"/v1/agents/{aid}/eval-runs", headers=OPS))
        runtime = dev_platform._transport.app.state.runtime  # type: ignore[attr-defined]  # pyright: ignore
        runtime.policies = _EveryChangeWaits()
        _ok(await c.post(f"/v1/agents/{aid}/publish-requests", json={"version": 1, "note": "go"}, headers=OPS), 201)
        gates = await _tab(c, "gates", OPS)
        (gate,) = gates["data"]
        step = next(s for s in gate["steps"] if s["step"] == "pass_rate")
        assert (gate["blocked"], step["result"], step["mode"]) == (True, "fail", "blocking")
        assert "1 of 2" in step["detail"] and gate["toVersion"] == 1 and gate["reviewStatus"] == "pending"
        assert gates["stats"]["gatesBlocked"] == 1 and gates["tabCounts"]["gates"] == 1


async def test_only_builders_save_and_run_cases_while_viewers_read_and_chat_users_do_not(
    dev_platform: AsyncClient,
) -> None:
    builder, viewer, chat = who("usr_b", "builder"), who("usr_v", "viewer"), who("usr_c", "chat_user")
    aid = await _agent(dev_platform, who("usr_a", "admin"))
    _ok(await _save(dev_platform, aid, [PASSING], builder))
    assert (await _save(dev_platform, aid, [PASSING], viewer)).status_code == 403
    assert (await dev_platform.post(f"/v1/agents/{aid}/eval-runs", headers=viewer)).status_code == 403
    assert len((await _tab(dev_platform, "suites", viewer))["data"]) == 1
    assert (await dev_platform.get("/v1/assurance/suites", headers=chat)).status_code == 403


async def test_saving_an_unknown_check_type_is_refused_and_keeps_the_saved_cases(dev_platform: AsyncClient) -> None:
    async with _same(dev_platform) as c:
        aid = await _agent(c, OPS)
        _ok(await _save(c, aid, [PASSING], OPS))
        bad = await _save(c, aid, [{"name": "x", "input": "y", "checks": [{"type": "rubric", "text": "kind"}]}], OPS)
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "unknown_check_type"
        kept = _ok(await c.get(f"/v1/agents/{aid}/eval-cases", headers=OPS))
        assert [x["name"] for x in kept["cases"]] == ["greets"]
