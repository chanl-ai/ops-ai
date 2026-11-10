"""What search matches apart from what it cites, by failure mode: a child that matches but cites only itself, a piece
matched twice and returned twice, one long document filling every passage, and mapped metadata that never reaches its
pieces."""

from __future__ import annotations

from typing import Any

import httpx

from .pdfs import policy_pdf
from .test_bases_and_sources import data
from .test_sync import file_source, upload

MANUAL = policy_pdf(
    "Escrow handbook",
    [
        (
            "Escrow shortages",
            "An escrow analysis runs every year. "
            + " ".join(
                f"Paragraph {n} explains how escrow balances are projected for taxes and insurance." for n in range(40)
            )
            + " A shortage below one hundred dollars is collected with the next monthly payment.",
        ),
        ("Late fees", "A late fee of four percent applies when a payment is more than fifteen days past due."),
        ("Payoff quotes", "A payoff quote is valid for thirty days and includes interest to the payoff date."),
        ("Insurance", "Hazard insurance must name the servicer as mortgagee and cover the replacement cost."),
    ],
)


async def base_with(client: httpx.AsyncClient, settings: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    src = await file_source(client)
    data(await client.patch(f"/v1/sources/{src['id']}", json=settings))
    kb = data(
        await client.post(
            "/v1/knowledge-bases",
            json={"name": "Servicing", "owner": "james@harborpine.example", "sourceIds": [src["id"]]},
        ),
        201,
    )
    await upload(client, src["id"], "escrow.pdf", MANUAL)
    run = data(await client.post(f"/v1/sources/{src['id']}/sync"))
    assert run["counts"]["upserted"] == 1, run
    return src, kb


async def search(client: httpx.AsyncClient, kb_id: str, question: str, limit: int = 8) -> list[dict[str, Any]]:
    body = {"kbIds": [kb_id], "question": question, "limit": limit}
    return data(await client.post("/v1/knowledge-bases/search", json=body))["passages"]


async def test_a_matching_child_returns_and_cites_its_whole_parent_piece_once(client: httpx.AsyncClient) -> None:
    settings = {
        "ingest": {"strategies": ["structure", "context_headers", "parent_child"], "size": 1200, "childSize": 100}
    }
    _, kb = await base_with(client, settings)
    found = await search(client, kb["id"], "shortage below one hundred dollars collected monthly payment")
    shortage = [p for p in found if "one hundred dollars" in p["text"]]
    assert len(shortage) == 1, found
    assert "escrow analysis runs every year" in shortage[0]["text"], "the parent piece is cited, not the child"


async def test_one_document_gives_at_most_two_pieces(client: httpx.AsyncClient) -> None:
    _, kb = await base_with(client, {"ingest": {"strategies": ["fixed"], "size": 100, "overlap": 0}})
    found = await search(client, kb["id"], "escrow balances projected taxes insurance")
    assert 1 <= len(found) <= 2 and len({p["itemId"] for p in found}) == 1, found


async def test_mapped_metadata_reaches_every_piece_and_units_show_what_is_searched(client: httpx.AsyncClient) -> None:
    settings = {"metadataMapping": [{"key": "product", "from": "static:mortgage"}]}
    src, _ = await base_with(client, settings)
    [item] = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]
    pieces = data(await client.get(f"/v1/items/{item['id']}"))["detail"]["chunks"]
    assert pieces and all(p["metadata"].get("product") == "mortgage" for p in pieces), pieces
    assert all(p["metadata"]["department"] == "Lending" for p in pieces)
    assert all([u["kind"] for u in p["units"]] == ["self"] for p in pieces)
    assert all(p["units"][0]["text"].startswith("Escrow handbook") for p in pieces), "context header is searched"
