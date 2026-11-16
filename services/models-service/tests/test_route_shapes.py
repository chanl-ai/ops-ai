"""Today's reply keys and accepted bodies on the routes no other test pins, held while the store and request layers
move onto the shared components. Every reply is also checked against the app's OpenAPI document (conftest)."""

from __future__ import annotations

from uuid import uuid4

from .conftest import SERVICE, Models

ALIAS_KEYS = {
    "name",
    "version",
    "kind",
    "providerId",
    "modelId",
    "clearedSensitivity",
    "inputPerMillion",
    "outputPerMillion",
    "status",
    "reasoningEffort",
    "images",
}


async def test_the_alias_list_holds_each_aliases_serving_version_only(models: Models) -> None:
    name = f"shape-{uuid4().hex[:8]}"
    version = {"providerId": "prov_scripted", "modelId": "m-1", "clearedSensitivity": "internal"}
    made = await models.client.post("/v1/models/aliases", json={**version, "name": name}, headers=SERVICE)
    assert made.status_code == 201, made.text
    again = {**version, "modelId": "m-2", "inputPerMillion": "1.5"}
    added = await models.client.post(f"/v1/models/aliases/{name}/versions", json=again, headers=SERVICE)
    assert added.json()["data"] == {"name": name, "version": 2}

    r = await models.client.get("/v1/models/aliases", headers=SERVICE)

    assert r.status_code == 200
    listed = [a for a in r.json()["data"] if a["name"] == name]
    assert listed == [
        {
            "name": name,
            "version": 2,
            "kind": "chat",
            "providerId": "prov_scripted",
            "modelId": "m-2",
            "clearedSensitivity": "internal",
            "inputPerMillion": "1.500000",
            "outputPerMillion": "0.000000",
            "status": "current",
            "reasoningEffort": None,
            "images": False,
        }
    ]
    names = [a["name"] for a in r.json()["data"]]
    assert len(names) == len(set(names))
    assert all(set(a) == ALIAS_KEYS for a in r.json()["data"])


async def test_a_body_takes_camel_or_snake_names_and_refuses_an_unknown_one(models: Models) -> None:
    camel = {"id": f"workflow:shape-{uuid4().hex[:8]}", "kind": "workflow", "budget": "1", "rateLimitPerMinute": 5}
    snake = {"id": f"workflow:shape-{uuid4().hex[:8]}", "kind": "workflow", "budget": "1", "rate_limit_per_minute": 7}
    for body, limit in ((camel, 5), (snake, 7)):
        r = await models.client.post("/v1/models/keys", json=body, headers=SERVICE)
        assert r.status_code == 201, r.text
        assert set(r.json()["data"]) == {"id", "secret"}
        keys = (await models.client.get("/v1/models/keys", headers=SERVICE)).json()["data"]
        assert next(k for k in keys if k["id"] == body["id"])["rateLimitPerMinute"] == limit

    unknown = {**camel, "id": f"workflow:shape-{uuid4().hex[:8]}", "colour": "red"}
    r = await models.client.post("/v1/models/keys", json=unknown, headers=SERVICE)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "validation_failed"
