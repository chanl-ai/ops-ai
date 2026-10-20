"""Check before sending at the gateway (c-300), on the real Rego in OPA and a seeded tenant's registry, by failure mode:
a write the team's sending policy forbids runs; a judge that cannot be reached lets the write through; a retried
payload is judged twice; with the setting off, on a read, or on a call carrying an approval, a model call is made or
the answer changes. open_case is a write that runs without approval, so it shows the check alone."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import dev_service_signer, mint_service_token
from ops_service_kit.model_calls import ModelCallError, StructuredCalls
from ops_tools.modules.policy import CheckBeforeSend
from ops_tools.modules.seed import load
from ops_tools.send_check import NEEDS_REVIEW, NO_JUDGE, SendCheck
from ops_tools.store.modules import ModuleStore
from ops_tools.store.send_policies import KEEP, SendPolicies, send_checks

from .conftest import build_app, opa_client

TEAM = "team_ops"
POLICY = "Never promise a refund in a case subject."
FORBIDDEN = {"subject": "Refund promised for the double charge"}
ALLOWED = {"subject": "Card stopped working abroad"}


class Setting(CheckBeforeSend):
    def __init__(self, on: bool) -> None:
        super().__init__(cast(Any, None))
        self.value = on

    async def on(self, tenant_id: str, team_id: str | None) -> bool:
        return self.value


class Judge(StructuredCalls):
    """Forbids a subject that promises a refund; counts its calls. `down` stands for models-service out of reach."""

    def __init__(self, *, down: bool = False) -> None:
        super().__init__(cast(Any, None), "mk_test")
        self.calls = 0
        self.down = down

    async def structured(self, system: str, user: str, schema: dict[str, Any], *, tenant: str, step: str) -> Any:
        self.calls += 1
        if self.down:
            raise ModelCallError("models-service could not be reached")
        if "Refund promised" in user:
            return {"ok": False, "reason": "It promises a refund, which the policy forbids."}
        return {"ok": True, "reason": ""}


Call = Callable[..., Any]


@pytest.fixture
def judge() -> Judge:
    return Judge()


async def _gateway(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog: list[dict[str, Any]], check: SendCheck
) -> AsyncIterator[Call]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog)
    await SendPolicies(engine).save(tenant, TEAM, POLICY, by="p@x")
    token = mint_service_token(
        dev_service_signer(), service="agents", audience="tools", tenant_id=tenant, scopes=["tools:view"], team_id=TEAM
    )
    async with opa_client() as opa:
        app = build_app(engine, seed, tenant, opa=opa, send_check=check)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as client,
        ):

            async def call(tool: str, args: dict[str, Any], key: str, **extra: Any) -> httpx.Response:
                body = {"tool": tool, "input": args, "key": key, "runContext": {"act": "test"}, **extra}
                return await client.post("/v1/calls", json=body, headers={"Authorization": f"Bearer {token}"})

            yield call


@pytest.fixture
async def on(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], judge: Judge
) -> AsyncIterator[Call]:
    async for call in _gateway(
        engine, seed, tenant, catalog_tools, SendCheck(SendPolicies(engine), Setting(True), judge)
    ):
        yield call


async def test_a_write_the_policy_forbids_waits_for_a_person_with_the_reason(on: Call, judge: Judge) -> None:
    r = await on("open_case", FORBIDDEN, "k1")
    assert (r.status_code, r.json()["error"]["code"]) == (409, NEEDS_REVIEW), r.text
    assert r.json()["error"]["details"]["reasons"] == ["It promises a refund, which the policy forbids."]
    allowed = await on("open_case", ALLOWED, "k2")
    assert allowed.json()["data"]["decision"] == "allow", allowed.text
    assert judge.calls == 2


async def test_the_same_payload_is_judged_once(on: Call, judge: Judge) -> None:
    first, again = await on("open_case", FORBIDDEN, "k3"), await on("open_case", FORBIDDEN, "k4")
    assert first.status_code == again.status_code == 409 and judge.calls == 1


async def test_a_read_or_a_call_with_an_approval_is_not_judged(on: Call, judge: Judge) -> None:
    await on("lookup_account", {"accountId": "CHQ-2219"}, "k5")
    await on("open_case", FORBIDDEN, "k6", approvalToken="not-a-real-token")
    assert judge.calls == 0


async def test_a_judge_out_of_reach_sends_the_write_to_a_person(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> None:
    down = Judge(down=True)
    async for call in _gateway(
        engine, seed, tenant, catalog_tools, SendCheck(SendPolicies(engine), Setting(True), down)
    ):
        r = await call("open_case", ALLOWED, "k7")
        assert (r.status_code, r.json()["error"]["details"]["reasons"]) == (409, [NO_JUDGE]), r.text


async def test_with_the_setting_off_nothing_is_judged(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], judge: Judge
) -> None:
    async for call in _gateway(
        engine, seed, tenant, catalog_tools, SendCheck(SendPolicies(engine), Setting(False), judge)
    ):
        r = await call("open_case", FORBIDDEN, "k8")
        assert r.json()["data"]["decision"] == "allow" and judge.calls == 0, r.text


async def test_a_team_saves_its_sending_policy_as_versions_and_reads_the_newest(api: Any, seed: dict[str, Any]) -> None:
    user, team = seed["currentUser"], TEAM
    empty = await api.client.get("/v1/send-policy", headers={"X-Dev-User": user, "X-Team-Id": team})
    assert empty.status_code == 200 and empty.json()["data"] is None, empty.text
    for text in ("No refunds promised.", POLICY):
        saved = await api.client.put(
            "/v1/send-policy", json={"text": text}, headers={"X-Dev-User": user, "X-Team-Id": team}
        )
        assert saved.status_code == 200, saved.text
    newest = (await api.client.get("/v1/send-policy", headers={"X-Dev-User": user, "X-Team-Id": team})).json()["data"]
    assert (newest["version"], newest["text"]) == (2, POLICY)


async def test_judgements_nobody_can_read_again_are_not_kept(engine: AsyncEngine, tenant: str) -> None:
    """tick 31: send_checks only grew. Judgements against an older policy version go when a new one is saved, and
    any past KEEP go as the next one is kept."""
    store = SendPolicies(engine)
    await store.save(tenant, TEAM, POLICY, by="p@x")
    await store.keep(tenant, TEAM, "h-old-version", 1, ok=False, reason="r")
    await store.save(tenant, TEAM, POLICY + " v2", by="p@x")
    assert await store.judged(tenant, TEAM, "h-old-version", 1) is None
    async with engine.begin() as c:
        old = (datetime.now(UTC) - KEEP - timedelta(days=1)).isoformat()
        await c.execute(
            send_checks.insert().values(
                tenant_id=tenant,
                team_id=TEAM,
                input_hash="h-aged",
                policy_version=2,
                ok=True,
                reason="",
                checked_at=old,
            )
        )
    await store.keep(tenant, TEAM, "h-new", 2, ok=True, reason="")
    assert await store.judged(tenant, TEAM, "h-aged", 2) is None
    assert await store.judged(tenant, TEAM, "h-new", 2) is not None
