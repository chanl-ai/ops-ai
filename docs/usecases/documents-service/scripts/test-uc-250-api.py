# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-250 Every fixture of four document types is read end to end, api layer:
docs/usecases/documents-service/every-fixture-is-read-end-to-end.md.

Own services, no real model: models-service on the fake OpenAI with an answer per fixture
(services/documents-service/tests/fixtures/fake-model, made by scripts/make_fake_reads.py), files-service with
scanning off, platform-service for the team's pageImages policy, and documents-service with the four seeded document
types: restraining notices, tax levies, supplier invoices and bank statements. The fake answers what expected.json
holds, so this proves what happens around the model (classify, grounding, the field checks, boxes, templates, page
images), not the model's accuracy."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx
from usecase_harness import (
    ROOT,
    bearer,
    check,
    data,
    fake_openai,
    finish,
    kb,
    models,
    platform,
    service_headers,
    signed_in,
)

DOCS = ROOT / "services" / "documents-service"
RULES = DOCS / "tests" / "fixtures" / "fake-model"
OPS = {"X-Team-Id": "team_ops"}
# The forms a template is suggested for: five reads of the master make the offer and the draft.
FORMS = {"supplier_invoice": "INV", "bank_statement": "STMT"}
# A scan that takes the model path, for the page image gates (c-295), and the alias documents-service reads with.
SCAN = ("restraining", "TEST001_scan.pdf")
MODELS_ADMIN = service_headers("models")


def seeded() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("seed_document_types", DOCS / "scripts" / "seed_document_types.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_document_types"] = module
    spec.loader.exec_module(module)
    return {d["id"]: (d, folder) for d, _, folder in module.SEEDED.values()}


def keyed(definition: dict[str, Any], dated: Any) -> dict[str, dict[str, Any]]:
    """The type's fields by key, each date field with the type's date order (month first unless the type says)."""
    return {f["key"]: f for f in dated(definition["fields"], definition.get("dateOrder"))}


def upload(files: httpx.Client, folder: Path, name: str) -> str:
    body = (folder / name).read_bytes()
    meta = {"name": name, "size": len(body), "mime": "application/pdf", "purpose": "case_attachment"}
    ticket = data(files.post("/v1/files/uploads", json={**meta, "digest": hashlib.sha256(body).hexdigest()}))
    files.put(ticket["uploadUrl"], headers=ticket.get("headers") or {}, content=body).raise_for_status()
    return str(data(files.post(f"/v1/files/uploads/{ticket['fileId']}/complete"))["file"]["id"])


def read(documents: httpx.Client, fid: str, body: dict[str, Any]) -> dict[str, Any]:
    r = documents.post("/v1/documents/extractions", json={"fileId": fid, **body})
    return data(r) or {"error": r.text[:300]}


