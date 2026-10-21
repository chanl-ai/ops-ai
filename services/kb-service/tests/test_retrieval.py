"""Questions over indexed knowledge (c-056 T004), by failure mode: the answering passage not ranked first or missing
its page and section, a question nothing answers returning a weak passage that shares a few of its words, a
never-indexed knowledge base answering as if empty, and agents-service's search reaching another tenant's knowledge
or a knowledge base that does not exist."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import dev_service_signer, mint_service_token
from ops_identity.testing import TEST_TOKEN_TTL_S

from .conftest import kb_client
from .pdfs import HARDSHIP, RATES
from .test_bases_and_sources import data
from .test_sync import file_source, upload


def agents(tenant: str, scopes: tuple[str, ...] = ("knowledge:view",)) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(),
        service="agents",
        audience="kb",
        tenant_id=tenant,
        ttl_s=TEST_TOKEN_TTL_S,
        scopes=list(scopes),
    )
    return {"Authorization": f"Bearer {token}"}


async def indexed_kb(client: httpx.AsyncClient) -> dict[str, Any]:
    src = await file_source(client)
    body = {"name": "Lending", "owner": "maya@harborpine.example", "sourceIds": [src["id"]]}
    kb = data(await client.post("/v1/knowledge-bases", json=body), 201)
    await upload(client, src["id"], "hardship.pdf", HARDSHIP)
    await upload(client, src["id"], "rates.pdf", RATES)
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    return kb


async def ask(client: httpx.AsyncClient, kb_id: str, question: str) -> dict[str, Any]:
    return data(await client.post(f"/v1/knowledge-bases/{kb_id}/query", json={"question": question}))


async def test_the_answering_passage_comes_first_with_page_and_section(client: httpx.AsyncClient) -> None:
    kb = await indexed_kb(client)
    answer = await ask(client, kb["id"], "How many mortgage payments can a borrower who lost their job defer?")
    top = answer["citations"][0]
    assert (top["title"], top["page"], top["version"]) == ("Mortgage Hardship Policy", 1, "v1"), answer["citations"]
    assert "Eligibility" in top["section"] and "three mortgage payments" in top["snippet"]
    scores = [c["score"] for c in answer["chunks"]]
    assert scores == sorted(scores, reverse=True) and not answer.get("noAnswer")


async def test_a_question_nothing_answers_returns_no_passage(client: httpx.AsyncClient) -> None:
    kb = await indexed_kb(client)
    answer = await ask(client, kb["id"], "What will the weather be in Lisbon tomorrow?")
    assert (answer["citations"], answer["noAnswer"]) == ([], True), answer
    weak = await ask(client, kb["id"], "Which mortgage brokers sell travel insurance?")
    assert weak["citations"] == [], "two of five terms shared with the rate sheet is not an answer"
    one = await ask(client, kb["id"], "mortgage")
    assert one["citations"] != [], "a one-word question is answered by a passage with that word"


async def test_a_knowledge_base_that_never_indexed_says_so(client: httpx.AsyncClient) -> None:
    kb = data(await client.post("/v1/knowledge-bases", json={"name": "Empty", "owner": "maya@x.com"}), 201)
    r = await client.post(f"/v1/knowledge-bases/{kb['id']}/query", json={"question": "fixed rate"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_indexed", r.text


async def test_agents_search_stays_in_the_tokens_tenant(client: httpx.AsyncClient, tenant: str) -> None:
    kb = await indexed_kb(client)
    question = {"kbIds": [kb["id"]], "question": "five-year fixed mortgage rate for insured borrowers"}
    found = data(await client.post("/v1/knowledge-bases/search", json=question, headers=agents(tenant)))
    top = found["passages"][0]
    assert (top["kbId"], top["title"], top["page"]) == (kb["id"], "Rate Sheet", 1), top
    other = await client.post("/v1/knowledge-bases/search", json=question, headers=agents("t_other"))
    assert other.status_code == 404, other.text
    unscoped = await client.post("/v1/knowledge-bases/search", json=question, headers=agents(tenant, ()))
    assert unscoped.status_code == 403 and unscoped.json()["error"]["code"] == "scope_required", unscoped.text


async def test_agents_list_the_tokens_tenants_knowledge_bases(client: httpx.AsyncClient, tenant: str) -> None:
    kb = data(await client.post("/v1/knowledge-bases", json={"name": "Cards", "owner": "maya@x.com"}), 201)
    refs = data(await client.get("/v1/knowledge-bases/refs", headers=agents(tenant)))
    assert refs == [{"id": kb["id"], "name": "Cards"}]
    assert data(await client.get("/v1/knowledge-bases/refs", headers=agents("t_other"))) == []


async def test_a_person_lists_and_searches_only_their_teams_bases_and_those_no_team_owns(
    client: httpx.AsyncClient,
) -> None:
    """Refs and search were for services only (c-222): a person may call them with knowledge.view, and reads their
    team's bases and the unowned ones, never another team's, which search refuses as unknown."""
    ops, fraud = {"X-Team-Id": "team_ops"}, {"X-Team-Id": "team_fraud"}
    mine = data(await client.post("/v1/knowledge-bases", json={"name": "Ops", "owner": "a@x.com"}, headers=ops), 201)
    theirs = data(
        await client.post("/v1/knowledge-bases", json={"name": "Fraud", "owner": "b@x.com"}, headers=fraud), 201
    )
    refs = data(await client.get("/v1/knowledge-bases/refs", headers=ops))
    assert mine["id"] in [r["id"] for r in refs] and theirs["id"] not in [r["id"] for r in refs], refs
    ask_mine = {"kbIds": [mine["id"]], "question": "fixed rate"}
    ask_theirs = {"kbIds": [theirs["id"]], "question": "fixed rate"}
    assert (await client.post("/v1/knowledge-bases/search", json=ask_mine, headers=ops)).status_code == 200
    refused = await client.post("/v1/knowledge-bases/search", json=ask_theirs, headers=ops)
    assert refused.status_code == 404, refused.text


async def test_an_agent_citing_a_retired_base_still_answers_from_its_others(
    engine: AsyncEngine, client: httpx.AsyncClient, tenant: str
) -> None:
    """c-094 T007: a deleted base was an unknown id, so every search naming it was refused and the agent lost all its
    knowledge. A retired base is skipped; an id kb-service never had is still refused, as is another tenant's."""
    gone = await indexed_kb(client)
    shared = [x["sourceId"] for x in data(await client.get(f"/v1/knowledge-bases/{gone['id']}"))["sources"]]
    body = {"name": "Rates desk", "owner": "maya@harborpine.example", "sourceIds": shared}
    kept = data(await client.post("/v1/knowledge-bases", json=body), 201)
    async with kb_client(engine, tenant, email="maya@harborpine.example") as maya:
        assert (await maya.delete(f"/v1/knowledge-bases/{gone['id']}")).status_code == 204
    assert (await client.get(f"/v1/knowledge-bases/{gone['id']}")).status_code == 404
    question = {"kbIds": [gone["id"], kept["id"]], "question": "five-year fixed mortgage rate for insured borrowers"}
    found = data(await client.post("/v1/knowledge-bases/search", json=question, headers=agents(tenant)))
    assert found["passages"] and {p["kbId"] for p in found["passages"]} == {kept["id"]}, found
    only_gone = {**question, "kbIds": [gone["id"]]}
    assert (
        data(await client.post("/v1/knowledge-bases/search", json=only_gone, headers=agents(tenant)))["passages"] == []
    )
    never = {**question, "kbIds": ["kb_never_made", kept["id"]]}
    assert (await client.post("/v1/knowledge-bases/search", json=never, headers=agents(tenant))).status_code == 404
    other = await client.post("/v1/knowledge-bases/search", json=only_gone, headers=agents("t_other"))
    assert other.status_code == 404, other.text
