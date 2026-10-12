"""Editing an operation's HTTP call after it is added (c-027), through the real routes and the real executor against
the in-process fake bank: one test per way it can break."""

from __future__ import annotations

import resource
import sys
import time
from typing import Any

import httpx
import pytest

from .test_calls import MODULE, Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]

SECURITY = {"X-Dev-User": "Nadia Petrov"}
BASE = f"/v1/tool-modules/{MODULE}"


async def _op_id(g: Gateway, base: str) -> str:
    detail = (await g.client.get(BASE)).json()["data"]
    return next(o["id"] for o in detail["operations"] if o["name"] == g.tool(base))


async def _patch(g: Gateway, base: str, body: dict[str, Any]) -> httpx.Response:
    return await g.client.patch(f"{BASE}/operations/{await _op_id(g, base)}", json=body)


async def _publish(g: Gateway) -> dict[str, Any]:
    """Publishes what is staged; a major version is approved by Security so the module serves again."""
    r = await g.client.post(f"{BASE}/versions", json={"note": "c-027"})
    assert r.status_code == 200, r.text
    detail = r.json()["data"]
    review = next((x for x in detail["reviews"] if x["decision"] == "pending"), None)
    if review is not None:
        decided = f"{BASE}/reviews/{review['id']}/decide"
        r = await g.client.post(decided, json={"decision": "approved"}, headers=SECURITY)
        assert r.status_code == 200, r.text
        detail = r.json()["data"]
    return detail


@pytest.fixture
async def g(gateway: Gateway) -> Gateway:  # noqa: F811
    """The published bank module and the fake bank (test_calls.gateway), under a short name."""
    return gateway


def _doubling(start: str, op: str) -> str:
    """A value doubled 30 times in a loop: about a billion items, past every per-operator size check."""
    loop = f"{{% for i in range(30) %}}{{% set ns.s = ns.s {op} ns.s %}}{{% endfor %}}"
    return f"{{% set ns = namespace(s={start}) %}}{loop}{{{{ ns.s | length }}}}"


def _out(r: httpx.Response) -> Any:
    assert r.status_code == 200, r.text
    return r.json()["data"]["output"]


async def test_an_edited_header_with_a_literal_credential_is_refused_and_nothing_is_staged(g: Gateway) -> None:
    r = await _patch(g, "get_account", {"headers": [{"key": "Authorization", "value": "Bearer sk_live_abc123"}]})
    assert r.status_code == 400 and "literal value" in r.json()["error"]["message"]
    assert (await g.client.get(BASE)).json()["data"]["pendingChanges"] == []
    kept = await _patch(g, "get_account", {"headers": [{"key": "Authorization", "value": "{{BANK_TOKEN}}"}]})
    assert kept.status_code == 200, "a vault reference is kept"


async def test_a_url_off_the_module_endpoint_is_refused_on_add_and_on_edit(g: Gateway) -> None:
    op = {
        "name": f"other_{g.suffix}",
        "description": "",
        "access": "read",
        "method": "GET",
        "url": "https://other.test/x",
    }
    added = await g.client.post(f"{BASE}/operations", json=op)
    assert added.status_code == 400 and "not this module's endpoint" in added.json()["error"]["message"]
    edited = await _patch(g, "get_account", {"path": "https://other.test/x"})
    assert edited.status_code == 400
    plain = await g.client.post(f"{BASE}/operations", json={**op, "url": "http://bank.test/v1/x"})
    assert plain.status_code == 400 and "https" in plain.json()["error"]["message"]


async def test_method_path_and_body_are_major_and_headers_transform_and_timeout_minor(g: Gateway) -> None:
    minor = {"headers": [{"key": "X-Trace", "value": "ops"}], "responseTransform": "{{ data }}", "timeoutMs": 4000}
    assert (await _patch(g, "get_account", minor)).status_code == 200
    staged = (await g.client.get(BASE)).json()["data"]["pendingChanges"]
    assert [c["major"] for c in staged] == [False]
    assert (await _publish(g))["version"] == "1.1.0"
    assert (await _patch(g, "get_account", {"path": "/accounts/{accountId}/summary"})).status_code == 200
    [change] = (await g.client.get(BASE)).json()["data"]["pendingChanges"]
    assert change["major"] is True and change["kind"] == "schema_changed"
    r = await g.client.post(f"{BASE}/versions", json={"note": "c-027"})
    detail = r.json()["data"]
    assert detail["version"] == "2.0.0" and any(x["decision"] == "pending" for x in detail["reviews"]), "a review opens"


