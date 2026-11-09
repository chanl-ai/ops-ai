"""Audit entries other services record (ops_store.audit), by failure mode: an entry that never reaches the Audit page,
one delivered twice and shown twice, a token without the scope or without a team writing to the log."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ops_identity import mint_service_token

from .conftest import CALLER, Platform
from .test_audit_route import audit
from .test_members import as_admin


def _token(tenant: str, team: str | None, scopes: list[str]) -> dict[str, str]:
    token = mint_service_token(
        CALLER, service="agents", audience="platform", tenant_id=tenant, team_id=team, scopes=scopes, ttl_s=3600
    )
    return {"Authorization": f"Bearer {token}"}


def _event(key: str) -> dict[str, Any]:
    return {
        "name": "audit.recorded",
        "key": key,
        "actor": "usr_builder",
        "payload": {
            "action": "knowledge.source.settings",
            "targetKind": "knowledge_source",
            "targetId": "src_help",
            "requestId": key,
            "detail": {"summary": "Changed the settings of source Help centre: schedule", "changed": ["schedule"]},
        },
    }


async def test_a_delivered_entry_shows_on_the_audit_page_once_however_often_it_arrives(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    team = h["X-Team-Id"]
    key = f"aud_{uuid4().hex}"
    service = _token(admin.tenant_id, team, ["audit:create"])
    first = await platform.internal.post("/v1/audit-events", json=_event(key), headers=service)
    again = await platform.internal.post("/v1/audit-events", json=_event(key), headers=service)
    assert (first.json()["data"]["written"], again.json()["data"]["written"]) == (True, False), (first.text, again.text)
    rows = [e for e in (await audit(platform, h))["data"] if e["id"] == key]
    assert len(rows) == 1, rows
    assert rows[0]["summary"] == "Changed the settings of source Help centre: schedule"
    assert (rows[0]["targetKind"], rows[0]["kind"]) == ("knowledge_source", "edited")


async def test_a_token_without_the_scope_or_a_team_writes_nothing(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    team = h["X-Team-Id"]
    no_scope = await platform.internal.post(
        "/v1/audit-events", json=_event(f"aud_{uuid4().hex}"), headers=_token(admin.tenant_id, team, [])
    )
    assert no_scope.status_code == 403 and no_scope.json()["error"]["code"] == "scope_required"
    no_team = await platform.internal.post(
        "/v1/audit-events", json=_event(f"aud_{uuid4().hex}"), headers=_token(admin.tenant_id, None, ["audit:create"])
    )
    assert no_team.status_code == 403 and no_team.json()["error"]["code"] == "team_required"
