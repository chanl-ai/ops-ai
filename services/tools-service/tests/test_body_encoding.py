"""How an operation's body is sent (c-591), by failure mode: a form-encoded write sent as JSON (Stripe takes forms
only), a raw body sent with a Content-Type other than its own, a credential coming back form-encoded through a system
that echoes it, and a save that keeps a body its encoding cannot send."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, quote_plus

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.modules.seed import blank
from ops_tools.store.egress import EgressStore
from ops_tools.store.modules import ModuleStore

from .conftest import Bank, service_headers
from .fake_upstream import ENDPOINT, HOST
from .test_calls import on_its_connection

MODULE = "mod_body_encoding"
VALUE = "sk_test 7f+3c&9e"


async def _module(engine: AsyncEngine, tenant: str) -> None:
    await EgressStore(engine).add(tenant, "host", HOST, actor="test", note="", at=datetime.now(UTC))
    m = blank(
        module_id=MODULE,
        tenant_id=tenant,
        team_id="team_ops",
        owner="Operations",
        me="James Richardson",
        at=datetime.now(UTC),
        input={"displayName": "Body encoding", "name": "body-encoding", "type": "http"},
    )

    def op(n: int, name: str, encoding: str, body: str, headers: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "id": f"{MODULE}_op{n}", "tool_id": f"tl_{name}", "name": name, "description": name, "access": "write",
            "enabled": True, "executor": "http", "method": "POST", "path": "/echo-body", "body": body,
            "body_encoding": encoding, "headers": [{"key": "Authorization", "value": "Bearer {{BANK_KEY}}"}, *headers],
            "input": [{"name": "email", "type": "string", "required": True}], "masked_output": [], "binding": None,
            "rate_limit_per_min": 60, "requires_approval": False, "amount_max": None, "stub": {},
        }  # fmt: skip

    m.update(
        status="published",
        egress_hosts=[HOST],
        operations=[
            op(1, f"form_{tenant}", "form", '{"email": "{{email}}", "metadata[source]": "ops_ai"}', []),
            op(
                2,
                f"raw_{tenant}",
                "raw",
                "<customer><email>{{email}}</email></customer>",
                [
                    {"key": "Content-Type", "value": "application/xml"},
                ],
            ),
        ],
    )
    m = await on_its_connection(engine, m, ENDPOINT)
    await ModuleStore(engine).put(m, expected_revision=None)


@pytest.fixture
async def encoded(bank: Bank, engine: AsyncEngine) -> Bank:
    await _module(engine, bank.api.tenant)
    await bank.api.client.post("/v1/secrets", json={"name": "BANK_KEY", "value": VALUE})
    return bank


async def _call(bank: Bank, tool: str, args: dict[str, Any], key: str) -> Any:
    body = {"tool": tool, "input": args, "key": key, "runContext": {"act": "workflow:dispute_email"}}
    return await bank.api.client.post("/v1/calls", json=body, headers=service_headers(bank.api.tenant))


async def test_a_form_operation_sends_its_fields_form_encoded_and_hides_its_key_echoed_back(encoded: Bank) -> None:
    email = "a+b@example.com&x=1"
    res = await _call(encoded, f"form_{encoded.api.tenant}", {"email": email}, "f1")
    assert res.status_code == 200, res.text
    sent = encoded.received[-1]
    assert sent["headers"]["content-type"] == "application/x-www-form-urlencoded"
    assert parse_qs(sent["body"].decode()) == {"email": [email], "metadata[source]": ["ops_ai"]}
    assert VALUE not in res.text and quote_plus(VALUE) not in res.text, res.text


async def test_a_raw_operation_sends_its_text_with_its_own_content_type(encoded: Bank) -> None:
    res = await _call(encoded, f"raw_{encoded.api.tenant}", {"email": "jo@example.com"}, "r1")
    assert res.status_code == 200, res.text
    sent = encoded.received[-1]
    assert sent["headers"]["content-type"] == "application/xml"
    assert sent["body"].decode() == "<customer><email>jo@example.com</email></customer>"


@pytest.mark.parametrize(
    ("patch", "says"),
    [
        (
            {"bodyEncoding": "form", "headers": [{"key": "Content-Type", "value": "application/json"}]},
            "Remove the header",
        ),
        ({"bodyEncoding": "raw", "headers": []}, "add the Content-Type header"),
        ({"bodyEncoding": "form", "body": '{"email": 1}', "headers": []}, "a set of fields"),
    ],
)
async def test_a_save_refuses_a_body_its_encoding_cannot_send(encoded: Bank, patch: dict[str, Any], says: str) -> None:
    res = await encoded.api.call("PATCH", f"/{MODULE}/operations/{MODULE}_op2", json=patch)
    assert res.status_code == 400 and says in res.text, res.text


async def test_a_save_lists_every_problem_at_once_and_sends_the_key_to_the_connection(encoded: Bank) -> None:
    """c-591 T003: the dogfood found each problem only after fixing the one before it."""
    patch = {
        "bodyEncoding": "form",
        "headers": [
            {"key": "Authorization", "value": "Bearer sk_live_51abc"},
            {"key": "Content-Type", "value": "application/json"},
        ],
        "timeoutMs": 5,
    }
    res = await encoded.api.call("PATCH", f"/{MODULE}/operations/{MODULE}_op1", json=patch)
    assert res.status_code == 400, res.text
    problems = res.json()["error"]["details"]["problems"]
    assert len(problems) == 3, problems
    assert "on the connection" in problems[0] and "Remove the header" in problems[1] and "timeout" in problems[2]


async def test_request_sent_shows_the_content_type_its_encoding_set(encoded: Bank) -> None:
    """The tool page's Request sent is what the system got: httpx adds a form's Content-Type on the wire, so the record
    of the request names it too (c-591)."""
    run = {
        "operation": f"form_{encoded.api.tenant}",
        "contextId": "owner",
        "target": "sandbox",
        "input": {"email": "a@b.c"},
    }
    out = (await encoded.api.call("POST", f"/{MODULE}/test", json=run)).json()["data"]
    headers = {h["key"].lower(): h["value"] for h in out["request"]["headers"]}
    assert headers.get("content-type") == "application/x-www-form-urlencoded", out["request"]
    assert encoded.received[-1]["headers"]["content-type"] == headers["content-type"], "the same type went on the wire"