async def test_a_pending_edit_reaches_calls_only_once_published(g: Gateway) -> None:
    assert (await _patch(g, "get_account", {"path": "/limited"})).status_code == 200
    pending = await g.call("get_account", {"accountId": "CHQ-2219"}, step="s1")
    assert _out(pending)["accountId"] == "CHQ-2219", "the published call ran, not the staged one"
    await _publish(g)
    published = await g.call("get_account", {"accountId": "CHQ-2219"}, step="s2")
    assert _out(published)["error"]["code"] == "RATE_LIMITED", "after publish the edited path is called"
    assert [x["path"] for x in g.received] == ["/v1/accounts/CHQ-2219", "/v1/limited"]


async def test_a_transform_shapes_the_answer_and_an_invalid_one_is_refused_at_save(g: Gateway) -> None:
    bad = await _patch(g, "get_account", {"responseTransform": "{{ data.accountId "})
    assert bad.status_code == 400 and "does not parse" in bad.json()["error"]["message"]
    template = '{"id": "{{ data.accountId }}", "balance": {{ data.balance }}, "sin": "{{ data.holder.sin }}"}'
    assert (await _patch(g, "get_account", {"responseTransform": template})).status_code == 200
    await _publish(g)
    out = _out(await g.call("get_account", {"accountId": "CHQ-2219"}, step="s1"))
    assert out == {"id": "CHQ-2219", "balance": 1200.5, "sin": "[redacted]"}, "rendered over the masked response"


async def test_a_transform_that_fails_returns_the_masked_answer_with_the_error(g: Gateway) -> None:
    for template in ("{{ data.missing.field }}", "{{ data.__class__.__mro__ }}", "{{ cycler.__init__.__globals__ }}"):
        assert (await _patch(g, "get_account", {"responseTransform": template})).status_code == 200
        await _publish(g)
        r = await g.call("get_account", {"accountId": "CHQ-2219"}, step=f"s-{len(template)}")
        out = _out(r)
        assert r.json()["data"]["ok"] is True and out["transform_error"].startswith("The response transform failed")
        assert out["response"]["accountId"] == "CHQ-2219" and out["response"]["holder"]["sin"] == "[redacted]"
        assert "__globals__" not in str(out["response"]) and "object" not in out["transform_error"].split(":")[0]


async def test_a_transform_cannot_carry_a_secret_out(g: Gateway) -> None:
    secret = "sk-bank-1f2e3d4c5b6a"
    created = await g.client.post("/v1/secrets", json={"name": f"BANK_KEY_{g.suffix.upper()}", "value": secret})
    assert created.status_code == 201, created.text
    shape = {
        "path": "/echo-headers",
        "headers": [{"key": "X-Api-Key", "value": f"{{{{BANK_KEY_{g.suffix.upper()}}}}}"}],
        "responseTransform": '{"key": "{{ data.headers["x-api-key"] }}"}',
    }
    assert (await _patch(g, "elsewhere", shape)).status_code == 200
    await _publish(g)
    r = await g.call("elsewhere", {"accountId": "CHQ-2219"}, step="s1")
    assert g.received[-1]["headers"]["x-api-key"] == secret, "the key went to the bank"
    assert secret not in r.text and _out(r) == {"key": "[secret]"}


async def test_the_timeout_is_per_operation_bounded_and_logged(g: Gateway) -> None:
    for ms, status in ((999, 400), (120_001, 400), (1_000, 200), (120_000, 200)):
        r = await _patch(g, "limited", {"timeoutMs": ms})
        assert r.status_code == status, (ms, r.text)
    assert (await _patch(g, "limited", {"path": "/slow", "timeoutMs": 1_000})).status_code == 200
    await _publish(g)
    out = _out(await g.call("limited", {}, step="s1"))
    assert out["error"]["code"] == "UPSTREAM_TIMEOUT" and "1000 ms" in out["error"]["message"]
    rows = (await g.client.get("/v1/executions", params={"tool": g.tool("limited")})).json()["data"]["data"]
    assert rows[0]["status"] == "error"
    assert (await _patch(g, "limited", {"timeoutMs": None})).status_code == 200
    await _publish(g)
    slow_ok = _out(await g.call("limited", {}, step="s2"))
    assert slow_ok == {"slow": True}, "unset, the module's timeout applies again"


