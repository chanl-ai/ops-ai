"""A source's settings, by failure mode: a setting shown that a sync does not apply, an invalid setting saved, a
source's OCR mode that never reaches its reading, a rule that does not keep an item out of search, a settings save
that approves AI steps, and a settings change nobody is told needs a rebuild."""

from __future__ import annotations

import re
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

import httpx
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb import source_settings
from ops_kb.files import KnowledgeFiles
from ops_kb.source_settings import EFFECTS, SourceSettings, defaults, index_key, merged, rebuild_for, wire

from .conftest import kb_client
from .pdfs import HARDSHIP, RATES, policy_pdf
from .readings_fake import LocalReadings
from .test_bases_and_sources import data
from .test_rebuild import finished
from .test_sync import file_source, upload

LONG = policy_pdf(
    "Mortgage servicing manual",
    [(f"Section {n}", " ".join(f"Clause {n}.{w} covers escrow, arrears and payment holidays." for w in range(60)))
     for n in range(1, 4)],
)  # fmt: skip


async def chunks_of(client: httpx.AsyncClient, source_id: str) -> list[dict[str, Any]]:
    [item] = data(await client.get(f"/v1/sources/{source_id}/items"))["data"]
    return data(await client.get(f"/v1/items/{item['id']}"))["detail"]["chunks"]


async def test_a_new_file_source_answers_the_settings_a_sync_applies(client: httpx.AsyncClient) -> None:
    src = await file_source(client)
    assert src["parsing"] == {"ocr": "auto", "tables": True, "vision": False}
    assert src["ingest"]["strategies"] == ["structure", "context_headers"] and src["ingest"]["size"] == 400
    assert src["cleaning"] == {"furniture": False, "mainContent": False, "siteRepeats": False, "duplicates": "flag"}
    assert src["rules"] == [] and src["metadataMapping"] == []


async def test_a_split_change_is_applied_and_no_rebuild_is_needed_after(client: httpx.AsyncClient) -> None:
    src = await file_source(client)
    await upload(client, src["id"], "manual.pdf", LONG)
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    before = await chunks_of(client, src["id"])
    patch = {"ingest": {"strategies": ["fixed"], "size": 120, "overlap": 10}}
    saved = data(await client.patch(f"/v1/sources/{src['id']}", json=patch))
    assert (saved["ingest"]["strategies"], saved["ingest"]["size"], saved["ingest"]["preset"]) == (
        ["fixed"],
        120,
        "custom",
    )
    run = await finished(client, saved["rebuild"]["id"])
    assert run["counts"]["rebuilt"] == 1, run
    after = await chunks_of(client, src["id"])
    assert len(after) > len(before) and max(c["tokens"] for c in after) <= 140, [c["tokens"] for c in after]
    assert data(await client.get(f"/v1/sources/{src['id']}"))["reindexNeeded"] is False


async def test_an_invalid_setting_is_refused_and_nothing_is_saved(client: httpx.AsyncClient) -> None:
    src = await file_source(client)
    bad = await client.patch(f"/v1/sources/{src['id']}", json={"ingest": {"size": 200, "overlap": 200}})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_settings", bad.text
    vision = await client.patch(f"/v1/sources/{src['id']}", json={"parsing": {"vision": True}})
    assert vision.status_code == 400 and vision.json()["error"]["code"] == "invalid_settings", vision.text
    assert data(await client.get(f"/v1/sources/{src['id']}"))["ingest"]["overlap"] == 40


async def test_the_sources_ocr_mode_reaches_its_reading(engine: AsyncEngine, tenant: str) -> None:
    intake = KnowledgeFiles(Path(mkdtemp(prefix="kb-files-")))
    readings = LocalReadings(intake)
    asked: list[str] = []
    real = readings.reading

    async def recording(tenant: str, team: str, file_id: str, *, ocr: str) -> dict[str, Any]:
        asked.append(ocr)
        return await real(tenant, team, file_id, ocr=ocr)

    readings.reading = recording  # type: ignore[method-assign]
    async with kb_client(engine, tenant, files=intake, readings=readings) as client:
        src = await file_source(client)
        assert (
            data(await client.patch(f"/v1/sources/{src['id']}", json={"parsing": {"ocr": "off"}}))["parsing"]["ocr"]
            == "off"
        )
        await upload(client, src["id"], "hardship.pdf", HARDSHIP)
        data(await client.post(f"/v1/sources/{src['id']}/sync"))
        assert asked == ["off"]
        saved = data(await client.patch(f"/v1/sources/{src['id']}", json={"parsing": {"ocr": "always"}}))
        await finished(client, saved["rebuild"]["id"])
        assert asked == ["off", "always"]


