"""Likely questions written by a model for each piece, by failure mode: written before the knowledge owner approved
them, asked again for pieces whose text did not change, their spend not recorded on the run, a model that is down
failing the document, an estimate that calls the model, and questions that never reach search."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_ingest import ModelBudgetSpent, ModelUnavailable
from ops_kb.ai import AiClient, models_clients
from ops_kb.files import KnowledgeFiles

from .conftest import kb_client
from .pdfs import policy_pdf
from .readings_fake import LocalReadings
from .test_bases_and_sources import data
from .test_sync import file_source, upload

SECTIONS = [
    ("Wire cut-off", "Outgoing wires sent after four in the afternoon leave on the next business day."),
    ("Recall requests", "A recall of a sent wire is asked of the receiving bank and can take ten days."),
    ("International wires", "Wires abroad need the receiving bank's SWIFT code and the beneficiary address."),
]


class FakeAi:
    """One run's client: three questions per piece, naming its section; or refusing, as a down model does."""

    def __init__(self, log: list[str], down: bool, ceiling: float, cost: float) -> None:
        self.log, self.down = log, down
        self.calls = self.input_tokens = self.output_tokens = 0
        # The run's ceiling and what each call costs, as models-service records them: past the ceiling it refuses.
        self.ceiling, self.cost, self.spent = ceiling, cost, 0.0

    def complete(self, prompt: str, *, alias: str, max_tokens: int) -> str:
        if self.down:
            raise ModelUnavailable("provider_unavailable")
        if self.spent >= self.ceiling:
            raise ModelBudgetSpent("this sync reached its source's ceiling")
        self.spent += self.cost
        self.calls += 1
        self.input_tokens += 100
        self.output_tokens += 20
        section = re.search(r"Section: (.*)", prompt)
        name = section.group(1).split(" > ")[-1] if section else "this"
        self.log.append(name)
        return json.dumps({"questions": [f"zebracode {name} when?", f"Who asks about {name}?"]})


class Ai:
    def __init__(self) -> None:
        self.asked: list[str] = []
        self.down = False
        self.made: list[FakeAi] = []
        self.runs: list[tuple[str, float]] = []
        self.cost = 0.01

    def __call__(self, tenant: str, run_id: str, ceiling: float) -> AiClient:
        self.runs.append((run_id, ceiling))
        made = FakeAi(self.asked, self.down, ceiling, self.cost)
        self.made.append(made)
        return made


@pytest.fixture
def ai() -> Ai:
    return Ai()


@pytest.fixture
async def client(engine: AsyncEngine, tenant: str, tmp_path: Path, ai: Ai) -> AsyncIterator[httpx.AsyncClient]:
    files = KnowledgeFiles(tmp_path)
    async with kb_client(engine, tenant, files=files, readings=LocalReadings(files), ai_clients=ai) as c:
        yield c


