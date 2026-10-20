"""scripts/reimport_bank_module.py against tools-service in process, with the scripts' fake bank as the upstream
(c-057 T003): a module imported before the levy operations existed gains them, the hold's policy becomes one approver
from the operations team with no self-approval, and running it again changes nothing."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.contract import response_checker
from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore

from .conftest import Api, build_app, opa_client, service_headers

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
HOST = "api.bank.test"
SOURCE = {"kind": "openapi", "specUrl": f"https://{HOST}/openapi.json"}


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def gw(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Api]:
    """tools-service whose outbound https goes to the scripts' fake bank in process, as the dev stack's does over
    OPS_EGRESS_RESOLVE."""
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    bank = load_script("fake_bank_app", SCRIPTS / "fake_bank" / "app.py").app
    async with (
        opa_client() as opa,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=bank)) as upstream,
    ):
        app = build_app(engine, seed, tenant, opa=opa, upstream=upstream)
        hooks = {"response": [response_checker(app)]}
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks) as c,
        ):
            r = await c.post("/v1/egress/hosts", json={"value": HOST})
            assert r.status_code in (200, 201), r.text
            yield Api(c, tenant)


async def imported_before_levy(gw: Api) -> str:
    """The module as c-048 imported it: the document's operations before search_customers matched addresses and
    add_customer_note existed."""
    found = (await gw.call("POST", "/discover", json=SOURCE)).json()["data"]
    old = [o for o in found["operations"] if o["name"] not in ("search_customers", "add_customer_note")]
    assert old, found
    body = {
        "name": "northfield-core-banking",
        "displayName": "Northfield Core Banking",
        "system": found["system"],
        "type": "openapi",
        "endpoint": found["endpoint"],
        "operations": [{**o, "access": "read" if o["method"] == "GET" else "write"} for o in old],
        "source": SOURCE,
    }
    r = await gw.call("POST", "", json=body)
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


async def served(gw: Api) -> dict[str, dict[str, Any]]:
    """What the registry offers agents and the gateway runs: the test that a staged operation is not yet one."""
    r = await gw.client.get("/v1/grantable-operations", headers=service_headers(gw.tenant))
    assert r.status_code == 200, r.text
    return {o["name"]: o for o in r.json()["data"]}


class AsNadia:
    """Security's approver in Reviews (c-163): approving `/v1/publish-requests/{id}/decision` there is what tells
    tools-service, so here it applies the decision as agents-service would."""

    def __init__(self, gw: Api, module_id: str) -> None:
        self.gw, self.module_id = gw, module_id

    async def post(self, path: str, **kw: Any) -> httpx.Response:
        assert path.startswith("/v1/publish-requests/") and path.endswith("/decision"), path
        return await self.gw.decide(self.module_id)


async def published(gw: Api, module_id: str) -> None:
    """Security approves the first version, so the module serves its operations as the shared stack's did."""
    r = await gw.call("POST", f"/{module_id}/reviews", json={"note": "first version"})
    assert r.status_code == 200, r.text
    r = await gw.decide(module_id)
    assert r.status_code == 200, r.text


async def test_reimport_adds_the_levy_operations_and_sets_the_hold_policy(gw: Api) -> None:
    script = load_script("reimport_bank_module", SCRIPTS / "reimport_bank_module.py")
    module_id = await imported_before_levy(gw)
    await published(gw, module_id)
    assert "add_customer_note" not in await served(gw)
    before = (await gw.call("GET", f"/{module_id}")).json()["data"]
    assert "add_customer_note" not in {o["name"] for o in before["operations"]}
    # The hold's policy was loosened since the import: two approvers from another team, the asker among them.
    hold = next(o for o in before["operations"] if o["name"] == "place_hold")
    loosened = {"approvers": 2, "approverTeam": "team_retail"}
    r = await gw.call("PATCH", f"/{module_id}/operations/{hold['id']}", json=loosened)
    assert r.status_code == 200, r.text

    module = await script.reimport(gw.client, module_id, approver=AsNadia(gw, module_id))  # type: ignore[arg-type]
    names = {o["name"] for o in module["operations"]}
    assert {"search_customers", "add_customer_note", "place_hold", "get_customer", "get_account"} <= names
    # The point of the run: the registry now serves the new operations and the new hold policy.
    offered = await served(gw)
    assert {"add_customer_note", "list_accounts"} <= set(offered), sorted(offered)
    assert offered["place_hold"]["approvers"] == 1 and offered["place_hold"]["stepUp"] is True
    current = next(v for v in module["versions"] if v["version"] == module["version"])
    assert module["version"] == "2.0.0" and current["status"] == "published"
    assert not module.get("pendingChanges") and script.pending_review(module) is None
    ops = {o["name"]: o for o in module["operations"]}
    assert (ops["search_customers"]["access"], ops["add_customer_note"]["access"]) == ("read", "write")
    assert (ops["place_hold"]["approvers"], ops["place_hold"]["approverTeam"]) == (1, "team_ops")
    assert ops["place_hold"]["requiresApproval"] is True and ops["place_hold"]["stepUp"] is True
    # The stored row carries the policy the gateway and the review service read.
    stored = (await gw.call("GET", f"/{module_id}")).json()["data"]
    assert next(o for o in stored["operations"] if o["name"] == "place_hold")["approverTeam"] == "team_ops"

    again = await script.reimport(gw.client, module_id, approver=AsNadia(gw, module_id))  # type: ignore[arg-type]
    assert again["updatedAt"] == module["updatedAt"], "a second run changed the module"


