"""Add source screens that said more than the service knew, by failure mode: every non-web source named with the Email
templates preset, and Add source offering a source the create then refuses."""

from __future__ import annotations

import httpx

from .test_bases_and_sources import data
from .test_tool_sources import FakeTools, kb, tools  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixtures


async def test_files_text_and_pushed_sources_do_not_start_as_email_templates(client: httpx.AsyncClient) -> None:
    kinds = {k["type"]: k for k in data(await client.get("/v1/knowledge/source-kinds"))}
    presets = {t: kinds[t]["defaults"]["ingest"]["preset"] for t in ("file", "text", "push")}
    assert presets == {"file": "documents", "text": "documents", "push": "documents"}, presets


async def test_add_source_offers_only_what_create_accepts_and_says_why_not(
    kb: httpx.AsyncClient,  # noqa: F811
    tools: FakeTools,  # noqa: F811
) -> None:
    kinds = (await kb.get("/v1/knowledge/source-kinds")).json()["data"]
    ok_kind = next(k for k in kinds if k.get("source") == "articles")
    assert ok_kind["canCreate"] is True and not ok_kind.get("cannotCreateBecause")
    tools.sign_in = "person"
    kinds = (await kb.get("/v1/knowledge/source-kinds")).json()["data"]
    blocked = next(k for k in kinds if k.get("source") == "articles")
    assert blocked["canCreate"] is False and "team sign-in" in blocked["cannotCreateBecause"], blocked
    refused = await kb.post(
        "/v1/sources",
        json={"type": "tool", "name": "Articles", "config": {"plugin": "opsai.salesforce", "source": "articles"}},
    )
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "sign_in_not_team", refused.text
