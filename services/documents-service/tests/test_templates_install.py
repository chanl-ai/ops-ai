"""Installing a plugin's document type as a team's own copy, through the real routes, by failure mode: the list
shows a template the team cannot install, or hides which ones it already holds; a copy is made some way other than the
create route, so it reads differently from a type a person made; a second install of the same version makes a second
copy; a copy whose type is gone blocks the template for good; an install of a template whose plugin is off for the team,
or of a version it does not ship, makes something anyway; another team sees or reads the copy; a template body's own id
makes the second team's install collide with the first's; and the read from tools-service names no team.

tools-service is faked at the service client documents-service calls it through: it answers the templates a team sees,
as GET /v1/plugin-templates does (tools-service's own tests prove that answer)."""

from __future__ import annotations

from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.store.document_types import document_type_versions, document_types
from ops_documents.tools_client import PluginTemplates

from .conftest import Make, Service

SOURCE = "plugin:test.templates"
ON, OTHER, OFF = "team_ops", "team_claims", "team_platform"
OPS, CLAIMS, PLATFORM = ({"X-Team-Id": t} for t in (ON, OTHER, OFF))

LETTER: dict[str, Any] = {
    "source": SOURCE,
    "plugin": {"id": "test.templates", "title": "Case desk", "version": "0.2.0"},
    "kind": "document_type",
    "id": "case-letter",
    "version": 1,
    "title": "Case letter",
    "requires": {"tools": [], "bind": []},
    "digest": "a" * 64,
    "body": {
        # A body's own id is never the copy's: ids are unique per tenant, so a second team's copy would collide.
        "id": "case_letter",
        "name": "Case letter",
        "description": "A letter about a case, with its number and date",
        "fields": [
            {"key": "case_number", "label": "Case number", "type": "text", "required": True, "keyField": True},
            {"key": "letter_date", "label": "Letter date", "type": "date", "required": True},
        ],
    },
}


class Tools:
    """tools-service's GET /v1/plugin-templates as the service client reaches it: the plugin is on for the teams in
    `on`, and a team it is off for sees nothing."""

    def __init__(self, listed: list[dict[str, Any]], on: tuple[str, ...] = (ON, OTHER)) -> None:
        self.listed = listed
        self.on = on
        self.asked: list[tuple[str | None, str | None]] = []

    async def get(
        self, path: str, *, params: dict[str, Any] | None = None, tenant: str | None = None, team: str | None = None
    ) -> Any:
        assert path == "/v1/plugin-templates" and params == {"kind": "document_type"}
        self.asked.append((tenant, team))
        return list(self.listed) if team in self.on else []


def wire(svc: Service, listed: list[dict[str, Any]], **kw: Any) -> Tools:
    tools = Tools(listed, **kw)
    svc.app.state.plugin_templates = PluginTemplates(tools)  # type: ignore[arg-type]
    return tools


