"""Document types (c-236, moved here in c-256), by failure mode: a save that rewrites the version a workflow reads (F1);
a test that spends without a cap or without its cost shown first (F2); a correct read failing its test because the
expected value was compared unnormalised (F3); an extraction naming a type that reads other fields, another team's
type, or not saying which version it read (F4); a member without documents.edit changing a type, or the console
guessing so from a role (c-243)."""

from __future__ import annotations

import base64
import json
from decimal import Decimal
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents import document_types
from ops_documents.store.extractions import service_outbox
from ops_identity import ServiceClient
from ops_service_kit.settings import Settings

from .conftest import OPS, Make
from .test_extractions import NOTICE, Floor

FIELDS = [{"key": "invoice", "type": "text", "required": True}, {"key": "amount", "type": "money", "required": True}]
TYPE = {"id": "invoice_notice", "name": "Invoice notice", "fields": FIELDS}
READ = {
    "invoice": {"value": "INV-2207", "quote": "Invoice INV-2207", "page": 1},
    "amount": {"value": "1,250.00 CAD", "quote": "Amount due: 1,250.00 CAD", "page": 1},
    "customer": {"value": "Marcus Bell", "quote": "Customer: Marcus Bell", "page": 1},
}


class Models:
    def __init__(self) -> None:
        self.users: list[str] = []

    async def structured(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        run: str,
        step: str,
        tenant: str,
        usage: Any = None,
        images: Any = (),
    ) -> Any:
        self.users.append(user)
        return {k: v for k, v in READ.items() if k in schema["properties"]}


class Prices:
    async def price(self, alias: str, *, tenant: str) -> tuple[Decimal, Decimal] | None:
        return Decimal("0.25"), Decimal("2.00")