async def test_an_empty_module_gets_the_whole_document_and_the_policy(gw: Api) -> None:
    script = load_script("reimport_bank_module", SCRIPTS / "reimport_bank_module.py")
    r = await gw.call("POST", "/blank", json={"displayName": "Empty", "name": "empty", "type": "http"})
    assert r.status_code == 201, r.text
    new_id = r.json()["data"]["id"]
    module = await script.reimport(gw.client, new_id, approver=AsNadia(gw, new_id))  # type: ignore[arg-type]
    ops = {o["name"]: o for o in module["operations"]}
    assert {"search_customers", "add_customer_note", "place_hold"} <= set(ops)
    assert ops["place_hold"]["approverTeam"] == "team_ops"


async def test_a_clean_stack_gets_the_module_created_reviewed_and_served(gw: Api) -> None:
    """A fresh tenant has no module calling the bank: the run imports one from the bank's document, sends it through
    Security's review, and the registry serves it; a second run finds it and changes nothing."""
    script = load_script("reimport_bank_module", SCRIPTS / "reimport_bank_module.py")
    module_id, created = await script.ensure_module(gw.client, HOST)
    assert created
    module = await script.reimport(gw.client, module_id, approver=AsNadia(gw, module_id))  # type: ignore[arg-type]
    offered = await served(gw)
    assert {"get_customer", "list_accounts", "search_customers", "place_hold"} <= set(offered), sorted(offered)
    assert offered["place_hold"]["approvers"] == 1 and offered["place_hold"]["stepUp"] is True
    again_id, again_created = await script.ensure_module(gw.client, HOST)
    assert (again_id, again_created) == (module_id, False)
    again = await script.reimport(gw.client, module_id, approver=AsNadia(gw, module_id))  # type: ignore[arg-type]
    assert again["updatedAt"] == module["updatedAt"], "a second run changed the module"


async def test_find_module_reads_the_list_envelope(gw: Api) -> None:
    script = load_script("reimport_bank_module", SCRIPTS / "reimport_bank_module.py")
    module_id = await imported_before_levy(gw)
    assert await script.find_module(gw.client, HOST) == module_id
    with pytest.raises(SystemExit, match="0 modules"):
        await script.find_module(gw.client, "nobody.bank.test")


async def test_a_version_left_waiting_for_security_is_decided_first(gw: Api) -> None:
    script = load_script("reimport_bank_module", SCRIPTS / "reimport_bank_module.py")
    module_id = await imported_before_levy(gw)
    r = await gw.call("POST", f"/{module_id}/reviews", json={"note": "an earlier run stopped here"})
    assert r.status_code == 200, r.text
    with pytest.raises(SystemExit, match="waiting for Security"):
        await script.reimport(gw.client, module_id)
    module = await script.reimport(gw.client, module_id, approver=AsNadia(gw, module_id))  # type: ignore[arg-type]
    assert "add_customer_note" in await served(gw)
    assert script.pending_review(module) is None


async def test_the_bank_key_secret_is_created_once(gw: Api) -> None:
    script = load_script("reimport_bank_module", SCRIPTS / "reimport_bank_module.py")
    assert await script.ensure_secret(gw.client, "BANK_API_KEY", "dev-bank-key") == "created"
    assert await script.ensure_secret(gw.client, "BANK_API_KEY", "other") == "exists"


async def test_an_operation_imported_with_old_wording_takes_the_documents(gw: Api) -> None:
    # customer_summary on shared, 2026-10-18: get_customer said only "One customer and their account ids", so a model
    # with a name invented ids; the document now says the id comes from search_customers, and a module imported before
    # that keeps the old text unless the reimport copies it.
    script = load_script("reimport_bank_module", SCRIPTS / "reimport_bank_module.py")
    module_id = await imported_before_levy(gw)
    look = next(
        o for o in (await gw.call("GET", f"/{module_id}")).json()["data"]["operations"] if o["name"] == "get_customer"
    )
    old = {
        "description": "One customer and their account ids",
        "input": [{"name": "customer_id", "type": "string", "required": True}],
    }
    r = await gw.call("PATCH", f"/{module_id}/operations/{look['id']}", json=old)
    assert r.status_code == 200, r.text
    await published(gw, module_id)
    module = await script.reimport(gw.client, module_id, approver=AsNadia(gw, module_id))  # type: ignore[arg-type]
    got = next(o for o in module["operations"] if o["name"] == "get_customer")
    assert "search_customers" in got["description"], got
    assert "CUS-1002" in (got["input"][0].get("description") or ""), got["input"]
    assert served_desc(await served(gw), "get_customer") == got["description"]


def served_desc(ops: dict[str, dict[str, Any]], name: str) -> str:
    return str(ops[name].get("description") or "")