async def questions_on(client: httpx.AsyncClient, src: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    data(await client.patch(f"/v1/sources/{src['id']}", json={"ingest": {"strategies": ["structure", "faq"]}}))
    kb = data(
        await client.post(
            "/v1/knowledge-bases",
            json={"name": "Wires", "owner": "james@harborpine.example", "sourceIds": [src["id"]]},
        ),
        201,
    )
    await upload(client, src["id"], "wires.pdf", policy_pdf("Wire handbook", SECTIONS))
    run = data(await client.post(f"/v1/sources/{src['id']}/sync"))
    return kb, run


async def test_no_question_is_written_until_the_owner_approves_and_the_run_records_the_spend(
    client: httpx.AsyncClient, ai: Ai
) -> None:
    src = await file_source(client)
    kb, unapproved = await questions_on(client, src)
    assert ai.asked == [] and "modelCalls" not in unapproved["counts"], unapproved
    estimate = data(await client.get(f"/v1/sources/{src['id']}/ai-estimate"))
    assert ai.asked == [], "an estimate calls no model"
    assert (estimate["steps"], estimate["sampledItems"], estimate["totalItems"]) == (["faq"], 1, 1), estimate
    assert estimate["calls"] == len(SECTIONS) and estimate["inputTokens"] > 0, estimate
    approved = data(await client.post(f"/v1/sources/{src['id']}/ai-approval", json={"decision": "approve"}))
    assert approved["rebuild"] is not None, approved
    rebuild = await finished(client, approved["rebuild"]["id"])
    assert sorted(ai.asked) == sorted(name for name, _ in SECTIONS), ai.asked
    assert rebuild["counts"]["modelCalls"] == 3 and rebuild["counts"]["inputTokens"] == 300, rebuild["counts"]
    found = data(
        await client.post(
            "/v1/knowledge-bases/search", json={"kbIds": [kb["id"]], "question": "zebracode recall requests when"}
        )
    )
    top = found["passages"][0]
    assert (top["matched"], top["section"].split(" > ")[-1]) == ("question", "Recall requests"), top


async def test_a_new_version_asks_only_for_the_piece_that_changed(client: httpx.AsyncClient, ai: Ai) -> None:
    src = await file_source(client)
    await questions_on(client, src)
    approved = data(await client.post(f"/v1/sources/{src['id']}/ai-approval", json={"decision": "approve"}))
    await finished(client, approved["rebuild"]["id"])
    ai.asked.clear()
    changed = [*SECTIONS[:2], ("International wires", "Wires abroad now also need the purpose of the payment.")]
    await upload(client, src["id"], "wires.pdf", policy_pdf("Wire handbook", changed))
    run = data(await client.post(f"/v1/sources/{src['id']}/sync"))
    assert ai.asked == ["International wires"] and run["counts"]["modelCalls"] == 1, (ai.asked, run["counts"])


async def test_a_down_model_indexes_the_document_without_questions_and_says_why(
    client: httpx.AsyncClient, ai: Ai
) -> None:
    src = await file_source(client)
    await questions_on(client, src)
    ai.down = True
    approved = data(await client.post(f"/v1/sources/{src['id']}/ai-approval", json={"decision": "approve"}))
    rebuild = await finished(client, approved["rebuild"]["id"])
    assert rebuild["status"] == "success" and rebuild["counts"]["rebuilt"] == 1, rebuild
    assert any("did not answer" in line for line in rebuild["log"]), rebuild["log"]
    revoked = data(await client.post(f"/v1/sources/{src['id']}/ai-approval", json={"decision": "revoke"}))
    assert revoked["ingest"]["approval"]["status"] == "pending", revoked["ingest"]


async def finished(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    for _ in range(200):
        run = data(await client.get(f"/v1/sync-runs/{run_id}"))
        if run["status"] != "running":
            return run
        await asyncio.sleep(0.02)
    raise AssertionError(f"run {run_id} did not finish")


async def test_a_run_stops_at_its_sources_ceiling_and_indexes_the_rest_without_questions(
    client: httpx.AsyncClient, ai: Ai
) -> None:
    """The ceiling was a count of calls kept in kb-service; the source's ceiling in money now travels with the run's
    own id to models-service, which refuses past it from what it recorded."""
    src = await file_source(client)
    data(await client.patch(f"/v1/sources/{src['id']}", json={"aiCeiling": 0.5}))
    await questions_on(client, src)
    ai.cost = 0.4
    approved = data(await client.post(f"/v1/sources/{src['id']}/ai-approval", json={"decision": "approve"}))
    rebuild = await finished(client, approved["rebuild"]["id"])
    assert ai.runs[-1][1] == 0.5 and ai.runs[-1][0].startswith("airun_"), ai.runs
    assert rebuild["status"] == "success" and rebuild["counts"]["rebuilt"] == 1, rebuild
    assert len(ai.asked) == 2, "two calls fit under 0.50 at 0.40 each; the third is refused"
    said = "spend ceiling: this sync reached its source's ceiling"
    assert any(said in line for line in rebuild["log"]), rebuild["log"]


def test_models_services_ceiling_refusals_stop_the_step_and_send_the_runs_ceiling() -> None:
    """A ceiling refusal read as the model being down would say the wrong thing; a call without the run's id and
    ceiling would never be refused at all."""
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(429, json={"success": False, "error": {"code": "run_spend_cap", "message": "spent"}})

    client = models_clients("http://models", "mk_dev_kb")("t1", "airun_1", 5.0)
    inner = cast(Any, client).inner
    inner.http = httpx.Client(transport=httpx.MockTransport(answer), base_url="http://models")
    with pytest.raises(ModelBudgetSpent, match="source's ceiling"):
        client.complete("Write questions", alias="default", max_tokens=10)
    assert (sent[0].headers["x-run-id"], sent[0].headers["x-run-spend-cap"]) == ("airun_1", "5.00")
