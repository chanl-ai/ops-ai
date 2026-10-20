"""The Egress and Secrets lists a page at a time, through the real routes. Failure modes: a page answering every row, a
total that ignores the search, a page that loads the whole table, and earlier callers of GET /v1/secrets getting a
page instead of the whole list."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ops_tools.store.egress import EgressStore
from ops_tools.store.secrets import SecretStore

from .test_egress_and_secrets_need_security_admin import client  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_review_decisions import person


def _data(r: httpx.Response) -> Any:
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]


async def test_hosts_and_secrets_page_on_the_server(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sam = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    for i in range(5):
        _data(await client.post("/v1/egress/hosts", json={"value": f"paging-{i}.example.com"}, headers=sam))
        _data(await client.post("/v1/secrets", json={"name": f"PAGING_{i}", "value": "x"}, headers=sam))

    whole = _data(await client.get("/v1/secrets", headers=sam))
    assert isinstance(whole, list), "without page, earlier callers still read the whole list"

    # A page reads only its own rows: the whole-table reads are never called.
    async def no_whole_table(*_: Any) -> Any:
        raise AssertionError("a page must not load every row")

    monkeypatch.setattr(EgressStore, "allow_list", no_whole_table)
    monkeypatch.setattr(SecretStore, "listed", no_whole_table)

    hosts = _data(
        await client.get("/v1/egress/hosts", params={"search": "paging-", "page": 2, "pageSize": 2}, headers=sam)
    )
    assert [h["host"] for h in hosts["data"]] == ["paging-2.example.com", "paging-3.example.com"]
    assert (hosts["pagination"]["total"], hosts["pagination"]["totalPages"]) == (5, 3)

    page = _data(await client.get("/v1/secrets", params={"search": "paging_", "page": 3, "pageSize": 2}, headers=sam))
    assert [s["name"] for s in page["data"]] == ["PAGING_4"] and page["pagination"]["total"] == 5


async def test_wildcards_in_the_search_match_only_themselves(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    sam = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    for n in ("A_B", "AXB"):
        _data(await client.post("/v1/secrets", json={"name": n, "value": "x"}, headers=sam))
    for host, note in (("wild-1.example.com", "rate 100%"), ("wild-2.example.com", "rate 1000")):
        _data(await client.post("/v1/egress/hosts", json={"value": host, "note": note}, headers=sam))
    secrets = _data(await client.get("/v1/secrets", params={"page": 1, "search": "a_b"}, headers=sam))
    assert [s["name"] for s in secrets["data"]] == ["A_B"]
    hosts = _data(await client.get("/v1/egress/hosts", params={"search": "100%"}, headers=sam))
    assert [h["host"] for h in hosts["data"]] == ["wild-1.example.com"]
