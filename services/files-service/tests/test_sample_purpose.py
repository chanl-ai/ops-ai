"""Files a document type is tested against (c-379), by failure mode: a sample uploaded with the sample purpose
refused, so the seed has to call it an email attachment; and the files already stored that way never relabelled, or
a file a case or chat also uses relabelled as a sample; a sample's bytes mailed as an attachment still shown as a
sample, because dedupe kept the first purpose (c-380)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
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

MIGRATION = Path(__file__).parents[1] / "migrations" / "versions" / "0010_document_type_sample_purpose.py"
# The mailbox demo's levy notice, which is also a seeded levy sample: the same bytes arrive both ways.
LEVY = Path(__file__).parents[3] / "services" / "agents-service" / "tests" / "fixtures" / "mailbox" / "levy_notice.pdf"


def relabel() -> Any:
    spec = importlib.util.spec_from_file_location("files_0010", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RELABEL


async def _stored(c: httpx.AsyncClient, name: str, body: bytes) -> str:
    ticket = await _upload(c, body, name=name)
    return _data(await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))["file"]["id"]


async def _attach(c: httpx.AsyncClient, tenant: str, file_id: str, kind: str, service: str) -> None:
    token = mint_service_token(
        dev_service_signer(),
        service=service,
        audience="files",
        tenant_id=tenant,
        scopes=["files:edit"],
        team_id="team_ops",
    )
    body = {"type": kind, "refId": f"{kind}_{file_id}", "name": kind}
    r = await c.post(f"/v1/files/{file_id}/references", json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text


async def test_a_sample_is_uploaded_and_listed_with_the_sample_purpose(client: Client) -> None:  # noqa: F811
    async with client(admin=True) as c:
        meta = {"name": "levy.pdf", "size": len(PDF), "mime": "application/pdf", "purpose": "document_type_sample"}
        ticket = await c.post("/v1/files/uploads", json=meta, headers=OPS)
        assert ticket.status_code == 201, ticket.text
        upload = _data(ticket)
        await c.put(upload["uploadUrl"], content=PDF, headers={**OPS, **upload["headers"]})
        done = _data(await c.post(f"/v1/files/uploads/{upload['fileId']}/complete", headers=OPS))["file"]
        listed = _data(await c.get("/v1/files", params={"purpose": "document_type_sample"}, headers=OPS))
    assert done["purpose"] == "document_type_sample"
    assert [f["id"] for f in listed["data"]] == [done["id"]]


async def test_stored_attachments_kept_only_as_samples_take_the_sample_purpose(
    client: Client,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    async with client(admin=True) as c:
        sample = await _stored(c, "sample.pdf", PDF + b"1")
        shared = await _stored(c, "shared.pdf", PDF + b"2")
        loose = await _stored(c, "loose.pdf", PDF + b"3")
        await _attach(c, tenant, sample, "test_set", "documents")
        await _attach(c, tenant, shared, "test_set", "documents")
        await _attach(c, tenant, shared, "chat", "kb")
    async with engine.begin() as conn:
        await conn.execute(relabel())
        rows = (await conn.execute(sa.select(files_table.c.id, files_table.c.purpose))).all()
    purposes = {r.id: r.purpose for r in rows}
    assert purposes[sample] == "document_type_sample"
    assert (purposes[shared], purposes[loose]) == ("chat_attachment", "chat_attachment"), purposes


async def _as(c: httpx.AsyncClient, body: bytes, purpose: str) -> dict[str, Any]:
    meta = {"name": "levy_notice.pdf", "size": len(body), "mime": "application/pdf", "purpose": purpose}
    ticket = _data(await c.post("/v1/files/uploads", json=meta, headers=OPS))
    await c.put(ticket["uploadUrl"], content=body, headers={**OPS, **ticket["headers"]})
    return _data(await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))


async def test_a_samples_bytes_mailed_as_an_attachment_show_as_the_attachment(client: Client) -> None:  # noqa: F811
    levy = LEVY.read_bytes()
    async with client(admin=True) as c:
        await _as(c, levy, "document_type_sample")
        mailed = await _as(c, levy, "case_attachment")
        other = PDF + b"attachment first"
        await _as(c, other, "case_attachment")
        seeded = await _as(c, other, "document_type_sample")
    assert mailed["deduplicated"] and mailed["file"]["purpose"] == "case_attachment", mailed["file"]["purpose"]
    assert seeded["deduplicated"] and seeded["file"]["purpose"] == "case_attachment", "an attachment stays one"
