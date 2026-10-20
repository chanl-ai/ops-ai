"""`extract_records` on the fixture levy notice (c-057 T002), through the fake OpenAI in process: the records come
from the scripted rule, and without that rule the structured call fails instead of inventing persons."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx2
import pdfplumber
import pytest
from openai import AsyncOpenAI
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from ops_agents.graphs.metering import MeteredModels
from ops_agents.graphs.models import PydanticAiModels

ROOT = Path(__file__).resolve().parents[4]
FIXTURES = ROOT / "services" / "agents-service" / "tests" / "fixtures" / "mailbox"
# The committed fake-OpenAI rules: the levy rules and the banker demo's, one set.
RULES = ROOT / "services" / "models-service" / "seed" / "demo-fake-openai"
V1_RULE = "NOTICE OF GARNISHMENT|judgment debtor"
FAKE_OPENAI = ROOT / "services" / "models-service" / "scripts" / "fake_openai" / "app.py"


def fake_openai() -> ModuleType:
    """The fake's app module, loaded from models-service's scripts: it is a script folder, not a package."""
    spec = importlib.util.spec_from_file_location("fake_openai_app", FAKE_OPENAI)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve their module through sys.modules; a module loaded from a path is not there by itself.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def models(rules_folder: Path | None) -> PydanticAiModels:
    fake = fake_openai()
    script = fake.load_script(rules_folder) if rules_folder else fake.Script([], ["default"])
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=fake.create_app(script)))
    client = AsyncOpenAI(base_url="http://fake/v1", api_key="fake", max_retries=0, http_client=http)
    return PydanticAiModels(OpenAIChatModel("default", provider=OpenAIProvider(openai_client=client)))


def notice_text() -> str:
    with pdfplumber.open(io.BytesIO((FIXTURES / "levy_notice.pdf").read_bytes())) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


async def test_the_rule_yields_one_record_per_person_with_every_field() -> None:
    records = await MeteredModels(models(RULES), None, "default").extract_records("persons", notice_text())
    rules: list[dict[str, Any]] = json.loads((RULES / "script.json").read_text())["rules"]
    # The v1 rule, by its pattern: the v2 Extract from file rule for the same notice sits ahead of it.
    scripted = next(r for r in rules if r["when"] == V1_RULE)["arguments"]["records"]
    assert records == scripted
    assert [r["name"] for r in records] == ["Marcus Bell", "Priya Natarajan", "Jordan Whitfield"]
    assert all(set(r) == {"name", "address", "ssn_last4", "amount", "court", "case_no"} for r in records)
    # The scripted answer is the notice's: every value the rule returns is in the PDF's text layer.
    text = notice_text()
    assert all(value in text for r in records for value in r.values())


async def test_without_the_rule_the_call_fails_instead_of_inventing_records() -> None:
    with pytest.raises(UnexpectedModelBehavior):
        await models(None).extract_records("persons", notice_text())


async def test_an_unknown_schema_is_refused_before_any_call() -> None:
    with pytest.raises(ValueError, match="persons"):
        await models(None).extract_records("invoices", "anything")
