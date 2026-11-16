"""Today's replies of the gateway call route, tool modules, tools, apps and accounts, secrets and executions, pinned key
by key before the store and request layers move under them: every value, null against a missing key, the datetime
format, the error object and the status. Generated ids, the test's tenant, datetimes and timings are replaced by a
token naming their form, so a pin fails on a changed shape or value and never on a fresh id.

The pins are in fixtures/reply_pins.json; `OPS_WRITE_PINS=1` rewrites them from the code under test, which is done only
where a reply is meant to change, and that change is listed with the commit."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from .conftest import Api, Bank, service_headers
from .fake_upstream import ENDPOINT, HOST

PINS = Path(__file__).parent / "fixtures" / "reply_pins.json"
LENDING = {"X-Team-Id": "team_lending"}
WRITE = os.environ.get("OPS_WRITE_PINS") == "1"

_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_ID = re.compile(r"\b([a-z][a-z0-9]*)_[0-9a-f]{12}\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_HEX = re.compile(r"\b[0-9a-f]{32,64}\b")
# Measured, not decided: a timing differs on every run.
_TIMINGS = {"latencyMs", "latency_ms", "p95Ms", "durationMs", "elapsedMs"}


def _text(value: str, tenant: str) -> str:
    out = value.replace(tenant, "<tenant>")
    out = _DATETIME.sub("<datetime>", out)
    out = _DATE.sub("<date>", out)
    out = _UUID.sub("<uuid>", out)
    out = _ID.sub(lambda m: f"<id:{m.group(1)}>", out)
    return _HEX.sub("<hex>", out)


def normal(value: Any, tenant: str) -> Any:
    if isinstance(value, dict):
        fields = cast(dict[str, Any], value)
        return {
            k: ("<timing>" if k in _TIMINGS and isinstance(v, int | float) else normal(v, tenant))
            for k, v in sorted(fields.items())
        }
    if isinstance(value, list):
        return [normal(v, tenant) for v in cast(list[Any], value)]
    if isinstance(value, str):
        return _text(value, tenant)
    return value


class Pins:
    def __init__(self, group: str, tenant: str) -> None:
        self.group, self.tenant = group, tenant
        self.seen: dict[str, Any] = {}

    def reply(self, name: str, r: httpx.Response, sent: dict[str, Any] | None = None) -> Any:
        body = r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else r.text
        self.seen[name] = {
            "status": r.status_code,
            **({"sent": sorted(sent)} if sent is not None else {}),
            "body": normal(body, self.tenant),
        }
        return body

    def check(self) -> None:
        pinned: dict[str, Any] = json.loads(PINS.read_text()) if PINS.exists() else {}
        if WRITE:
            pinned[self.group] = self.seen
            PINS.write_text(json.dumps(pinned, indent=1, sort_keys=True) + "\n")
            return
        assert self.group in pinned, f"no pins for {self.group}: run once with OPS_WRITE_PINS=1 on today's code"
        for name, want in pinned[self.group].items():
            assert name in self.seen, f"{self.group}/{name} was not replied"
            assert self.seen[name] == want, f"{self.group}/{name} changed"
        assert sorted(self.seen) == sorted(pinned[self.group]), f"{self.group}: replies added or gone"


async def _bank_tool(bank_api: Api) -> None:
    await bank_api.client.post("/v1/egress/hosts", json={"value": HOST})
    op: dict[str, Any] = {"name": "get_account", "description": "", "access": "read", "group": "accounts", "input": []}
    source = {"kind": "openapi", "specUrl": f"{ENDPOINT}/openapi.json"}
    r = await bank_api.call(
        "POST", "/mod_document_service/operations/import", json={"source": source, "operations": [op]}
    )
    assert r.status_code == 200, r.text


async def test_gateway_call_and_executions_replies(bank: Bank, gateway_call: Any) -> None:
    api = bank.api
    pins = Pins("gateway_and_executions", api.tenant)
    await _bank_tool(api)
    pins.reply("call refused for a missing secret", await gateway_call("get_account", {"accountId": "CHQ-1"}))
    body = {"name": "STATEMENTS_KEY", "value": "sk-statements-123", "teamId": "team_lending"}
    assert (await api.client.post("/v1/secrets", json=body)).status_code == 201
    pins.reply("call ok", await gateway_call("get_account", {"accountId": "CHQ-1"}))
    pins.reply("call unknown tool", await gateway_call("no_such_tool", {}))
    bad: dict[str, Any] = {"tool": "get_account", "input": {}}
    pins.reply(
        "call without its key",
        await api.client.post("/v1/calls", json=bad, headers=_service(api.tenant)),
        sent=bad,
    )
    listed = pins.reply("executions list", await api.client.get("/v1/executions", params={"tool": "get_account"}))
    first = listed["data"]["data"][0]["id"]
    pins.reply("execution one", await api.client.get(f"/v1/executions/{first}"))
    pins.reply("execution missing", await api.client.get("/v1/executions/gwc_nobody"))
    pins.check()


async def test_secret_replies(bank: Bank) -> None:
    api = bank.api
    pins = Pins("secrets", api.tenant)
    body = {"name": "LEDGER_KEY", "value": "sk-ledger-1", "teamId": "team_lending"}
    pins.reply("create", await api.client.post(headers=LENDING, url="/v1/secrets", json=body), sent=body)
    pins.reply("create again", await api.client.post(headers=LENDING, url="/v1/secrets", json=body), sent=body)
    pins.reply("list", await api.client.get(headers=LENDING, url="/v1/secrets"))
    rotate = {"value": "sk-ledger-2"}
    pins.reply(
        "rotate", await api.client.post(headers=LENDING, url="/v1/secrets/LEDGER_KEY/rotate", json=rotate), sent=rotate
    )
    rename = {"name": "LEDGER_API_KEY"}
    pins.reply(
        "rename", await api.client.post(headers=LENDING, url="/v1/secrets/LEDGER_KEY/rename", json=rename), sent=rename
    )
    pins.reply("rotate missing", await api.client.post(headers=LENDING, url="/v1/secrets/NO_SUCH/rotate", json=rotate))
    pins.reply("delete", await api.client.delete(headers=LENDING, url="/v1/secrets/LEDGER_API_KEY"))
    pins.reply("delete missing", await api.client.delete(headers=LENDING, url="/v1/secrets/LEDGER_API_KEY"))
    pins.check()


async def test_tool_module_and_tool_replies(bank: Bank) -> None:
    api = bank.api
    pins = Pins("tool_modules", api.tenant)
    pins.reply("list", await api.call("GET", "", params={"page": 1, "pageSize": 3}))
    pins.reply("one", await api.call("GET", "/mod_document_service"))
    pins.reply("missing", await api.call("GET", "/mod_nobody"))
    pins.reply("grants", await api.call("GET", "/grants", headers=_service(api.tenant)))
    pins.reply("activity", await api.call("GET", "/mod_document_service/activity"))
    pins.reply("tool", await api.client.get("/v1/tools/lookup_case", headers=_service(api.tenant)))
    pins.reply("tool missing", await api.client.get("/v1/tools/no_such_tool", headers=_service(api.tenant)))
    pins.check()


async def test_app_and_account_replies(bank: Bank) -> None:
    api = bank.api
    pins = Pins("apps_and_accounts", api.tenant)
    pins.reply("list", await api.client.get("/v1/apps"))
    body = {"name": "Ledger", "authKind": "api_key"}
    made = pins.reply("create", await api.client.post("/v1/apps", json=body), sent=body)
    app = made["data"]["id"]
    pins.reply("create same name", await api.client.post("/v1/apps", json=body), sent=body)
    pins.reply("one", await api.client.get(f"/v1/apps/{app}"))
    pins.reply("missing", await api.client.get("/v1/apps/app_nobody"))
    pins.reply("accounts", await api.client.get(f"/v1/apps/{app}/accounts"))
    pins.reply("my connections", await api.client.get("/v1/me/connections"))
    pins.reply("delete", await api.client.delete(f"/v1/apps/{app}"))
    pins.check()


def _service(tenant: str) -> dict[str, str]:
    return service_headers(tenant)


@pytest.fixture(autouse=True)
def _pins_file_exists_or_written() -> None:
    assert WRITE or PINS.exists(), "fixtures/reply_pins.json is missing: write it with OPS_WRITE_PINS=1"
