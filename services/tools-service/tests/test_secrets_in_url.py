"""Secrets in an operation's URL (c-070 T003), by failure mode: the path's own query dropped when arguments are sent
as the query, a reference resolved from a caller's argument instead of the operation's definition, a value that
breaks the URL it is put in, a resolved value coming back through an upstream that echoes its URL, a call sent
without its credential, and an OpenAPI API key `in: query` imported as an input the agent fills."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, quote, quote_plus

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.executor import build_request, scrubbed_values
from ops_tools.modules.openapi import discover
from ops_tools.modules.seed import blank
from ops_tools.secrets import scrub
from ops_tools.store.calls import gateway_calls
from ops_tools.store.egress import EgressStore
from ops_tools.store.modules import ModuleStore

from .conftest import Bank, service_headers
from .fake_upstream import ENDPOINT, HOST

# Characters that mean something in a URL, so a value put in unencoded would change the request.
VALUE = "sk/live+7f&3c=9e d"
MODULE = "mod_url_keyed"


def _field(name: str, kind: str = "string", *, required: bool = False) -> dict[str, Any]:
    return {"name": name, "type": kind, "required": required}


async def _module(engine: AsyncEngine, tenant: str) -> None:
    await EgressStore(engine).add(tenant, "host", HOST, actor="test", note="", at=datetime.now(UTC))
    m = blank(
        module_id=MODULE,
        tenant_id=tenant,
        # Operations, the team the dev caller acts in: the secrets these tests write as that caller are the module's.
        team_id="team_ops",
        owner="Operations",
        me="James Richardson",
        at=datetime.now(UTC),
        input={"displayName": "Url keyed", "name": "url-keyed", "type": "http"},
    )

    def op(n: int, name: str, path: str, fields: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "id": f"{MODULE}_op{n}", "tool_id": f"tl_{name}", "name": name, "description": name, "access": "read",
            "enabled": True, "executor": "http", "method": "GET", "path": path, "headers": [], "body": None,
            "input": fields, "masked_output": [], "binding": None, "rate_limit_per_min": 60,
            "requires_approval": False, "amount_max": None, "stub": {},
        }  # fmt: skip

    m.update(
        status="published",
        endpoint=ENDPOINT,
        egress_hosts=[HOST],
        operations=[
            op(
                1,
                f"query_{tenant}",
                "/echo-url/{account_id}?api_key={{BANK_KEY}}&format=json",
                [_field("account_id", required=True), _field("limit", "integer"), _field("api_key")],
            ),
            op(2, f"segment_{tenant}", "/echo-url/{{BANK_KEY}}", []),
            op(
                3,
                f"search_{tenant}",
                "/echo-url/search?email={email}&cursor={cursor}&api_key={{BANK_KEY}}",
                [_field("email", required=True), _field("cursor"), _field("limit", "integer")],
            ),
        ],
    )
    await ModuleStore(engine).put(m, expected_revision=None)


async def _call(bank: Bank, tool: str, args: dict[str, Any], key: str) -> Any:
    body = {"tool": tool, "input": args, "key": key, "runContext": {"act": "workflow:dispute_email"}}
    return await bank.api.client.post("/v1/calls", json=body, headers=service_headers(bank.api.tenant))


@pytest.fixture
async def keyed(bank: Bank, engine: AsyncEngine) -> Bank:
    await _module(engine, bank.api.tenant)
    return bank


async def test_a_query_secret_reaches_the_upstream_beside_the_arguments_and_never_comes_back(
    keyed: Bank, engine: AsyncEngine
) -> None:
    tenant = keyed.api.tenant
    await keyed.api.client.post("/v1/secrets", json={"name": "BANK_KEY", "value": VALUE})
    res = await _call(keyed, f"query_{tenant}", {"account_id": "CHQ 2219", "limit": 3}, "u1")
    assert res.status_code == 200, res.text
    sent = keyed.received[-1]
    assert sent["path"] == "/v1/echo-url/CHQ 2219"
    query = parse_qs(sent["query"])
    assert query["api_key"] == [VALUE], "the value arrives whole, encoded once"
    assert query["format"] == ["json"] and query["limit"] == ["3"], "the path's own query and the arguments both arrive"
    out = res.json()["data"]["output"]
    assert out["query"]["api_key"] == "[secret]" and "[secret]" in out["url"], "the upstream echoed it back"
    executions = await keyed.api.client.get("/v1/executions", params={"pageSize": 50})
    async with engine.connect() as c:
        rows = (await c.execute(gateway_calls.select().where(gateway_calls.c.tool == f"query_{tenant}"))).mappings()
        logged = json.dumps([dict(r) for r in rows], default=str)
    for text in (res.text, executions.text, logged):
        for form in (VALUE, quote(VALUE, safe=""), quote_plus(VALUE, safe="")):
            assert form not in text


async def test_a_secret_in_a_path_segment_is_encoded_and_scrubbed(keyed: Bank) -> None:
    # No slash, question mark or hash: the fake decodes the path before routing, so those would re-split it there;
    # the request itself is checked for them below.
    value = "sk live+7f&3c=9e"
    await keyed.api.client.post("/v1/secrets", json={"name": "BANK_KEY", "value": value})
    res = await _call(keyed, f"segment_{keyed.api.tenant}", {}, "u2")
    assert res.status_code == 200, res.text
    assert keyed.received[-1]["path"] == f"/v1/echo-url/{value}"
    assert res.json()["data"]["output"]["accountId"] == "[secret]", res.text


def test_a_path_secret_stays_one_segment_whatever_it_holds() -> None:
    op: dict[str, Any] = {"method": "GET", "path": "/accounts/{{BANK_KEY}}/statement", "headers": []}
    req = build_request({"endpoint": ENDPOINT}, op, {}, {"BANK_KEY": "a/b?c#d"})
    assert req.url == f"{ENDPOINT}/accounts/a%2Fb%3Fc%23d/statement"


async def test_a_query_placeholder_is_filled_from_its_argument_and_sent_once(keyed: Bank) -> None:
    # `?email={email}` was sent as the literal `%7Bemail%7D` (the dogfood's Stripe customer search).
    await keyed.api.client.post("/v1/secrets", json={"name": "BANK_KEY", "value": VALUE})
    email = "a+b@example.com&x=1"
    res = await _call(keyed, f"search_{keyed.api.tenant}", {"email": email, "limit": 2}, "u4")
    assert res.status_code == 200, res.text
    query = parse_qs(keyed.received[-1]["query"])
    assert query["email"] == [email], "the argument's value, encoded once, in place of {email}"
    assert query["api_key"] == [VALUE] and query["limit"] == ["2"], "the secret and the other arguments still arrive"
    assert "cursor" not in query, "a placeholder whose argument is not given is left out, not sent empty"


async def test_a_query_argument_cannot_name_a_secret(keyed: Bank) -> None:
    await keyed.api.client.post("/v1/secrets", json={"name": "BANK_KEY", "value": VALUE})
    await _call(keyed, f"search_{keyed.api.tenant}", {"email": "{{BANK_KEY}}"}, "u5")
    assert parse_qs(keyed.received[-1]["query"])["email"] == ["{{BANK_KEY}}"], "an argument is sent as written"


async def test_a_caller_cannot_replace_the_credential_or_name_a_secret(keyed: Bank) -> None:
    tenant = keyed.api.tenant
    await keyed.api.client.post("/v1/secrets", json={"name": "BANK_KEY", "value": VALUE})
    await _call(keyed, f"query_{tenant}", {"account_id": "{{BANK_KEY}}", "api_key": "mine"}, "u3")
    sent = keyed.received[-1]
    assert sent["path"] == "/v1/echo-url/{{BANK_KEY}}", "an argument is sent as written, never resolved"
    assert parse_qs(sent["query"])["api_key"] == [VALUE]


async def test_a_missing_url_secret_sends_nothing(keyed: Bank) -> None:
    res = await _call(keyed, f"query_{keyed.api.tenant}", {"account_id": "CHQ-2219"}, "u4")
    assert res.json()["data"]["output"]["error"]["code"] == "SECRET_MISSING"
    assert not [x for x in keyed.received if x["path"].startswith("/v1/echo-url")]


def test_an_openapi_query_api_key_is_a_url_secret_not_an_input() -> None:
    spec: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": "Rates", "version": "1"},
        "servers": [{"url": "https://api.bank.test"}],
        "components": {"securitySchemes": {"partnerKey": {"type": "apiKey", "in": "query", "name": "api_key"}}},
        "security": [{"partnerKey": []}],
        "paths": {
            "/rates/{currency}": {
                "get": {
                    "operationId": "getRate",
                    "parameters": [
                        {"name": "currency", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "api_key", "in": "query", "required": True, "schema": {"type": "string"}},
                    ],
                }
            }
        },
    }
    found = discover(spec, "https://api.bank.test/openapi.json")
    op = found["operations"][0]
    assert op["path"] == "/rates/{currency}?api_key={{PARTNER_KEY}}"
    assert [f["name"] for f in op["input"]] == ["currency"]
    assert op["headers"] == [] and found["noAuth"] is False


def test_a_value_echoed_with_lowercase_escapes_is_scrubbed() -> None:
    """Escapes are case-insensitive, and some servers write them lowercase when they repeat a URL (%2f for %2F)."""
    value = "sk/live+7f&3c=9e d"
    echoed = {
        "url": "https://api.bank.test/v1/x?api_key=sk%2flive%2b7f%263c%3d9e+d",
        "path": "/v1/sk%2flive%2b7f%263c%3d9e%20d",
    }
    out = scrub(echoed, scrubbed_values({"BANK_KEY": value}))
    assert out == {"url": "https://api.bank.test/v1/x?api_key=[secret]", "path": "/v1/[secret]"}