async def test_an_mcp_or_stub_operation_has_no_call_to_edit(g: Gateway) -> None:
    detail = (await g.client.get("/v1/tool-modules/mod_core_banking")).json()
    stub = next(o for o in detail["data"]["operations"] if o["executor"] != "http")
    r = await g.client.patch(f"/v1/tool-modules/mod_core_banking/operations/{stub['id']}", json={"path": "/x"})
    assert r.status_code == 400 and "not an HTTP operation" in r.json()["error"]["message"]


async def test_a_transform_cannot_re_encode_a_secret(g: Gateway) -> None:
    secret = "sk-bank-9a8b7c6d5e4f"
    name = f"ECHO_KEY_{g.suffix.upper()}"
    assert (await g.client.post("/v1/secrets", json={"name": name, "value": secret})).status_code == 201
    shape = {"path": "/echo-headers", "headers": [{"key": "X-Api-Key", "value": f"{{{{{name}}}}}"}]}
    assert (await _patch(g, "elsewhere", shape)).status_code == 200
    await _publish(g)
    encodings = (
        '{{ data.headers["x-api-key"] | reverse }}',
        '{{ data.headers["x-api-key"] | list | join(" ") }}',
        '{{ data[data.headers["x-api-key"] | reverse] }}',
    )
    for n, template in enumerate(encodings):
        assert (await _patch(g, "elsewhere", {"responseTransform": template})).status_code == 200
        await _publish(g)
        r = await g.call("elsewhere", {"accountId": "CHQ-2219"}, step=f"enc{n}")
        assert g.received[-1]["headers"]["x-api-key"] == secret
        for leaked in (secret, secret[::-1], " ".join(secret)):
            assert leaked not in r.text, (template, r.text[:300])


async def test_a_runaway_transform_is_stopped(g: Gateway) -> None:
    cases = (
        ("{% for a in range(100000) %}{% for b in range(100000) %}{% endfor %}{% endfor %}", "range()"),
        ('{% set s = "x" | center(50000) %}{% for a in s %}{% for b in s %}{% endfor %}{% endfor %}', "ran past"),
        ('{{ "a" * 1000000 }}', "Repeating a value"),
        # One C-level call can take gigabytes before any deadline or output check runs: each is sized first.
        ('{{ "a" | center(300000000) }}', "past 100000 characters"),
        ('{{ "%300000000s" | format(1) }}', "past 100000 characters"),
        ('{{ "a"' + ' | replace("a", "aaaaaaaaaa")' * 7 + " }}", "past 100000 characters"),
        ('{{ "a".ljust(1000000000) }}', "past 100000 characters"),
        ('{{ "{:>300000000}".format(1) }}', "past 100000 characters"),
        ('{{ "%300000000s" % 1 }}', "past 100000 characters"),
        # Doubling in a loop passes every per-operator check; the render process's memory bound stops it.
        (_doubling('"a"', "~"), "out of memory"),
        (_doubling('"a"', "+"), "out of memory"),
        (_doubling("[1]", "+"), "out of memory"),
    )
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for n, (template, why) in enumerate(cases):
        assert (await _patch(g, "get_account", {"responseTransform": template})).status_code == 200
        await _publish(g)
        started = time.monotonic()
        out = _out(await g.call("get_account", {"accountId": "CHQ-2219"}, step=f"run{n}"))
        assert time.monotonic() - started < 4, template
        assert why in out["transform_error"] and out["response"]["accountId"] == "CHQ-2219", out["transform_error"]
    # ru_maxrss is bytes on macOS and KiB on Linux; either way none of the above may have built a ~300 MB string.
    grown = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - peak
    assert grown < (150_000_000 if sys.platform == "darwin" else 150_000), grown
