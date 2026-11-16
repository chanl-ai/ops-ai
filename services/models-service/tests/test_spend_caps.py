"""Spend ceilings from the call log, by failure mode: a run that goes on calling past its ceiling, a key that goes on
calling past its daily cap, and a ceiling counted by the caller (which a second process, or a retry, gets around)
rather than from what models-service recorded."""

from __future__ import annotations

from decimal import Decimal

from ops_models.store import ModelKeys

from .conftest import Models


async def test_a_run_stops_at_its_ceiling_from_its_recorded_spend(models: Models) -> None:
    _, secret = await models.key(budget="5")
    run = {"X-Run-Id": "run_faq_1", "X-Run-Spend-Cap": "0.00001"}
    assert (await models.complete(secret, **run)).status_code == 200, "under the ceiling: answered"
    refused = await models.complete(secret, **run)
    assert refused.status_code == 429 and refused.json()["error"]["code"] == "run_spend_cap", refused.text
    other = await models.complete(secret, **{**run, "X-Run-Id": "run_faq_2"})
    assert other.status_code == 200, "another run has its own ceiling"


async def test_a_key_stops_at_its_daily_cap(models: Models) -> None:
    key_id, secret = await models.key(budget="5")
    await ModelKeys(models.engine).set_daily_cap(key_id, Decimal("0.00001"))
    assert (await models.complete(secret)).status_code == 200
    refused = await models.complete(secret)
    assert refused.status_code == 429 and refused.json()["error"]["code"] == "daily_spend_cap", refused.text
    await ModelKeys(models.engine).set_daily_cap(key_id, None)
    assert (await models.complete(secret)).status_code == 200


async def test_a_keys_caps_count_the_calls_it_made_for_every_tenant(models: Models) -> None:
    """A key spent for many tenants: its daily and run caps are the key's, so a tenant that never called is refused
    once another tenant's calls reached them, and its rate limit counts a refused call too."""
    key_id, secret = await models.key(budget="5", rateLimitPerMinute=2)
    run = {"X-Run-Id": "run_shared_1", "X-Run-Spend-Cap": "0.00001"}
    assert (await models.complete(secret, **run, **{"X-Tenant-Id": "t_a"})).status_code == 200
    refused = await models.complete(secret, **run, **{"X-Tenant-Id": "t_b"})
    assert (refused.status_code, refused.json()["error"]["code"]) == (429, "run_spend_cap"), refused.text
    over = await models.complete(secret, **{"X-Tenant-Id": "t_c"})
    assert (over.status_code, over.json()["error"]["code"]) == (429, "rate_limited"), over.text
    await ModelKeys(models.engine).set_daily_cap(key_id, Decimal("0.00001"))
    daily = await models.complete(secret, **{"X-Tenant-Id": "t_d", "X-Run-Id": "run_shared_2"})
    assert (daily.status_code, daily.json()["error"]["code"]) == (429, "daily_spend_cap"), daily.text
