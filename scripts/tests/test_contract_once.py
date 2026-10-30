"""The response contract is built once per app shape for a test session (c-566), by failure mode: a cached contract
checks a response against another app's document and lets a broken body through; a cache that never hits leaves every
test paying for a fresh document again; a test file builds its own contract per test, putting the cost back."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from ops_service_kit.contract import contract_for, response_checker

ROOT = Path(__file__).resolve().parents[2]


class Named(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class Counted(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    count: int


async def thing() -> dict[str, object]:
    return {"name": "n"}


def app_with(model: type[BaseModel]) -> FastAPI:
    app = FastAPI()
    app.add_api_route("/thing", thing, methods=["GET"], response_model=model)
    return app


def answered(body: object) -> httpx.Response:
    request = httpx.Request("GET", "http://t/thing")
    return httpx.Response(200, json=body, request=request)


def test_apps_of_one_shape_share_one_contract() -> None:
    assert contract_for(app_with(Named)) is contract_for(app_with(Named))


def test_a_body_that_breaks_its_own_apps_schema_fails_even_when_a_like_app_was_checked_first() -> None:
    # The same path, method and handler under another response model: the cached contract of the first must not
    # stand in for the second, or a body missing `count` would pass.
    asyncio.run(response_checker(app_with(Named))(answered({"name": "n"})))
    with pytest.raises(AssertionError, match="does not match its schema"):
        asyncio.run(response_checker(app_with(Counted))(answered({"name": "n"})))


def test_a_second_app_of_the_same_shape_still_fails_a_broken_body() -> None:
    asyncio.run(response_checker(app_with(Named))(answered({"name": "n"})))
    with pytest.raises(AssertionError, match="does not match its schema"):
        asyncio.run(response_checker(app_with(Named))(answered({"name": "n", "extra": 1})))


BUILDS_OWN = re.compile(r"\bContract\(")


def own_contracts(root: Path) -> list[str]:
    """Test files that build a contract themselves instead of through response_checker's session cache."""
    found: list[str] = []
    for path in sorted(root.glob("**/tests/**/*.py")):
        if path.name == "contract.py" or "/node_modules/" in str(path) or "/.venv/" in str(path):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if BUILDS_OWN.search(line):
                found.append(f"{path.relative_to(root)}:{n}")
    return found


def test_the_guard_finds_a_test_that_builds_its_own_contract(tmp_path: Path) -> None:
    planted = tmp_path / "services" / "x" / "tests" / "test_planted.py"
    planted.parent.mkdir(parents=True)
    planted.write_text("from ops_service_kit.contract import Contract\n\ncontract = Contract(app)\n", encoding="utf-8")
    assert own_contracts(tmp_path) == ["services/x/tests/test_planted.py:3"]


def test_no_test_builds_its_own_contract() -> None:
    assert own_contracts(ROOT / "services") + own_contracts(ROOT / "packages") == [], (
        "build the contract through ops_service_kit.contract.response_checker, which builds it once per app shape"
    )