def data(r: httpx.Response, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


def code(r: httpx.Response, status: int) -> str:
    assert r.status_code == status, r.text
    return str(r.json()["error"]["code"])


async def install(
    svc: Service, body: dict[str, Any] | None = None, *, tid: str = "case-letter", headers: dict[str, str] = OPS
) -> httpx.Response:
    return await svc.client.post(f"/v1/resources/{SOURCE}:{tid}/copies", json=body or {}, headers=headers)


async def listed(svc: Service, headers: dict[str, str] = OPS) -> list[dict[str, Any]]:
    return list(data(await svc.client.get("/v1/templates", params={"kind": "document_type"}, headers=headers)))


async def types_of(svc: Service, headers: dict[str, str] = OPS) -> list[str]:
    return [t["name"] for t in data(await svc.client.get("/v1/document-types", headers=headers))["items"]]


async def test_the_list_shows_the_teams_templates_and_which_it_holds(make: Make) -> None:
    svc = make()
    tools = wire(svc, [LETTER])
    [before] = await listed(svc)
    assert before["id"] == "case-letter" and before["plugin"]["title"] == "Case desk" and before["version"] == 1
    assert before["installed"] == {"copies": 0, "version": None, "newerAvailable": False, "changed": False}
    data(await install(svc), 201)
    [after] = await listed(svc)
    assert after["installed"] == {"copies": 1, "version": 1, "newerAvailable": False, "changed": False}
    # The plugin changed the body at the same version: the copy was made from the old one.
    wire(svc, [LETTER | {"digest": "b" * 64}])
    [changed] = await listed(svc)
    assert changed["installed"]["changed"] is True, changed["installed"]
    # A newer version shipped by the plugin is offered, and the copy stays as it is.
    wire(svc, [LETTER | {"version": 2}])
    [newer] = await listed(svc)
    assert newer["installed"] == {"copies": 1, "version": 1, "newerAvailable": True, "changed": False}
    # Every read named the caller's tenant and team, so tools-service answered that team's view.
    assert tools.asked and set(tools.asked) == {(svc.tenant, ON)}


async def test_an_installed_type_reads_like_one_a_person_made(make: Make) -> None:
    svc = make()
    wire(svc, [LETTER])
    made = data(await install(svc, {"name": "Ops case letter"}), 201)
    assert made["created"] is True and made["needs"] == []
    copy = made["copy"]
    assert (copy["kind"], copy["source"], copy["templateId"], copy["version"]) == (
        "document_type",
        SOURCE,
        "case-letter",
        1,
    )
    assert copy["recordId"] != "case_letter"
    copied = data(await svc.client.get(f"/v1/document-types/{copy['recordId']}", headers=OPS))
    person = data(
        await svc.client.post(
            "/v1/document-types", json={k: v for k, v in LETTER["body"].items() if k != "id"}, headers=OPS
        ),
        201,
    )
    assert copied["name"] == "Ops case letter" and copied["team"] == ON and copied["latestVersion"] == 1
    # The copy is ready to read: version 1 holds the template's fields exactly as a person's create of the same body.
    [v1] = copied["versions"]
    [mine] = person["versions"]
    assert [f["key"] for f in v1["fields"]] == ["case_number", "letter_date"]
    assert v1["fields"] == mine["fields"]


async def test_the_same_version_again_answers_the_copy_and_a_type_gone_lets_a_new_one_in(
    make: Make, engine: AsyncEngine
) -> None:
    svc = make()
    wire(svc, [LETTER])
    first = data(await install(svc), 201)["copy"]
    again = data(await install(svc), 200)
    assert again["created"] is False and again["copy"] == first
    assert await types_of(svc) == ["Case letter"]
    # documents-service has no route that deletes a type; the copy's type is removed underneath, as a later delete
    # or purge would, and the template is installable again.
    async with engine.begin() as c:
        for table, key in ((document_type_versions, "type_id"), (document_types, "id")):
            await c.execute(sa.delete(table).where(table.c.tenant_id == svc.tenant, table.c[key] == first["recordId"]))
    fresh = data(await install(svc), 201)["copy"]
    assert fresh["recordId"] != first["recordId"] and fresh["id"] != first["id"]
    [row] = await listed(svc)
    assert row["installed"]["copies"] == 1


async def test_a_template_not_listed_or_a_version_not_shipped_makes_nothing(make: Make) -> None:
    svc = make()
    wire(svc, [LETTER])
    # The plugin is off for this team, so its templates are not listed for it.
    assert code(await install(svc, headers=PLATFORM), 404) == "template_not_found"
    assert code(await install(svc, tid="no-such-template"), 404) == "template_not_found"
    assert code(await install(svc, {"version": 2}), 404) == "template_version_not_found"
    assert await types_of(svc) == [] and await types_of(svc, PLATFORM) == []
    assert await listed(svc, PLATFORM) == []


async def test_another_team_never_sees_the_copy_and_installs_its_own(make: Make) -> None:
    svc = make()
    wire(svc, [LETTER])
    mine = data(await install(svc), 201)["copy"]
    [theirs] = await listed(svc, CLAIMS)
    assert theirs["installed"] == {"copies": 0, "version": None, "newerAvailable": False, "changed": False}
    seen = await svc.client.get(f"/v1/document-types/{mine['recordId']}", headers=CLAIMS)
    assert seen.status_code == 404, seen.text
    assert await types_of(svc, CLAIMS) == []
    # The body's id is not the copy's, so the second team's install makes its own type rather than colliding.
    other = data(await install(svc, headers=CLAIMS), 201)["copy"]
    assert other["recordId"] != mine["recordId"] and await types_of(svc, CLAIMS) == ["Case letter"]


async def test_a_role_that_cannot_edit_types_or_no_tools_address_makes_nothing(make: Make) -> None:
    # A chat-only member holds no documents cell, so it can make no type, as on create, and nothing is written.
    chatter = make(role="chat_user")
    wire(chatter, [LETTER])
    assert (await install(chatter)).status_code == 403
    assert await types_of(make()) == []
    unwired = make()
    assert code(await unwired.client.get("/v1/templates", headers=OPS), 503) == "unavailable"
    assert code(await install(unwired), 503) == "unavailable"
