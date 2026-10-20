"""A tool module publish follows the team's publish-review mode, read live (c-139, c-214), by failure mode: a minor
version published at once while the team set "always", a minor version held while it set "major", a change of the
setting that waits for a restart, a policy that cannot be read letting a version through, and a minor review sent to
Security instead of the module's team. Driven through the real routes into the real PublishPolicy; platform-service is
a fake endpoint holding the setting."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.modules.policy import PublishPolicy
from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore

from .conftest import Api, FakeReviews, build_app, response_checker
from .service_clients import fake_service

MOD = "/mod_core_banking"
# What the fake platform-service holds; a test changes it between publishes. None makes the read fail.
SETTING: dict[str, Any] = {"value": {}}


def _platform(_request: httpx.Request) -> httpx.Response:
    if SETTING["value"] is None:
        return httpx.Response(503, json={"success": False, "error": {"code": "unavailable"}})
    return httpx.Response(200, json={"success": True, "data": {"key": "publishReview", "value": SETTING["value"]}})


@pytest.fixture
async def published(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[tuple[Api, FakeReviews, str]]:
    """The seeded tenant behind the real routes, its publish reads routed to the fake platform; with the module's team,
    which the setting is keyed by."""
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    module = await ModuleStore(engine).get(tenant, "mod_core_banking")
    assert module is not None
    reviews = FakeReviews()
    platform = fake_service(_platform, "platform", ["settings:view"])
    app = build_app(engine, seed, tenant, reviews=reviews, publish_policy=PublishPolicy(platform))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://tools",
        event_hooks={"response": [response_checker(app)]},
    ) as c:
        yield Api(c, tenant), reviews, str(module["team_id"])
    SETTING["value"] = {}


async def _minor_publish(api: Api, note: str) -> dict[str, Any]:
    """A description-only edit of one field, a minor change, then publish; the new version."""
    detail = (await api.call("GET", MOD)).json()["data"]
    op = next(o for o in detail["operations"] if o["name"] == "get_customer_profile")
    fields = [{**{k: v for k, v in f.items() if v is not None}, "description": note} for f in op["input"]]
    edited = await api.call("PATCH", f"{MOD}/operations/{op['id']}", json={"input": fields})
    assert edited.status_code == 200, edited.text
    r = await api.call("POST", f"{MOD}/versions", json={"note": note})
    assert r.status_code == 200, r.text
    return r.json()["data"]["versions"][0]


async def test_a_minor_version_follows_the_setting_as_it_is_at_each_publish(
    published: tuple[Api, FakeReviews, str],
) -> None:
    api, reviews, team = published
    SETTING["value"] = {}
    live = await _minor_publish(api, "Clearer field text")
    assert (live["status"], live["reviewRequired"], live["policy"]) == ("published", False, "major"), live
    assert reviews.opened == [], "major lets a minor version through with no review"
    SETTING["value"] = {team: {"tools": "always"}}
    held = await _minor_publish(api, "Clearer still")
    assert (held["status"], held["reviewRequired"], held["policy"]) == ("in_review", True, "always"), held
    assert reviews.opened[-1]["security"] is False, "a minor review is the module's team's, not Security's"


async def test_an_unreadable_policy_holds_the_version(published: tuple[Api, FakeReviews, str]) -> None:
    api, _, _ = published
    SETTING["value"] = None
    held = await _minor_publish(api, "Clearer field text")
    assert (held["status"], held["reviewRequired"], held["policy"]) == ("in_review", True, "always"), held
