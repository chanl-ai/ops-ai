"""An API key scoped to one agent or workflow (c-246), by failure mode: the target is lost before agents-service sees
it; a target the key could never start is accepted; the service list of keys leaks another workspace's keys, a
secret or the creator, or answers a person."""

from __future__ import annotations

from .conftest import SERVICE, Platform
from .test_api_keys import create
from .test_members import as_admin
from .test_team_names import service

TARGET = {"kind": "workflow", "id": "levy_intake", "version": 3}


async def test_the_target_reaches_introspection(platform: Platform) -> None:
    _, h = await as_admin(platform)
    made = await create(platform, h, scopes=["write"], target=TARGET)
    key_id = made["key"]["id"]  # type: ignore[index]
    assert made["key"]["target"] == TARGET  # type: ignore[index]
    r = await platform.internal.post("/v1/auth/introspect", json={"apiKey": made["secret"]}, headers=SERVICE)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["apiKey"] == {"id": key_id, "target": TARGET}
    plain = await create(platform, h, scopes=["write"])
    r = await platform.internal.post("/v1/auth/introspect", json={"apiKey": plain["secret"]}, headers=SERVICE)
    assert r.json()["data"]["apiKey"] == {"id": plain["key"]["id"], "target": None}  # type: ignore[index]


async def test_a_target_the_key_could_never_start_is_refused(platform: Platform) -> None:
    _, h = await as_admin(platform)
    read_only = await platform.public.post(
        "/v1/api-keys", headers=h, json={"name": "ci", "scopes": ["read"], "target": TARGET}
    )
    assert read_only.status_code == 400 and "write scope" in read_only.text
    pinned_agent = {"kind": "agent", "id": "ag_levy", "version": 2}
    r = await platform.public.post(
        "/v1/api-keys", headers=h, json={"name": "ci", "scopes": ["write"], "target": pinned_agent}
    )
    assert r.status_code == 400 and "latest published" in r.text


async def test_only_a_scoped_service_lists_every_teams_keys_and_no_secret(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    made = await create(platform, h, scopes=["write"], target=TARGET)
    r = await platform.public.get("/v1/api-key-summaries", headers=service(["settings:view"], admin.tenant_id))
    assert r.status_code == 200, r.text
    [row] = r.json()["data"]
    assert (row["id"], row["teamId"], row["target"], row["status"]) == (
        made["key"]["id"],  # type: ignore[index]
        h["X-Team-Id"],
        TARGET,
        "active",
    )
    assert str(made["secret"]).split(".", 1)[1] not in r.text and "createdBy" not in row
    other = await platform.public.get("/v1/api-key-summaries", headers=service(["settings:view"], "ten_other"))
    assert other.json()["data"] == []
    bare = await platform.public.get("/v1/api-key-summaries", headers=service([], admin.tenant_id))
    assert (bare.status_code, bare.json()["error"]["code"]) == (403, "scope_required")
    assert (await platform.public.get("/v1/api-key-summaries", headers=h)).status_code == 403