async def test_an_exclude_rule_keeps_an_item_out_and_takes_an_indexed_one_out_of_search(
    client: httpx.AsyncClient,
) -> None:
    src = await file_source(client)
    kb = data(
        await client.post(
            "/v1/knowledge-bases",
            json={"name": "Lending", "owner": "james@harborpine.example", "sourceIds": [src["id"]]},
        ),
        201,
    )
    await upload(client, src["id"], "hardship.pdf", HARDSHIP)
    await upload(client, src["id"], "rates.pdf", RATES)
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    rule = {"id": "r1", "kind": "exclude", "field": "path", "value": "rates.*"}
    data(await client.patch(f"/v1/sources/{src['id']}", json={"rules": [rule]}))
    run = data(await client.post(f"/v1/sources/{src['id']}/sync"))
    assert (run["counts"]["excluded"], run["counts"]["deleted"]) == (1, 1), run
    assert any("Exclude rule: path matches rates.*" in line for line in run["log"]), run["log"]
    paths = [i["path"] for i in data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]]
    assert paths == ["hardship.pdf"]
    found = data(
        await client.post(
            "/v1/knowledge-bases/search", json={"kbIds": [kb["id"]], "question": "fixed rate mortgage interest"}
        )
    )
    assert all(p["title"] != "rates.pdf" for p in found["passages"]), found


async def test_a_settings_save_never_approves_an_ai_step(client: httpx.AsyncClient) -> None:
    src = await file_source(client)
    patch = {
        "ingest": {"strategies": ["structure", "faq"], "approval": {"status": "approved", "approvedSteps": ["faq"]}}
    }
    saved = data(await client.patch(f"/v1/sources/{src['id']}", json=patch))
    assert saved["ingest"]["approval"]["status"] == "pending" and saved["ingest"]["approval"]["approvedSteps"] == []


# One saved change per setting, as the console's Settings tab sends it; None: it cannot be changed by a save.
CHANGES: dict[str, dict[str, Any] | None] = {
    "parsing.ocr": {"parsing": {"ocr": "always"}},
    "parsing.tables": {"parsing": {"tables": False}},
    "parsing.vision": None,
    "cleaning.furniture": {"cleaning": {"furniture": True}},
    "cleaning.main_content": {"cleaning": {"mainContent": True}},
    "cleaning.site_repeats": {"cleaning": {"siteRepeats": True}},
    "cleaning.duplicates": {"cleaning": {"duplicates": "skip"}},
    "ingest.preset": {"ingest": {"preset": "custom"}},
    "ingest.strategies": {"ingest": {"strategies": ["fixed"]}},
    "ingest.size": {"ingest": {"size": 600}},
    "ingest.overlap": {"ingest": {"overlap": 20}},
    "ingest.child_size": {"ingest": {"childSize": 100}},
    "ingest.questions_per_section": {"ingest": {"questionsPerSection": 5}},
    "ingest.columns": {"ingest": {"columns": [{"name": "Rate", "role": "searchable"}]}},
    "ingest.model": {"ingest": {"model": "bank-other"}},
    # Decided on its own route (test_a_settings_save_never_approves_an_ai_step); a save never changes it.
    "ingest.approval": None,
    "rules": {"rules": [{"id": "r1", "kind": "exclude", "field": "path", "value": "drafts/"}]},
    "metadata_mapping": {"metadataMapping": [{"key": "product", "from": "static:mortgage"}]},
    "schedule": {"schedule": {"kind": "daily", "time": "03:00", "tz": "UTC"}},
    "ai_ceiling": {"aiCeiling": 9.0},
}


def _leaves(model: type[BaseModel], prefix: str = "") -> list[str]:
    out: list[str] = []
    for name, field in model.model_fields.items():
        kind = field.annotation
        if isinstance(kind, type) and issubclass(kind, BaseModel) and name != "approval":
            out += _leaves(kind, f"{prefix}{name}.")
        else:
            out.append(f"{prefix}{name}")
    return out


def _readers(path: str) -> int:
    """Reads of a source's setting at `path` in kb-service's code outside this module's own validation."""
    pattern = re.compile(rf"(?:settings|settings_of\([^()]*\))\.{re.escape(path)}\b")
    src = Path(source_settings.__file__).parent
    return sum(len(pattern.findall(f.read_text())) for f in src.rglob("*.py") if f.name != "source_settings.py")


def test_every_source_setting_does_what_its_effect_says() -> None:
    """A setting the console saves that nothing reads is the failure. Each effect is checked against the code: a
    `split` change reaches what the pieces are built from, a `read` or `sync` setting has a reader, a `kept` one has
    none and a `label` save changes nothing; a save rebuilds exactly what its effect says."""
    assert sorted(_leaves(SourceSettings)) == sorted(EFFECTS) == sorted(CHANGES)
    base = defaults("files")
    for path, effect in EFFECTS.items():
        readers = _readers(path)
        if effect in ("read", "sync"):
            assert readers > 0, f"{path}: nothing reads it"
        elif effect == "kept":
            assert readers == 0, f"{path} is read; say where it applies"
        if (patch := CHANGES[path]) is None:
            continue
        after = merged(base, patch)
        stored, pieces = wire(after) != wire(base), index_key(after) != index_key(base)
        assert stored == (effect != "label"), f"{path}: a save stored={stored}"
        assert pieces == (effect == "split"), f"{path}: the pieces depend on it={pieces}"
        assert rebuild_for(base, after) == {"read": "read", "split": "split"}.get(effect, "none"), path
