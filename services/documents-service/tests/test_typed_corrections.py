"""Values a person typed into a read with no answer, saved in one call (POST .../corrections), by failure mode: the
original, the person or the type lost, or a retry doubling the history; and a person's token writing values under
someone else's name."""

from __future__ import annotations

from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.store.extractions import service_outbox
from ops_identity import dev_service_signer, mint_service_token

from .conftest import OPS, Make, tenant_outbox
from .test_document_types import TYPE, data
from .test_extractions import NOTICE, Floor
from .test_incomplete_replies import Replies, cut

MAYA = "maya@harborpine.example"
TYPED = [{"field": "invoice", "value": "NWF-88213"}, {"field": "amount", "value": "1,940.00"}]


def agents(tenant: str, *scopes: str) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(),
        service="agents",
        audience="documents",
        tenant_id=tenant,
        scopes=list(scopes),
        team_id="team_ops",
    )
    return {"Authorization": f"Bearer {token}"}


async def _not_read(c: httpx.AsyncClient, file_id: str) -> dict[str, Any]:
    data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
    body = {"fileId": file_id, "documentTypeId": "invoice_notice"}
    read = data(await c.post("/v1/documents/extractions", json=body, headers=OPS))
    assert read["outcome"] == "incomplete", read
    return read


async def test_typed_values_keep_the_original_the_person_and_the_type_and_a_repeat_adds_nothing(
    make: Make, engine: AsyncEngine
) -> None:
    s = make(Replies(cut(), cut()).service(), Floor())
    async with s.client as c:
        read = await _not_read(c, await s.stored(NOTICE))
        url = f"/v1/documents/extractions/{read['id']}/corrections"
        body = {"corrections": TYPED, "enteredBy": MAYA, "checked": True}
        saved = data(await c.post(url, json=body, headers=agents(s.tenant, "documents:edit")))
        again = data(await c.post(url, json=body, headers=agents(s.tenant, "documents:edit")))
    o = service_outbox
    events = await tenant_outbox(
        engine, s.tenant, sa.select(o).where(o.c.tenant_id == s.tenant, o.c.name == "extraction.corrected")
    )
    rows = saved["corrections"]
    assert [(r["field"], r["original"], r["correctedBy"]) for r in rows] == [
        ("invoice", None, MAYA),
        ("amount", None, MAYA),
    ], rows
    amount = saved["fields"]["amount"]
    assert (amount["value"], amount["notRead"], amount["needsReview"]) == (1940.0, "cut_off", False), amount
    assert saved["needsReview"] == [], saved
    assert len(again["corrections"]) == 2, "a repeat of the same values adds no rows"
    assert [(e["actor"], e["next_at"] is not None) for e in events] == [(MAYA, True)], events


async def test_a_person_cannot_save_values_under_someone_elses_name(make: Make) -> None:
    s = make(Replies(cut(), cut()).service(), Floor())
    async with s.client as c:
        read = await _not_read(c, await s.stored(NOTICE))
        url = f"/v1/documents/extractions/{read['id']}/corrections"
        named = await c.post(url, json={"corrections": TYPED, "enteredBy": MAYA}, headers=OPS)
        unscoped = await c.post(
            url, json={"corrections": TYPED, "enteredBy": MAYA}, headers=agents(s.tenant, "documents:view")
        )
    assert (named.status_code, named.json()["error"]["code"]) == (403, "entered_by_service_only"), named.text
    assert unscoped.status_code == 403, unscoped.text


async def test_one_field_typed_at_a_time_reaches_the_file_once_the_last_required_one_has_a_value(
    make: Make, engine: AsyncEngine
) -> None:
    """Edit fields on a read with no answer: a partly typed read sent the corrected event, which puts the read on the
    file, with the other required field still empty."""
    s = make(Replies(cut(), cut()).service(), Floor())
    o = service_outbox
    corrected = sa.select(o).where(o.c.tenant_id == s.tenant, o.c.name == "extraction.corrected")
    async with s.client as c:
        read = await _not_read(c, await s.stored(NOTICE))
        url = f"/v1/documents/extractions/{read['id']}/fields"
        data(await c.patch(f"{url}/invoice", json={"value": "NWF-88213"}, headers=OPS))
        partly = await tenant_outbox(engine, s.tenant, corrected)
        data(await c.patch(f"{url}/amount", json={"value": 1940}, headers=OPS))
        typed = await tenant_outbox(engine, s.tenant, corrected)
    assert partly == [], "a read with a required field still empty stays off the file"
    assert len(typed) == 1, typed
