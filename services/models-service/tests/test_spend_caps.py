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
