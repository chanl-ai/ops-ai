"""What the console's Files page reads from files-service (c-126), by failure mode: a view or its count computed over
one page instead of in the query; search and the uploaded-since date ignored; a held file missing its hold on the list
row; the sheet's delete reason disagreeing with the 409; bulk delete removing a referenced or held file; upload limits
the upload component cannot read."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import sqlalchemy as sa

from ops_files.store import AsyncEngine
from ops_files.store.files import files as files_table
from ops_identity import dev_service_signer, mint_service_token

from .test_api import (  # pyright: ignore[reportPrivateUsage]
    OPS,
    PDF,
    Client,
    _data,  # pyright: ignore[reportPrivateUsage]
    _upload,  # pyright: ignore[reportPrivateUsage]
    client,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)


async def _stored(c: httpx.AsyncClient, name: str, body: bytes = PDF) -> str:
    ticket = await _upload(c, body, name=name)
    return _data(await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))["file"]["id"]


async def _reference(c: httpx.AsyncClient, tenant: str, file_id: str) -> None:
    token = mint_service_token(
        dev_service_signer(),
        service="kb",
        audience="files",
        tenant_id=tenant,
        scopes=["files:edit"],
        team_id="team_ops",
    )
    attach = {"type": "chat", "refId": f"msg_{file_id}", "name": "Chat message"}
    r = await c.post(f"/v1/files/{file_id}/references", json=attach, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text


def _list(c: httpx.AsyncClient, **params: Any) -> Any:
    return c.get("/v1/files", params={"page": 1, "pageSize": 2, **params}, headers=OPS)


async def test_views_counts_search_and_date_run_in_the_query(
    client: Client,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    async with client(admin=True) as c:
        ids = [await _stored(c, f"statement-{i}.pdf", PDF + bytes([i])) for i in range(4)]
        await _reference(c, tenant, ids[0])
        hold = {"ids": [ids[1]], "hold": True, "reason": "Litigation 2026-114"}
        assert _data(await c.post("/v1/files/legal-hold", json=hold, headers=OPS))["updated"] == [ids[1]]
        # Two files are old enough to count as unreferenced: one is used, so only the other is.
        old = datetime.now(UTC) - timedelta(days=40)
        async with engine.begin() as conn:
            await conn.execute(sa.update(files_table).where(files_table.c.id.in_(ids[:3:2])).values(uploaded_at=old))

        page = _data(await _list(c))
        assert len(page["data"]) == 2 and page["pagination"]["total"] == 4, "a page of two, the total of four"
        counts = page["viewCounts"]
        assert (counts["all"], counts["legal_hold"], counts["unreferenced"]) == (4, 1, 1), counts
        assert page["facets"]["purpose"] == {"chat_attachment": 4}

        held = _data(await _list(c, view="legal_hold"))
        assert [f["id"] for f in held["data"]] == [ids[1]] and held["data"][0]["legalHold"]["reason"] == hold["reason"]
        unused = _data(await _list(c, view="unreferenced"))
        assert [f["id"] for f in unused["data"]] == [ids[2]]

        found = _data(await _list(c, search="statement-3"))
        assert [f["id"] for f in found["data"]] == [ids[3]] and found["viewCounts"]["all"] == 1
        recent = _data(await _list(c, uploadedAfter=(datetime.now(UTC) - timedelta(days=1)).isoformat()))
        assert sorted(f["id"] for f in recent["data"]) == sorted([ids[1], ids[3]])
        older = _data(await _list(c, uploadedBefore=(datetime.now(UTC) - timedelta(days=1)).isoformat()))
        assert sorted(f["id"] for f in older["data"]) == sorted([ids[0], ids[2]])


async def test_the_delete_reason_matches_the_409_and_bulk_delete_skips_with_it(
    client: Client,  # noqa: F811
    tenant: str,
) -> None:
    async with client(admin=True) as c:
        used, held, free = [await _stored(c, f"f{i}.pdf", PDF + bytes([i])) for i in range(3)]
        await _reference(c, tenant, used)
        await c.post("/v1/files/legal-hold", json={"ids": [held], "hold": True, "reason": "Audit"}, headers=OPS)

        reason = _data(await c.get(f"/v1/files/{used}", headers=OPS))["deleteBlockedBy"]
        assert reason and "Used by 1 record" in reason
        assert (await c.delete(f"/v1/files/{used}", headers=OPS)).status_code == 409
        assert _data(await c.get(f"/v1/files/{free}", headers=OPS))["deleteBlockedBy"] is None

        result = _data(await c.post("/v1/files/bulk-delete", json={"ids": [used, held, free]}, headers=OPS))
        assert result["updated"] == [free]
        skipped = {s["id"]: s["reason"] for s in result["skipped"]}
        assert "Used by 1 record" in skipped[used] and "legal hold" in skipped[held]
        assert (await c.get(f"/v1/files/{used}", headers=OPS)).status_code == 200, "a referenced file stays"


async def test_upload_limits_are_readable(client: Client) -> None:  # noqa: F811
    async with client() as c:
        limits = _data(await c.get("/v1/files/limits", headers=OPS))
        assert set(limits) == {"perPurpose", "scanning"} and limits["scanning"] is False


async def test_wildcards_in_the_search_match_only_themselves(client: Client) -> None:  # noqa: F811
    async with client() as c:
        for i, n in enumerate(("rate 100%.pdf", "rate 1000.pdf", "a_b.pdf", "axb.pdf")):
            await _stored(c, n, PDF + bytes([40 + i]))
        for term, want in (("100%", ["rate 100%.pdf"]), ("a_b", ["a_b.pdf"])):
            got = _data(await _list(c, search=term))
            assert [f["name"] for f in got["data"]] == want, term