def main() -> None:
    sys.path.insert(0, str(DOCS / "src"))
    # The service's own comparison, on fields carrying the version's date order as a read's fields do.
    from ops_documents.document_types import dated, matches  # noqa: PLC0415

    kinds = seeded()
    with (
        tempfile.TemporaryDirectory(prefix="uc250-") as tmp,
        platform() as (people, _inner),
        fake_openai(RULES) as fake,
        models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
        kb(
            Path(tmp) / "files",
            models_url=models_url,
            platform_url=str(people.base_url).rstrip("/"),
            document_types=True,
        ) as knowledge,
        httpx.Client(base_url=models_url, timeout=30) as model_admin,
        httpx.Client(base_url=knowledge.files_url, headers=OPS, timeout=60) as files,
        httpx.Client(base_url=knowledge.documents_url, headers=OPS, timeout=180) as documents,
    ):
        ids: dict[str, str] = {}
        reads: dict[str, dict[str, Any]] = {}
        wrong: list[str] = []
        unboxed: list[str] = []
        for type_id, (definition, folder) in kinds.items():
            fields = keyed(definition, dated)
            expected: dict[str, dict[str, Any]] = json.loads((folder / "expected.json").read_text())
            for name, entry in sorted(expected.items()):
                if entry.get("imageOnly"):
                    continue
                ids[name] = upload(files, folder, name)
                got = reads[name] = read(documents, ids[name], {"documentTypeId": type_id})
                values = got.get("fields") or {}
                for key, want in entry["expected"].items():
                    field = values.get(key) or {}
                    if key in fields and not matches(fields[key], want, field.get("value")):
                        wrong.append(f"{name} {key}: want {want!r} got {field.get('value')!r}")
                    if (field.get("citation") or {}).get("quote") and not field.get("boxes"):
                        unboxed.append(f"{name} {key}")
        check(
            "1 every text fixture of the four types reads its expected values, and every quoted field has a box",
            len(reads) >= 30 and not wrong and not unboxed and all(r.get("status") == "done" for r in reads.values()),
            {"read": len(reads), "wrong": wrong[:10], "unboxed": unboxed[:10]},
        )

        detected: dict[str, Any] = {}
        for type_id, (_, folder) in kinds.items():
            name = sorted(
                n for n, e in json.loads((folder / "expected.json").read_text()).items() if not e.get("imageOnly")
            )[0]
            got = read(documents, ids[name], {"detect": True})
            detected[name] = ((got.get("documentType") or {}).get("id"), type_id)
        check(
            "2 one fixture of each type read with Detect is read as its own type",
            all(found == wanted for found, wanted in detected.values()),
            detected,
        )

        offers: dict[str, Any] = {}
        saved: dict[str, Any] = {}
        paths: dict[str, Any] = {}
        for type_id, prefix in FORMS.items():
            definition, folder = kinds[type_id]
            expected = json.loads((folder / "expected.json").read_text())
            masters = [reads[f"{prefix}A0{i}.pdf"]["id"] for i in range(1, 6)]
            offers[type_id] = data(documents.get(f"/v1/document-types/{type_id}/template-offers")) or []
            suggested = (
                data(documents.post(f"/v1/document-types/{type_id}/templates/suggest", json={"extractionIds": masters}))
                or {}
            )
            body = {"fields": definition["fields"], "templates": [suggested.get("template")]}
            saved[type_id] = documents.post(f"/v1/document-types/{type_id}/versions", json=body).status_code
            for name in (
                f"{prefix}A06.pdf",
                f"{prefix}A07_scan.pdf",
                f"{prefix}A08_scan.pdf",
                f"{prefix}A09_misprint.pdf",
                f"{prefix}B01.pdf",
                f"{prefix}B02.pdf",
            ):
                fid = ids.get(name) or upload(files, folder, name)
                got = read(documents, fid, {"documentTypeId": type_id, "ocr": bool(expected[name].get("imageOnly"))})
                fields = keyed(definition, dated)
                found = got.get("fields") or {}
                bad = [
                    k
                    for k, w in expected[name]["expected"].items()
                    if not matches(fields[k], w, (found.get(k) or {}).get("value"))
                ]
                review = [k for k in bad if (found.get(k) or {}).get("needsReview")]
                # A date printed impossible: read from its zone, rejected by the date check, no value, sent to review.
                rejected = {
                    k: (found.get(k) or {}).get("value") is None
                    and (found.get(k) or {}).get("needsReview") is True
                    and (found.get(k) or {}).get("extractedValue") == printed
                    for k, printed in (expected[name].get("printedInvalid") or {}).items()
                }
                paths[name] = {
                    "path": got.get("path"),
                    "miss": bool(got.get("templateMiss")),
                    "wrong": bad,
                    "toReview": review,
                    "rejected": rejected,
                }
        layout_a = [n for n in paths if "A0" in n]
        layout_b = [n for n in paths if "B0" in n]
        check(
            "3 five reads of each master form offer a template, and the suggestion saves as a new version",
            all(len(o) == 1 and o[0]["count"] >= 5 for o in offers.values()) and set(saved.values()) == {201},
            {"offers": {k: [x["count"] for x in v] for k, v in offers.items()}, "saved": saved},
        )
        check(
            "4 the rest of each form, both scans included, is read by the template; an impossible date is not saved",
            all(paths[n]["path"] == "template" and paths[n]["wrong"] == paths[n]["toReview"] for n in layout_a)
            and all(
                paths[f"{p}A09_misprint.pdf"]["rejected"] and all(paths[f"{p}A09_misprint.pdf"]["rejected"].values())
                for p in FORMS.values()
            ),
            {n: paths[n] for n in layout_a},
        )
        check(
            "5 files of another layout take the model path with the template's miss recorded",
            all(paths[n]["path"] == "model" and paths[n]["miss"] and not paths[n]["wrong"] for n in layout_b),
            {n: paths[n] for n in layout_b},
        )
        page_images(people, model_admin, files, documents, kinds)
        examples(documents, reads)
    finish()


