"""models-service, one test per way a model call could escape its key, its budget or its alias's clearance."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from ops_models.store import model_aliases, model_keys

from .conftest import SERVICE, Models


async def admit(m: Models, key_id: str, **extra: object) -> tuple[int, str | None]:
    r = await m.client.post("/v1/models/admit", json={"keyId": key_id, **extra}, headers=SERVICE)
    error: dict[str, str] = r.json().get("error") or {}
    return r.status_code, error.get("code")


async def test_admin_routes_are_internal(models: Models) -> None:
    assert (await models.client.get("/v1/models/keys")).status_code == 401
    assert (await models.client.post("/v1/models/admit", json={"keyId": "agent:ag_fraud"})).status_code == 401
    # The old shared static token names no service and no tenant, so it is refused like no token at all.
    static = {"Authorization": "Bearer dev-service-token-not-secret"}
    assert (await models.client.get("/v1/models/keys", headers=static)).status_code == 401


async def test_a_key_at_its_budget_is_refused(models: Models) -> None:
    key_id, secret = await models.key(budget="0")
    assert await admit(models, key_id) == (429, "key_budget_exhausted")
    r = await models.complete(secret)
    assert r.status_code == 429 and r.json()["error"]["code"] == "key_budget_exhausted"


async def test_spend_reaches_the_cap_and_the_next_call_is_refused(models: Models) -> None:
    # Below one call's cost: the check runs before the call, so the first call may overshoot the cap by itself.
    key_id, secret = await models.key(budget="0.000040")
    first = await models.complete(secret)
    assert first.status_code == 200, first.text
    assert await models.spent(key_id) > 0
    second = await models.complete(secret)
    assert second.status_code == 429


async def test_an_estimate_over_what_is_left_is_refused(models: Models) -> None:
    key_id, _ = await models.key(budget="0.01")
    assert await admit(models, key_id) == (200, None)
    assert await admit(models, key_id, alias="bank-standard", estimatedTokens=1_000_000) == (
        429,
        "key_budget_exhausted",
    )


async def test_an_expired_key_is_refused(models: Models) -> None:
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    key_id, secret = await models.key(budget="5", expiresAt=past)
    assert await admit(models, key_id) == (403, "key_expired")
    assert (await models.complete(secret)).status_code == 403


async def test_an_unregistered_identity_is_refused(models: Models) -> None:
    assert await admit(models, "user:nobody@example.com") == (403, "key_not_registered")
    assert (await models.complete("mk_guessed")).status_code == 401


async def test_an_alias_not_cleared_for_the_data_is_refused(models: Models) -> None:
    # bank-reasoning is cleared for internal data; a confidential request must not reach it.
    key_id, secret = await models.key(budget="5")
    r = await models.complete(secret, alias="bank-reasoning", **{"X-Data-Sensitivity": "confidential"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "sensitivity_not_cleared"
    ok = await models.complete(secret, alias="bank-standard", **{"X-Data-Sensitivity": "confidential"})
    assert ok.status_code == 200
    assert [(c["outcome"], c["reason"]) for c in reversed(await models.calls(key_id))] == [
        ("denied", "sensitivity_not_cleared"),
        ("ok", None),
    ]


async def test_an_image_reaches_only_an_alias_cleared_for_images_and_every_call_counts_them(models: Models) -> None:
    """A page image carries the whole page (c-295): bank-standard is cleared for confidential data but not images, so
    an image part is refused there and logged; a version cleared for images takes it, and both rows count it."""
    key_id, secret = await models.key(budget="5")
    page = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
    messages = [{"role": "user", "content": [{"type": "text", "text": "Fields: total"}, page]}]
    auth = {"Authorization": f"Bearer {secret}"}
    refused = await models.client.post(
        "/v1/models/chat/completions", json={"model": "bank-standard", "messages": messages}, headers=auth
    )
    assert (refused.status_code, refused.json()["error"]["code"]) == (403, "images_not_cleared"), refused.text
    name = f"pages-{uuid4().hex[:8]}"
    alias = {"name": name, "providerId": "prov_scripted", "modelId": "scripted-pages", "clearedSensitivity": "internal"}
    made = await models.client.post("/v1/models/aliases", json={**alias, "images": True}, headers=SERVICE)
    assert made.status_code == 201, made.text
    versions = (await models.client.get(f"/v1/models/aliases/{name}/versions", headers=SERVICE)).json()["data"]
    assert [v["images"] for v in versions] == [True]
    sent = await models.client.post(
        "/v1/models/chat/completions", json={"model": name, "messages": messages}, headers=auth
    )
    assert sent.status_code == 200, sent.text
    # Any part that is not text counts, whatever it is called: a file, or a kind no provider has named yet.
    for other in ({"type": "file", "file": {"file_data": "data:application/pdf;base64,JVBERi0="}}, {"type": "x-new"}):
        body = {"model": "bank-standard", "messages": [{"role": "user", "content": [other]}]}
        r = await models.client.post("/v1/models/chat/completions", json=body, headers=auth)
        assert r.status_code == 403, (other, r.text)
    assert [(c["outcome"], c["reason"], c["images"]) for c in reversed(await models.calls(key_id))] == [
        ("denied", "images_not_cleared", 1),
        ("ok", None, 1),
        ("denied", "images_not_cleared", 1),
        ("denied", "images_not_cleared", 1),
    ]


async def test_a_completion_writes_one_metadata_row_and_no_prompt_text(models: Models) -> None:
    key_id, secret = await models.key(budget="5")
    r = await models.complete(secret, **{"X-Run-Id": "run_1", "X-Step-Id": "draft"})
    assert r.status_code == 200 and r.json()["object"] == "chat.completion"
    rows = await models.calls(key_id)
    assert len(rows) == 1
    assert (rows[0]["outcome"], rows[0]["runId"], rows[0]["stepId"]) == ("ok", "run_1", "draft")
    assert rows[0]["inputTokens"] > 0 and float(rows[0]["cost"]) > 0
    stored = json.dumps(rows[0])
    # Any fragment of the prompt or the completion would show the row holds content, not metadata.
    for fragment in ("Summarise", "dispute", "DSP-2210", "scripted reply"):
        assert fragment not in stored, fragment


async def test_rotation_keeps_the_old_secret_for_the_overlap_only(models: Models) -> None:
    key_id, old = await models.key(budget="5")
    r = await models.client.post(f"/v1/models/keys/{key_id}/rotate", json={"overlapSeconds": 1}, headers=SERVICE)
    new = str(r.json()["data"]["secret"])
    assert (await models.complete(old)).status_code == 200
    assert (await models.complete(new)).status_code == 200
    await asyncio.sleep(1.2)
    assert (await models.complete(old)).status_code == 401
    assert (await models.complete(new)).status_code == 200


async def test_a_key_over_its_rate_limit_is_refused(models: Models) -> None:
    _, secret = await models.key(budget="5", rateLimitPerMinute=2)
    codes = [(await models.complete(secret)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


async def test_an_alias_name_may_contain_a_dot(models: Models) -> None:
    """make up creates alias gpt-5.5; a hyphen-only pattern refused it on a fresh database."""
    body = {
        "name": "gpt-5.5",
        "providerId": "prov_scripted",
        "modelId": "scripted-standard",
        "clearedSensitivity": "internal",
    }
    r = await models.client.post("/v1/models/aliases", json=body, headers=SERVICE)
    assert r.status_code == 201, r.text
    versions = (await models.client.get("/v1/models/aliases/gpt-5.5/versions", headers=SERVICE)).json()["data"]
    assert versions[0]["modelId"] == "scripted-standard"


async def test_alias_versions_are_immutable_and_the_newest_serves(models: Models) -> None:
    name = f"bank-test-{datetime.now(UTC).strftime('%H%M%S%f')}"
    body = {"name": name, "providerId": "prov_scripted", "modelId": "scripted-a", "clearedSensitivity": "internal"}
    assert (await models.client.post("/v1/models/aliases", json=body, headers=SERVICE)).status_code == 201
    v2 = {"providerId": "prov_scripted", "modelId": "scripted-b", "clearedSensitivity": "internal"}
    r = await models.client.post(f"/v1/models/aliases/{name}/versions", json=v2, headers=SERVICE)
    assert r.json()["data"]["version"] == 2
    versions = (await models.client.get(f"/v1/models/aliases/{name}/versions", headers=SERVICE)).json()["data"]
    assert [v["modelId"] for v in versions] == ["scripted-a", "scripted-b"]
    key_id, secret = await models.key(budget="5")
    assert (await models.complete(secret, alias=name)).status_code == 200
    assert (await models.calls(key_id))[0]["providerModel"] == "scripted-b"


async def test_a_call_carries_the_callers_request_hash_and_is_found_by_thread(models: Models) -> None:
    key_id, secret = await models.key(budget="5")
    thread = f"th_{datetime.now(UTC).strftime('%H%M%S%f')}"
    r = await models.complete(secret, **{"X-Thread-Id": thread, "X-Request-Hash": "a" * 64})
    assert r.status_code == 200
    rows = (await models.client.get("/v1/models/calls", params={"threadId": thread}, headers=SERVICE)).json()
    assert [(c["keyId"], c["requestHash"]) for c in rows["data"]["items"]] == [(key_id, "a" * 64)]


async def test_one_tenant_spending_its_share_of_a_shared_key_leaves_other_tenants_theirs(models: Models) -> None:
    """c-251: files-service extracts for every tenant on one key; a tenant that spends its share is refused while the
    next tenant still reads, and a call that names no tenant is refused rather than charged to the whole key."""
    key_id, secret = await models.key(budget="1")
    async with models.engine.begin() as c:
        # Below one call's cost, as above: the first call by a tenant overshoots its share, the next is refused.
        await c.execute(model_keys.update().where(model_keys.c.id == key_id).values(tenant_budget=Decimal("0.000040")))
    first = await models.complete(secret, **{"X-Tenant-Id": "t_a"})
    again = await models.complete(secret, **{"X-Tenant-Id": "t_a"})
    other = await models.complete(secret, **{"X-Tenant-Id": "t_b"})
    nobody = await models.complete(secret)
    assert first.status_code == 200 and other.status_code == 200, (first.text, other.text)
    assert (again.status_code, again.json()["error"]["code"]) == (429, "tenant_budget_exhausted"), again.text
    assert (nobody.status_code, nobody.json()["error"]["code"]) == (400, "tenant_required"), nobody.text


async def test_a_new_version_retires_the_one_serving_and_only_one_is_current(models: Models) -> None:
    # Shared's chat alias had seven current versions (2026-10-18): which served was the query's order, not a rule.
    name = f"bank-cur-{datetime.now(UTC).strftime('%H%M%S%f')}"
    body = {"name": name, "providerId": "prov_scripted", "modelId": "scripted-a", "clearedSensitivity": "internal"}
    assert (await models.client.post("/v1/models/aliases", json=body, headers=SERVICE)).status_code == 201
    for model in ("scripted-b", "scripted-c"):
        v = {"providerId": "prov_scripted", "modelId": model, "clearedSensitivity": "internal"}
        assert (await models.client.post(f"/v1/models/aliases/{name}/versions", json=v, headers=SERVICE)).is_success
    versions = (await models.client.get(f"/v1/models/aliases/{name}/versions", headers=SERVICE)).json()["data"]
    assert [(v["modelId"], v["status"]) for v in versions] == [
        ("scripted-a", "retired"),
        ("scripted-b", "retired"),
        ("scripted-c", "current"),
    ]
    with pytest.raises(IntegrityError):
        async with models.engine.begin() as c:
            await c.execute(model_aliases.update().where(model_aliases.c.name == name).values(status="current"))