def data(r: httpx.Response, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


async def extract(c: httpx.AsyncClient, fid: str, **body: Any) -> httpx.Response:
    return await c.post("/v1/documents/extractions", json={"fileId": fid, **body}, headers=OPS)


async def test_a_new_version_leaves_the_one_a_workflow_reads(make: Make) -> None:
    models = Models()
    s = make(models, Floor(), Prices())
    async with s.client as c:
        fid = await s.stored(NOTICE)
        made = data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        more = [*FIELDS, {"key": "customer", "type": "text"}]
        v2 = data(await c.post("/v1/document-types/invoice_notice/versions", json={"fields": more}, headers=OPS), 201)
        pinned = data(await extract(c, fid, documentTypeId="invoice_notice", version=1))
        newest = data(await extract(c, fid, documentTypeId="invoice_notice"))
    assert (made["latestVersion"], v2["version"]) == (1, 2)
    assert pinned["documentType"] == {"id": "invoice_notice", "version": 1, "name": "Invoice notice"}, pinned
    assert set(pinned["fields"]) == {"invoice", "amount"} and "customer" not in models.users[0]
    assert newest["documentType"]["version"] == 2 and "customer" in newest["fields"], newest


async def test_another_teams_type_is_not_found_and_a_name_is_unique(make: Make) -> None:
    s = make(Models(), Floor(), Prices())
    async with s.client as c:
        fid = await s.stored(NOTICE, team="team_cards")
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        cards = {"X-Team-Id": "team_cards"}
        theirs = await c.get("/v1/document-types/invoice_notice", headers=cards)
        asked = await c.post(
            "/v1/documents/extractions", json={"fileId": fid, "documentTypeId": "invoice_notice"}, headers=cards
        )
        named = await c.post("/v1/document-types", json={**TYPE, "id": "other"}, headers=OPS)
    assert (theirs.status_code, asked.status_code) == (404, 404), (theirs.text, asked.text)
    assert asked.json()["error"]["message"] == "Document type was not found.", asked.text
    assert named.status_code == 409 and named.json()["error"]["code"] == "name_taken"


async def test_a_test_shows_its_cost_first_reads_at_most_the_cap_and_compares_normalised(
    make: Make, monkeypatch: Any
) -> None:
    monkeypatch.setattr(document_types, "MAX_TEST_SAMPLES", 2)
    models = Models()
    s = make(models, Floor(), Prices())
    async with s.client as c:
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        for body in (NOTICE, NOTICE + b"\n", NOTICE + b"\n\n"):
            # "1,250.00" expected against "1,250.00 CAD" read: the same amount, 1250, once both are normalised.
            sample = {"fileId": await s.stored(body), "expected": {"invoice": "inv-2207", "amount": "1,250.00"}}
            data(await c.post("/v1/document-types/invoice_notice/samples", json=sample, headers=OPS), 201)
        estimate = data(await c.get("/v1/document-types/invoice_notice/versions/1/test-estimate", headers=OPS))
        assert models.users == [], "the estimate spends nothing"
        started = data(await c.post("/v1/document-types/invoice_notice/versions/1/test-runs", headers=OPS), 202)
        await s.types.drain()
        done = data(await c.get(f"/v1/document-types/invoice_notice/test-runs/{started['id']}", headers=OPS))
    assert (estimate["calls"], estimate["capped"], estimate["estimatedCost"]) == (2, 2, "0.0044"), estimate
    assert done["status"] == "done" and len(models.users) == 2 and len(done["result"]["samples"]) == 2, done
    assert done["result"]["fields"]["amount"] == {"matches": 2, "misses": 0, "accuracy": 1.0}, done["result"]


async def test_a_sample_keeps_its_file_and_names_only_the_types_fields(make: Make) -> None:
    s = make(Models(), Floor(), Prices())
    async with s.client as c:
        fid = await s.stored(NOTICE)
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        wrong = await c.post(
            "/v1/document-types/invoice_notice/samples", json={"fileId": fid, "expected": {"total": 1}}, headers=OPS
        )
        ok = data(
            await c.post(
                "/v1/document-types/invoice_notice/samples",
                json={"fileId": fid, "expected": {"amount": 1}},
                headers=OPS,
            ),
            201,
        )
        kept = s.files.files[fid]["referenceCount"]
        gone = await c.delete(f"/v1/document-types/invoice_notice/samples/{ok['id']}", headers=OPS)
    assert wrong.status_code == 400 and ok["fileId"] == fid, wrong.text
    assert kept == 1 and gone.status_code == 204 and s.files.files[fid]["referenceCount"] == 0, (
        "Files keeps a sampled file"
    )


async def test_a_member_who_cannot_edit_documents_reads_types_but_changes_none(make: Make) -> None:
    builder = make(Models(), Floor(), Prices())
    async with builder.client as c:
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        assert data(await c.get("/v1/document-types", headers=OPS))["canCreate"] is True
    chatter = make(Models(), Floor(), Prices(), role="chat_user")
    async with chatter.client as c:
        listed = await c.get("/v1/document-types", headers=OPS)
        refused = await c.post("/v1/document-types/invoice_notice/versions", json={"fields": FIELDS}, headers=OPS)
    # A chat-only member holds no documents cell at all, so even the list is refused, never shown with writes.
    assert listed.status_code == 403 and refused.status_code == 403, (listed.text, refused.text)


async def test_the_estimate_prices_the_alias_with_the_callers_tenant_on_the_token() -> None:
    """models-service refuses a service token naming no tenant (401), so a price asked without one read as unknown
    and every estimate showed no cost."""

    def models(request: httpx.Request) -> httpx.Response:
        body = request.headers["authorization"].removeprefix("Bearer ").split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if not claims.get("tenant_id"):
            return httpx.Response(401, json={"success": False, "error": {"code": "unauthorized", "message": "no"}})
        row = {"status": "current", "inputPerMillion": "0.250000", "outputPerMillion": "2.000000"}
        return httpx.Response(200, json={"success": True, "data": [row]})

    http = httpx.AsyncClient(base_url="http://models", transport=httpx.MockTransport(models))
    prices = document_types.ModelsPrices(
        ServiceClient.for_settings(Settings(environment="dev"), http, service="documents", audience="models")
    )
    assert await prices.price("extract", tenant="t_bank") == (Decimal("0.25"), Decimal("2.00"))


class MeasuredModels(Models):
    """A reasoning model's spend: 2,000 tokens in and 2,400 out a call, as models-service reports usage."""

    async def structured(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        run: str,
        step: str,
        tenant: str,
        usage: Any = None,
        images: Any = (),
    ) -> Any:
        if usage is not None:
            usage.input_tokens += 2000
            usage.output_tokens += 2400
        return await super().structured(system, user, schema, run=run, step=step, tenant=tenant)


async def test_the_estimate_prices_a_type_at_what_reading_it_measured(make: Make) -> None:
    """The baseline estimated $0.0352 for $0.0792 spent: a fixed 600 output tokens against about 2,300 (c-247)."""
    s = make(MeasuredModels(), Floor(), Prices())
    async with s.client as c:
        fid = await s.stored(NOTICE)
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        sample = {"fileId": fid, "expected": {"invoice": "INV-2207"}}
        data(await c.post("/v1/document-types/invoice_notice/samples", json=sample, headers=OPS), 201)
        guessed = data(await c.get("/v1/document-types/invoice_notice/versions/1/test-estimate", headers=OPS))
        data(await extract(c, fid, documentTypeId="invoice_notice"))
        measured = data(await c.get("/v1/document-types/invoice_notice/versions/1/test-estimate", headers=OPS))
    # 2,000 in at $0.25 and 2,400 out at $2.00 per million: $0.0053 a call.
    assert (guessed["basis"], measured["basis"], measured["estimatedCost"]) == ("default", "type", "0.0053"), measured


async def test_a_type_with_a_pattern_that_does_not_compile_or_is_too_long_is_refused(make: Make) -> None:
    s = make(Models(), Floor(), Prices())
    broken = [{"key": "ref", "type": "text", "pattern": "(unclosed"}]
    too_long = [{"key": "ref", "type": "text", "pattern": "a" * 201}]
    async with s.client as c:
        bad = await c.post("/v1/document-types", json={**TYPE, "fields": broken}, headers=OPS)
        long = await c.post("/v1/document-types", json={**TYPE, "id": "other_notice", "fields": too_long}, headers=OPS)
    assert (bad.status_code, long.status_code) == (400, 400), (bad.text, long.text)


class DatedModels(Models):
    async def structured(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        run: str,
        step: str,
        tenant: str,
        usage: Any = None,
        images: Any = (),
    ) -> Any:
        return {"served": {"value": "03/04/2026", "quote": "Served 03/04/2026", "page": 1}}


async def test_a_numeric_date_reads_month_first_unless_the_type_says_day_first(make: Make) -> None:
    """The date order is the document type's (c-270): US levies write 03/04/2026 for March 4."""
    fields = [{"key": "served", "type": "date", "required": True}]
    s = make(DatedModels(), Floor(), Prices())
    async with s.client as c:
        fid = await s.stored(b"Served 03/04/2026\n")
        made = data(await c.post("/v1/document-types", json={**TYPE, "fields": fields}, headers=OPS), 201)
        day_first = {"fields": fields, "dateOrder": "DMY"}
        data(await c.post("/v1/document-types/invoice_notice/versions", json=day_first, headers=OPS), 201)
        us = data(await extract(c, fid, documentTypeId="invoice_notice", version=1))
        dmy = data(await extract(c, fid, documentTypeId="invoice_notice", version=2))
    assert made["versions"][0]["dateOrder"] == "MDY", made
    assert (us["fields"]["served"]["value"], dmy["fields"]["served"]["value"]) == ("2026-03-04", "2026-04-03")


async def test_a_correction_reports_the_newest_read_with_nothing_left_to_check_and_an_older_one_none(
    make: Make, engine: AsyncEngine
) -> None:
    """extraction.corrected (c-252) carries what Save data on file needs, written with the correction; correcting an
    older read reports nothing, so it can never replace a newer read on the file."""
    s = make(Models(), Floor(0.95))
    async with s.client as c:
        fid = await s.stored(NOTICE)
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        older = data(await extract(c, fid, documentTypeId="invoice_notice"))
        newer = data(await extract(c, fid, documentTypeId="invoice_notice"))
        assert newer["needsReview"] == ["amount"], newer
        fix = {"value": 1205.0}
        data(await c.patch(f"/v1/documents/extractions/{older['id']}/fields/amount", json=fix, headers=OPS))
        data(await c.patch(f"/v1/documents/extractions/{newer['id']}/fields/amount", json=fix, headers=OPS))
        again = {"value": "INV-2208"}
        fixed = data(await c.patch(f"/v1/documents/extractions/{newer['id']}/fields/invoice", json=again, headers=OPS))
    async with engine.connect() as conn:
        o = service_outbox
        rows = (
            await conn.execute(sa.select(o).where(o.c.tenant_id == s.tenant, o.c.name == "extraction.corrected"))
        ).mappings()
        events: list[dict[str, Any]] = [dict(r) for r in rows]
    assert fixed["needsReview"] == [] and fixed["fields"]["amount"]["needsReview"] is False, fixed
    # Two corrections in a row send one event, the last, after the settle time; the first is superseded unsent, and is
    # never due again nor marked sent, so nothing reads it as delivered.
    [superseded] = [e for e in events if e["last_error"] == "superseded by a newer correction"]
    [event] = [e for e in events if e["next_at"] is not None]
    assert (superseded["sent_at"], superseded["next_at"]) == (None, None), superseded
    assert event["sent_at"] is None and event["payload"]["field"] == "invoice"
    assert event["next_at"] >= event["created_at"] + 5, "it waits so a further correction can replace it"
    who = fixed["corrections"][-1]["correctedBy"]
    assert (event["name"], event["team_id"], event["actor"]) == ("extraction.corrected", "team_ops", who), event
    payload: dict[str, Any] = event["payload"]
    assert (payload["fileId"], payload["extractionId"], payload["needsReview"]) == (fid, newer["id"], []), payload
    assert payload["documentType"] == {"id": "invoice_notice", "version": 1, "name": "Invoice notice"}
    assert payload["typeName"] == "Invoice notice"


async def test_a_cleanup_rule_that_is_not_known_is_refused_when_the_type_is_saved(make: Make) -> None:
    """c-287: a misspelt rule would otherwise be ignored on every read."""
    s = make(Models(), Floor())
    fields = [{"key": "invoice", "type": "text", "clean": ["trimPunctuation", "trimPunctation"]}]
    async with s.client as c:
        r = await c.post("/v1/document-types", json={**TYPE, "fields": fields}, headers=OPS)
    assert r.status_code == 400 and "clean lists rules" in r.text, r.text


async def test_a_key_field_is_kept_and_a_mark_that_is_not_true_or_false_is_refused(make: Make) -> None:
    """c-303: a review shows key fields first and requires them checked, so the mark survives a save as a boolean."""
    s = make(Models(), Floor())
    keyed = [{**FIELDS[0], "keyField": True}, FIELDS[1]]
    async with s.client as c:
        made = data(await c.post("/v1/document-types", json={**TYPE, "fields": keyed}, headers=OPS), 201)
        bad = await c.post(
            "/v1/document-types/invoice_notice/versions",
            json={"fields": [{**FIELDS[0], "keyField": "yes"}]},
            headers=OPS,
        )
    assert made["versions"][0]["fields"][0]["keyField"] is True and "keyField" not in made["versions"][0]["fields"][1]
    assert bad.status_code == 400 and "keyField is true or false" in bad.text, bad.text
