"""The tool module's mocks answer test runs in place of the registry, so a mock that drifts from the registry makes a
test run pass on answers the real system would never give. Each mock here is checked against the fake registry."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

PLUGIN = Path(__file__).resolve().parents[1]
MODULE = yaml.safe_load((PLUGIN / "contributions" / "tool-modules" / "vendor-registry" / "module.yaml").read_text())
HEADERS = {"X-Api-Key": "dev-registry-key"}


def _registry() -> TestClient:
    spec = importlib.util.spec_from_file_location("vendor_registry", PLUGIN / "fake_api" / "vendor_registry.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return TestClient(module.app)


def _cases() -> list[tuple[str, dict[str, Any]]]:
    return [(op, mock) for op, mocks in MODULE["mocks"].items() for mock in mocks]


@pytest.mark.parametrize(("operation", "mock"), _cases(), ids=lambda v: v if isinstance(v, str) else v["name"])
def test_each_mock_is_what_the_registry_answers(operation: str, mock: dict[str, Any]) -> None:
    registry = _registry()
    match = mock.get("match") or {}
    if operation == "lookup_company":
        number = match.get("registration_number") or mock["body"]["registrationNumber"]
        answer = registry.get(f"/v1/companies/{number}", headers=HEADERS)
    else:
        name = match.get("legal_name") or "Brightwater Logistics Ltd"
        answer = registry.post("/v1/screenings", json={"name": name, "country": "CA"}, headers=HEADERS)
    assert answer.status_code == 200
    assert answer.json() == mock["body"]
