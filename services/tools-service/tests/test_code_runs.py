"""Code runs' calls back (c-531): the call token is this service's own and holds only for its purpose and its time, and
a secret handle becomes a value only for a bound secret handed to a read over http as a query value."""

from __future__ import annotations

from typing import Any

import pytest

from ops_policy import HmacSigner, mint
from ops_service_kit.errors import Unauthorized, Unprocessable
from ops_tools.code_runs import CodeExecutor, code_signer, resolve_handles, run_claims
from ops_tools.registry import Resolved
from ops_tools.tools import ToolCaller

SIGNER = code_signer("test-secrets-key")
CALLER = ToolCaller(tenant_id="t1", team_id="team_a", sub="ana@example.test", kind="person")
CODE: dict[str, Any] = {
    "source": "def main(i):\n    return i",
    "bindings": ["get_account"],
    "secrets": ["BANK_KEY"],
    "limits": {},
}


def claims() -> dict[str, Any]:
    token = CodeExecutor(None, SIGNER).token({"name": "check_limit", "access": "read"}, CODE, CALLER, "k1", "test")
    return run_claims(token, SIGNER)


class Secrets:
    async def lookup(self, _tenant: str, names: list[str], **_: Any) -> dict[str, str]:
        return {n: f"value-of-{n}" for n in names}


def read(path: str = "/accounts", method: str = "GET", access: str = "read", executor: str = "http") -> Resolved:
    return Resolved(access, executor, None, {"name": "get_account", "path": path, "method": method, "body": None})


def test_the_token_names_the_caller_and_what_the_function_may_use() -> None:
    c = claims()
    assert (c["tenant_id"], c["team_id"], c["sub"]) == ("t1", "team_a", "ana@example.test")
    assert c["bindings"] == ["get_account"] and c["secrets"] == ["BANK_KEY"]


def test_a_token_from_another_key_or_purpose_is_refused() -> None:
    forged = CodeExecutor(None, code_signer("another-key")).token(
        {"name": "x", "access": "read"}, CODE, CALLER, "k", None
    )
    with pytest.raises(Unauthorized):
        run_claims(forged, SIGNER)
    approval_like = mint({"purpose": "approval", "tenant_id": "t1"}, SIGNER, ttl_s=60)
    with pytest.raises(Unauthorized):
        run_claims(approval_like, SIGNER)
    with pytest.raises(Unauthorized):
        run_claims(None, SIGNER)


def test_an_expired_token_is_refused() -> None:
    old = mint({"purpose": "code-run"}, HmacSigner.derived("test-secrets-key", "code-run"), ttl_s=1, now=1000)
    with pytest.raises(Unauthorized):
        run_claims(old, SIGNER)


async def test_a_bound_secret_becomes_a_query_value_and_is_named_for_scrubbing() -> None:
    args, hide = await resolve_handles(claims(), read(), {"id": "A1", "apiKey": {"$secret": "BANK_KEY"}}, Secrets())  # pyright: ignore[reportArgumentType]
    assert args == {"id": "A1", "apiKey": "value-of-BANK_KEY"}
    assert hide == ["value-of-BANK_KEY"]


async def test_a_read_function_may_not_call_a_write() -> None:
    write = Resolved("write", "http", None, {"name": "place_hold", "path": "/holds", "method": "POST", "body": None})
    with pytest.raises(Unprocessable) as e:
        await resolve_handles(claims(), write, {"amount": 10}, Secrets())  # pyright: ignore[reportArgumentType]
    assert e.value.code == "write_from_read"


@pytest.mark.parametrize(
    ("resolved", "args", "code"),
    [
        (read(), {"apiKey": {"$secret": "OTHER_KEY"}}, "secret_not_bound"),
        (read(access="write", method="POST"), {"apiKey": {"$secret": "BANK_KEY"}}, "write_from_read"),
        (read(executor="mcp"), {"apiKey": {"$secret": "BANK_KEY"}}, "secret_placement"),
        (read(path="/accounts/{apiKey}"), {"apiKey": {"$secret": "BANK_KEY"}}, "secret_placement"),
        (read(), {"filter": {"key": {"$secret": "BANK_KEY"}}}, "secret_placement"),
    ],
    ids=["unbound", "write", "not-http", "in-path", "nested"],
)
async def test_a_handle_anywhere_else_is_refused(resolved: Resolved, args: dict[str, Any], code: str) -> None:
    with pytest.raises(Unprocessable) as e:
        await resolve_handles(claims(), resolved, args, Secrets())  # pyright: ignore[reportArgumentType]
    assert e.value.code == code
