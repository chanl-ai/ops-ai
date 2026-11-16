"""The replies of the knowledge-base, source, document, search and retrieval routes, key by key and value by value, by
failure mode: a store row that changes its shape (a column renamed, a JSON column left as text, a datetime written
another way, a null turned into a missing key) changing what a caller is sent, an error object changing its code, and
a body name the console sends no longer accepted. Generated ids and times are replaced by their kind, so the rest is
compared whole. Regenerate a fixture only for an intended change: `KB_REPIN=1` writes what the routes answer now."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, cast

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity.fastapi import DEV_TEAM
from ops_kb.files import FilesServiceIntake

from .conftest import kb_client
from .files_fake import FakeFilesService
from .pdfs import HARDSHIP, RATES, policy_pdf
from .test_add_existing_files import stored
from .test_readings import documents
from .test_retrieval import agents
from .test_sync import file_source, upload

PINS = Path(__file__).parent / "fixtures" / "reply-pins.json"
BODY_PINS = Path(__file__).parent / "fixtures" / "body-pins.json"
_TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(\+00:00|Z)?$")
# A day such as a document's effective date, which is the day the test runs.
_DATE = re.compile(r"^\d{4}-\d\d-\d\d$")
# A generated id holds a digit, so a code such as validation_error is compared as itself.
_ID = re.compile(r"^([a-z]+)_(?=[0-9a-z]*[0-9])[0-9a-z]{6,40}$")
# Measured, so only their being numbers is compared.
_MEASURED = {"durationSec", "lastRunDurationSec", "medianLatencyMs", "retrievalMs", "synthesisMs"}


def _key(k: str) -> str:
    return f"<{m.group(1)}>" if (m := _ID.match(k)) else k


def scrubbed(value: Any) -> Any:
    """`value` with every time, duration, file digest (a PDF holds its creation time) and generated id replaced by its
    kind, so two runs answer the same. A list of named records is compared by name: today's lists of knowledge bases
    leave the order of two made in one moment to the database."""
    if isinstance(value, dict):
        held = cast(dict[str, object], value)
        return {
            _key(k): f"<{k}>" if k in _MEASURED | {"digest"} and v is not None else scrubbed(v) for k, v in held.items()
        }
    if isinstance(value, list):
        items = [scrubbed(v) for v in cast(list[object], value)]
        if items and all(isinstance(i, dict) and "name" in i for i in items):
            items.sort(key=lambda i: json.dumps(i, sort_keys=True))
        return items
    if isinstance(value, str) and (m := _TIME.match(value)):
        return f"<time{m.group(2) or ''}>"
    if isinstance(value, str) and _DATE.match(value):
        return "<date>"
    if isinstance(value, str) and (m := _ID.match(value)):
        return f"<{m.group(1)}>"
    return value


def answer(r: httpx.Response) -> dict[str, Any]:
    """The status and the whole body, scrubbed: an error's object is pinned as a success's data is."""
    return {"status": r.status_code, "body": scrubbed(r.json()) if r.content else None}


def compare(seen: dict[str, Any], pins: Path) -> None:
    if os.environ.get("KB_REPIN"):
        pins.write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n")
    assert seen == json.loads(pins.read_text()), json.dumps(seen, indent=2, sort_keys=True)


async def test_the_knowledge_routes_keep_every_key_value_and_error_object(
    client: httpx.AsyncClient, tenant: str
) -> None:
    seen: dict[str, Any] = {}
    src = await file_source(client)
    sid = src["id"]
    seen["createSource"] = answer(await client.post("/v1/sources", json={"type": "file", "name": "Spare"}))
    # Both spellings of a body's names are accepted.
    body = {"name": "Lending", "owner": "maya@harborpine.example", "sourceIds": [sid]}
    created = await client.post("/v1/knowledge-bases", json=body)
    seen["createBase"] = answer(created)
    kb = created.json()["data"]["id"]
    snake = {"name": "Snake", "owner": "maya@harborpine.example", "source_ids": [sid], "color": "green"}
    seen["createBaseSnakeNames"] = answer(await client.post("/v1/knowledge-bases", json=snake))
    seen["duplicateName"] = answer(await client.post("/v1/knowledge-bases", json={**body, "sourceIds": []}))
    seen["noOwner"] = answer(await client.post("/v1/knowledge-bases", json={"name": "Nobody"}))
    seen["noName"] = answer(await client.post("/v1/knowledge-bases", json={"owner": "maya@harborpine.example"}))
    await upload(client, sid, "hardship.pdf", HARDSHIP)
    await upload(client, sid, "rates.pdf", RATES)
    seen["sync"] = answer(await client.post(f"/v1/sources/{sid}/sync"))
    changed = policy_pdf("Rate Sheet", [("1 Fixed rates", "The five-year fixed mortgage rate is now 5.19 percent.")])
    await upload(client, sid, "rates.pdf", changed)
    await client.post(f"/v1/sources/{sid}/sync")
    seen["listBases"] = answer(await client.get("/v1/knowledge-bases"))
    seen["listBasesSearched"] = answer(await client.get("/v1/knowledge-bases", params={"search": "snak"}))
    seen["options"] = answer(await client.get("/v1/knowledge-bases/options"))
    seen["refs"] = answer(await client.get("/v1/knowledge-bases/refs"))
    seen["getBase"] = answer(await client.get(f"/v1/knowledge-bases/{kb}"))
    seen["patchBase"] = answer(await client.patch(f"/v1/knowledge-bases/{kb}", json={"color": "red"}))
    seen["patchBaseBadSetting"] = answer(
        await client.patch(f"/v1/knowledge-bases/{kb}", json={"retrieval": {"nope": 1}})
    )
    seen["documents"] = answer(await client.get(f"/v1/knowledge-bases/{kb}/documents"))
    seen["listSources"] = answer(await client.get("/v1/sources"))
    seen["getSource"] = answer(await client.get(f"/v1/sources/{sid}"))
    seen["patchSource"] = answer(await client.patch(f"/v1/sources/{sid}", json={"tags": ["mortgage"]}))
    items = await client.get(f"/v1/sources/{sid}/items")
    seen["items"] = answer(items)
    first = items.json()["data"]["data"][0]["id"]
    seen["getItem"] = answer(await client.get(f"/v1/items/{first}"))
    runs = await client.get(f"/v1/sources/{sid}/runs")
    seen["runs"] = answer(runs)
    seen["getRun"] = answer(await client.get(f"/v1/sync-runs/{runs.json()['data']['data'][0]['id']}"))
    seen["tombstones"] = answer(await client.get(f"/v1/sources/{sid}/tombstones"))
    changes = await client.get("/v1/knowledge-changes", params={"view": "resolved"})
    seen["changes"] = answer(changes)
    seen["getChange"] = answer(await client.get(f"/v1/knowledge-changes/{changes.json()['data']['data'][0]['id']}"))
    ask = {"question": "How many mortgage payments can a borrower who lost their job defer?"}
    seen["query"] = answer(await client.post(f"/v1/knowledge-bases/{kb}/query", json=ask))
    seen["queryNothing"] = answer(
        await client.post(f"/v1/knowledge-bases/{kb}/query", json={"question": "Weather in Lisbon tomorrow?"})
    )
    search = {"kbIds": [kb], "question": "five-year fixed mortgage rate", "limit": 3}
    seen["search"] = answer(await client.post("/v1/knowledge-bases/search", json=search))
    seen["searchAsAgent"] = answer(
        await client.post(
            "/v1/knowledge-bases/search",
            json={"kb_ids": [kb], "question": search["question"], "limit": 3},
            headers=agents(tenant),
        )
    )
    seen["missingBase"] = answer(await client.get("/v1/knowledge-bases/kb_missing"))
    seen["missingSource"] = answer(await client.get("/v1/sources/src_missing"))
    seen["missingItem"] = answer(await client.get("/v1/items/item_missing"))
    seen["queryMissingBase"] = answer(await client.post("/v1/knowledge-bases/kb_missing/query", json=ask))
    seen["detach"] = answer(await client.delete(f"/v1/knowledge-bases/{kb}/sources/{sid}"))
    seen["deleteBase"] = answer(await client.delete(f"/v1/knowledge-bases/{kb}"))
    seen["deleteBaseAgain"] = answer(await client.delete(f"/v1/knowledge-bases/{kb}"))
    seen["deleteSource"] = answer(await client.delete(f"/v1/sources/{sid}"))
    compare(seen, PINS)


async def test_every_body_route_accepts_the_names_the_console_and_services_send(
    engine: AsyncEngine, tenant: str
) -> None:
    """Each route that takes a body, sent its fields under the console's camelCase names (and the snake_case spelling
    where a name has two words): a renamed or dropped name answers 422 instead of the pinned reply."""
    fake = FakeFilesService()
    files = fake.client()
    seen: dict[str, Any] = {}
    async with kb_client(engine, tenant, files=FilesServiceIntake(files)) as client:
        fid = await stored(fake, files, tenant, "rates.pdf", RATES)
        doc = await stored(fake, files, tenant, "hardship.pdf", HARDSHIP)
        src = (await client.post("/v1/sources", json={"type": "file", "name": "Policies", "aiCeiling": 2.5})).json()
        sid = src["data"]["id"]
        base = {"name": "Lending", "owner": "maya@harborpine.example", "sourceIds": [sid], "templateId": "lending"}
        seen["createBaseTemplate"] = answer(await client.post("/v1/knowledge-bases", json=base))
        base = {**base, "sourceDefaults": {"size": 700}}
        del base["templateId"]
        kb = (await client.post("/v1/knowledge-bases", json=base)).json()["data"]["id"]
        spare = (await client.post("/v1/sources", json={"type": "file", "name": "Spare"})).json()["data"]["id"]
        mapping: list[object] = []
        sent: dict[str, tuple[str, str, dict[str, object]]] = {
            "patchBase": ("PATCH", f"/v1/knowledge-bases/{kb}", {"sourceDefaults": {"size": 900}, "templateId": "x"}),
            "patchBaseSnake": ("PATCH", f"/v1/knowledge-bases/{kb}", {"source_defaults": {"size": 800}}),
            "attach": ("POST", f"/v1/knowledge-bases/{kb}/sources", {"sourceIds": [spare]}),
            "attachSnake": ("POST", f"/v1/knowledge-bases/{kb}/sources", {"source_ids": [spare]}),
            "addFiles": ("POST", f"/v1/sources/{sid}/files", {"fileIds": [fid]}),
            "addFilesSnake": ("POST", f"/v1/sources/{sid}/files", {"file_ids": [fid]}),
            "addDocuments": ("POST", f"/v1/knowledge-bases/{kb}/documents", {"fileIds": [doc]}),
            "sync": ("POST", f"/v1/sources/{sid}/sync", {"full": True, "retry": False}),
            "queryCollection": ("POST", f"/v1/knowledge-bases/{kb}/query", {"question": "fee", "collection": "x"}),
            "patchSource": ("PATCH", f"/v1/sources/{sid}", {"aiCeiling": 3.0, "metadataMapping": mapping}),
            "patchSourceSnake": ("PATCH", f"/v1/sources/{sid}", {"ai_ceiling": 4.0, "metadata_mapping": mapping}),
            "createSource": ("POST", "/v1/sources", {"type": "file", "name": "More", "kbIds": [kb], "fileIds": []}),
            "createSourceSnake": ("POST", "/v1/sources", {"type": "file", "name": "Most", "kb_ids": [kb]}),
            "preview": ("POST", "/v1/sources/preview", {"config": {"plugin": "opsai.nothing", "source": "pages"}}),
            "scopes": ("POST", "/v1/sources/scopes", {"plugin": "opsai.nothing", "source": "sites", "query": "x"}),
            "liftTombstones": ("POST", f"/v1/sources/{sid}/tombstones/lift", {"ids": ["item_missing1"]}),
            "aiApproval": ("POST", f"/v1/sources/{sid}/ai-approval", {"decision": "approve"}),
            "decide": ("POST", "/v1/knowledge-changes/decide", {"ids": ["chg_missing1"], "decision": "reject"}),
            "editChange": ("PATCH", "/v1/knowledge-changes/chg_missing1", {"question": "Q?", "answer": "A."}),
        }
        for key, (method, path, body) in sent.items():
            seen[key] = answer(await client.request(method, path, json=body))
    event = {"name": "reading.failed", "key": "evt_1", "teamId": DEV_TEAM, "payload": {"fileId": "fil_missing1"}}
    async with kb_client(engine, tenant) as client:
        page = {"title": "Fees", "text": "No fee to defer."}
        seen["addPage"] = answer(await client.post(f"/v1/knowledge-bases/{kb}/pages", json=page))
        push = (await client.post("/v1/sources", json={"type": "push", "name": "Rules", "kbIds": [kb]})).json()
        item = {
            "name": "fees",
            "title": "Fees",
            "text": "# Fees",
            "mime": "text/markdown",
            "url": "https://x.example/f",
        }
        written = await client.post(f"/v1/sources/{push['data']['id']}/items", json=item)
        seen["putItem"] = answer(written)
        iid = written.json()["data"]["item"]["id"]
        seen["verifyItem"] = answer(await client.post(f"/v1/items/{iid}/verify", json={"verified": True}))
        owner = {"owner": "maya@harborpine.example"}
        seen["itemOwner"] = answer(await client.put(f"/v1/items/{iid}/owner", json=owner))
        # The event route is a service's: documents-service reports a reading under these names.
        seen["event"] = answer(await client.post("/v1/events", json=event, headers=documents(tenant)))
        snake = {**event, "team_id": DEV_TEAM, "key": "evt_2"}
        del snake["teamId"]
        seen["eventSnake"] = answer(await client.post("/v1/events", json=snake, headers=documents(tenant)))
    compare(seen, BODY_PINS)
