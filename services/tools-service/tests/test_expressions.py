"""POST /v1/expressions/evaluate: a workflow's formulas (the Calculate step) evaluated in the transforms' sandbox.
One test per way it can go wrong: a number turned into text, a later formula blind to an earlier one, weekends
counted as working days, the sandbox reachable through an attribute, a missing name or a non-JSON result taken as a
value, and a service without the tools scope let in."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from ops_identity import Auth, dev_service_signer, install_auth, mint_service_token
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_service_kit.http import install_error_handlers
from ops_service_kit.settings import Settings
from ops_tools.expression_routes import expressions_router

PERSON = {"X-Dev-User": "m.okafor@harborpine.example"}
LEVY = {"levy": {"amount": 3250.0, "served": "2026-10-16"}, "balance": 1800}


def _service(scopes: list[str]) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(),
        service="agents",
        audience="tools",
        tenant_id="local",
        ttl_s=TEST_TOKEN_TTL_S,
        scopes=scopes,
        team_id="team_ops",
    )
    return {"Authorization": f"Bearer {token}"}


async def _evaluate(
    expressions: dict[str, str], values: dict[str, Any] | None = None, headers: dict[str, str] | None = None
) -> httpx.Response:
    # The route has no effects and needs no registry: the router alone, behind the gateway's own auth and errors.
    app = FastAPI()
    install_error_handlers(app)
    install_auth(app, Auth.from_settings(Settings(), audience="tools"))
    app.include_router(expressions_router())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c:
        body = {"expressions": expressions, "values": LEVY if values is None else values}
        return await c.post("/v1/expressions/evaluate", json=body, headers=headers or PERSON)


async def test_numbers_stay_numbers_and_a_later_formula_reads_an_earlier_one() -> None:
    r = await _evaluate({"amount": "min(levy.amount, balance)", "left": "levy.amount - amount"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["out"] == {"amount": 1800, "left": 1450.0}


async def test_business_days_skip_the_weekend() -> None:
    # 2026-10-16 is a Friday: one working day later is Monday the 19th, twenty is Friday 13 November.
    r = await _evaluate({"next": "business_days(levy.served, 1)", "deadline": "business_days(levy.served, 20)"})
    assert r.json()["data"]["out"] == {"next": "2026-10-19", "deadline": "2026-11-13"}


@pytest.mark.parametrize(
    ("formula", "why"),
    [
        ("levy.__class__", "SecurityError"),
        ("min.__self__", "SecurityError"),
        ("missing + 1", "UndefinedError"),
        ("levy.nothing", "UndefinedError"),
        ("range(3)", "not JSON"),
        ("balance / 0", "division by zero"),
        ("min(", "does not parse"),
    ],
)
async def test_a_bad_formula_is_refused_with_its_name_and_never_its_values(formula: str, why: str) -> None:
    r = await _evaluate({"amount": formula})
    assert r.status_code == 400, r.text
    message = r.json()["error"]["message"]
    assert message.startswith("amount:") and why in message
    assert "3250" not in message and "1800" not in message


async def test_a_service_without_the_tools_scope_is_refused() -> None:
    refused = await _evaluate({"amount": "balance"}, headers=_service([]))
    allowed = await _evaluate({"amount": "balance"}, headers=_service(["tools:view"]))
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "scope_required"
    assert allowed.status_code == 200 and allowed.json()["data"]["out"] == {"amount": 1800}
