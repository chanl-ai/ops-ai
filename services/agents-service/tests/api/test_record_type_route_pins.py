"""Every case-type and task-type route's reply, status and error object, value by value, by failure mode: a type or
version row changing a key the type editors read; a refusal (a viewer saving, a bad id, a type that is not there, a
stray body field) changing its status or code. Regenerate with `AGENTS_REPIN=1` only for an intended change."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api import role_app as role_app_module
from tests.api.test_reply_pins import FIXTURES, answer, compare
from tests.engine.test_lifecycle_rights import BUILDER, VIEWER

from .role_app import role_app

_ENGINES: list[AsyncEngine] = []
# Each router: its prefix, a seeded type to copy and the new type's id.
_ROUTERS = (("case-types", "complaint", "fraud_claim"), ("task-types", "write_approval", "vendor_bank_change"))


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    made = role_app_module.create_async_engine

    def kept(*args: Any, **kwargs: Any) -> AsyncEngine:
        _ENGINES.append(engine := made(*args, **kwargs))
        return engine

    monkeypatch.setattr(role_app_module, "create_async_engine", kept)
    async with role_app(TestModel()) as c:
        yield c


async def test_every_record_type_route_keeps_its_reply_status_and_error_object(client: AsyncClient) -> None:
    c = client
    seen: dict[str, Any] = {}
    for prefix, seed, new in _ROUTERS:
        base = f"/v1/{prefix}"
        seen[f"{prefix}.list"] = answer(await c.get(base, headers=VIEWER))
        seen[f"{prefix}.read"] = answer(await c.get(f"{base}/{seed}", headers=VIEWER))
        seen[f"{prefix}.missing"] = answer(await c.get(f"{base}/no_such_type", headers=VIEWER))
        body = {"id": new, "copyOf": {"id": seed}, "name": "Copied"}
        seen[f"{prefix}.create"] = answer(await c.post(base, json=body, headers=BUILDER))
        seen[f"{prefix}.createStray"] = answer(
            await c.post(base, json={**body, "id": "x_other", "colour": 1}, headers=BUILDER)
        )
        seen[f"{prefix}.badId"] = answer(await c.post(base, json={**body, "id": "Bad-Id"}, headers=BUILDER))
        seen[f"{prefix}.viewerCreates"] = answer(await c.post(base, json={**body, "id": "x_viewer"}, headers=VIEWER))
        record = (await c.get(f"{base}/{new}", headers=VIEWER)).json()["data"]["versions"][0]["record"]
        seen[f"{prefix}.save"] = answer(await c.put(f"{base}/{new}/draft", json=record, headers=BUILDER))
        seen[f"{prefix}.viewerSaves"] = answer(await c.put(f"{base}/{new}/draft", json=record, headers=VIEWER))
        seen[f"{prefix}.publish"] = answer(await c.post(f"{base}/{new}/publish", json={"version": 1}, headers=BUILDER))
        seen[f"{prefix}.publishStray"] = answer(
            await c.post(f"{base}/{new}/publish", json={"version": 1, "note": "x"}, headers=BUILDER)
        )
    compare(seen, FIXTURES / "reply-pins-record-types.json")
