"""The OpenAPI check fails on each thing it guards: an untyped route off the allowlist, a typed route still on it,
a repeated or missing operationId, and a document that drifted from openapi.json."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_openapi  # pyright: ignore[reportMissingImports]


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    return check_openapi.document()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


def test_the_committed_document_passes(doc: dict[str, Any]) -> None:
    assert check_openapi.problems(doc) == []  # pyright: ignore[reportUnknownMemberType]


def test_each_guarded_change_is_a_finding(doc: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Every operation is typed, so the allowlist case uses a stand-in list naming a typed operation.
    allow = tmp_path / "openapi-untyped.txt"
    allow.write_text("# 1 untyped operations\nagents_get_agent\n")
    monkeypatch.setattr(check_openapi, "ALLOWLIST", allow)
    d = copy.deepcopy(doc)
    agents = d["paths"]["/v1/agents"]["get"]
    agents["responses"]["200"]["content"]["application/json"]["schema"] = {}
    d["paths"]["/v1/workflows"]["get"]["operationId"] = "agents_list_agents"
    del d["paths"]["/v1/tools"]["get"]["operationId"]
    found = "\n".join(check_openapi.problems(d))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    assert "agents_list_agents: success response has no schema" in found
    assert "operationId agents_list_agents repeats" in found
    assert "GET /v1/tools: no operationId" in found
    assert "agents_get_agent: on the allowlist but typed now" in found
    assert "openapi.json differs" in found