def examples(documents: httpx.Client, reads: dict[str, dict[str, Any]]) -> None:
    """Check 7 (c-297): a correction of a typed read becomes an example of its type, listed for the team with the line
    its value was printed on, and removed it is gone; a value its cited line does not show teaches nothing."""
    first = reads["INVA01.pdf"]
    field = f"/v1/documents/extractions/{first['id']}/fields/invoice_no"
    url = "/v1/document-types/supplier_invoice/examples"
    unshown = documents.patch(field, json={"value": "INV-CHECKED"})
    untaught = [e for e in data(documents.get(url)) or [] if e["extractionId"] == first["id"]]
    printed = str(first["fields"]["invoice_no"]["value"])
    fixed = documents.patch(field, json={"value": printed})
    listed = data(documents.get(url)) or []
    mine = [e for e in listed if e["extractionId"] == first["id"]]
    gone = documents.delete(f"{url}/{mine[0]['id']}") if mine else None
    after = [e for e in data(documents.get(url)) or [] if e["extractionId"] == first["id"]]
    check(
        "7 a correction becomes an example of its type with the line it was printed on, and removed it is gone",
        unshown.status_code == 200
        and untaught == []
        and fixed.status_code == 200
        and len(mine) == 1
        and (mine[0]["field"], mine[0]["value"]) == ("invoice_no", printed)
        and bool(mine[0]["line"])
        and gone is not None
        and gone.status_code == 204
        and after == [],
        {
            "untaught": untaught,
            "fixed": fixed.status_code,
            "listed": mine,
            "removed": gone.status_code if gone else None,
            "after": after,
        },
    )


def page_images(
    people: httpx.Client,
    model_admin: httpx.Client,
    files: httpx.Client,
    documents: httpx.Client,
    kinds: dict[str, Any],
) -> None:
    """Check 6 (c-295): a scan's page goes to the model only when its type version, the team's pageImages policy and the
    model alias all allow it, and every call that carried one is on the read and in models-service's call log."""
    type_id, (definition, folder) = next((k, v) for k, v in kinds.items() if v[1].name == SCAN[0])
    fid = upload(files, folder, SCAN[1])

    def scan_read() -> dict[str, Any]:
        return read(documents, fid, {"documentTypeId": type_id, "ocr": True})

    def team(email: str, on: bool) -> int:
        session = signed_in(people, email)
        put = people.put("/v1/policies/pageImages", json={"value": on}, headers=bearer(session, "team_ops"))
        return put.status_code

    reads: dict[str, Any] = {}
    reads["type off"] = scan_read()
    version = {"fields": definition["fields"], "pageImages": True}
    turned = documents.post(f"/v1/document-types/{type_id}/versions", json=version)
    reads["team off"] = scan_read()
    refused_admin = team("p.shah@northfieldbank.com", True)
    allowed_admin = team("w.kamau@northfieldbank.com", True)
    reads["alias off"] = scan_read()
    alias = {"name": "extract", "providerId": "openai-local", "modelId": "default"}
    alias["clearedSensitivity"] = "confidential"
    cleared = model_admin.post("/v1/models/aliases", json={**alias, "images": True}, headers=MODELS_ADMIN).status_code
    reads["all on"] = scan_read()
    team("w.kamau@northfieldbank.com", False)
    reads["team off again"] = scan_read()
    shown = reads["all on"].get("imageCalls") or []
    logged = data(model_admin.get("/v1/models/calls", params={"alias": "extract"}, headers=MODELS_ADMIN))["items"]
    with_images = [c for c in logged if c["runId"] == reads["all on"].get("id") and c["images"]]
    gated = {k: bool(r.get("imageCalls")) for k, r in reads.items()}
    check(
        "6 a scan's page goes to the model only when its type, the team's policy and the alias allow it, and every "
        "image call is on the read and in the call log",
        turned.status_code == 201
        and (refused_admin, allowed_admin, cleared) == (403, 200, 201)
        and gated == {k: k == "all on" for k in reads}
        and all(r.get("status") == "done" for r in reads.values())
        and "not cleared for page images" in str(reads["alias off"].get("imageRefused"))
        and shown[:1] == [{"step": "extract", "pages": [1], "images": 1, "alias": "extract"}]
        and len(with_images) == len(shown),
        {
            "turned": turned.status_code,
            "policy": (refused_admin, allowed_admin),
            "alias": cleared,
            "gated": gated,
            "refused": reads["alias off"].get("imageRefused"),
            "shown": shown,
            "logged": len(with_images),
        },
    )


if __name__ == "__main__":
    main()
