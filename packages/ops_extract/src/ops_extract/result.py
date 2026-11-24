"""The scored answer to an extraction: every field checked (checks.score) and whether a person must look, in the shape
workflows read (`fields`, `needsReview`, `floor`, `schema`, and `records`/`count` for several records)."""

from __future__ import annotations

from typing import Literal

from ops_extract.checks import score
from ops_extract.shapes import FieldDefinition
from ops_service_kit.http import Json, JsonList, JsonValue
from ops_service_kit.narrow import an_object, entries, json_object

Status = Literal["ok", "review"]
# Every outcome a finished read can carry: a scored Status, a file with no text, a detected kind no type fits, or a
# model reply with no answer (cut off, empty, declined or filtered), which leaves every field not read.
Outcome = Literal["ok", "review", "unreadable", "unknown", "incomplete"]


def asked(fields: list[FieldDefinition]) -> list[Json]:
    """The fields asked for, so a person checking the read sees each one's label and type, not only its key. A field
    the document type marks `keyField` keeps the mark, so the check asks for it on its own."""
    out: list[Json] = []
    for f in fields:
        one: Json = {
            "key": f["key"],
            "label": str(f.get("label") or f["key"]),
            "type": f.get("type"),
            "required": bool(f.get("required")),
        }
        if f.get("keyField") is True:
            one["keyField"] = True
        out.append(one)
    return out


def _flagged(results: Json) -> JsonList:
    return [k for k, r in results.items() if json_object(r).get("needsReview")]


def scored(
    fields: list[FieldDefinition],
    answer: JsonValue,
    texts: dict[int, str],
    ocr_pages: set[int],
    *,
    file_id: str,
    many: bool,
    review_below: float | None,
    floor: float,
    word_confidence: dict[int, dict[str, float]] | None = None,
) -> tuple[Status, Json]:
    """`answer` has passed the schema; `review` when any field (or record) needs a person."""

    def one(found: Json) -> Json:
        results: Json = {}
        for f in fields:
            key = f["key"]
            said = found.get(key)
            results[key] = score(
                f,
                an_object(said, f"the answer for {key}") if said else None,
                texts,
                ocr_pages,
                file_id=file_id,
                schema_below=review_below,
                floor=floor,
                word_confidence=word_confidence,
            )
        return results

    if many:
        records: JsonList = []
        for found in entries(an_object(answer, "the answer")["records"]):
            results = one(an_object(found, "a record"))
            values: Json = {k: json_object(r).get("value") for k, r in results.items()}
            records.append({"values": values, "fields": results, "needsReview": _flagged(results)})
        review_many: JsonList = [i for i, r in enumerate(records) if json_object(r).get("needsReview")]
        out: Json = {"fileId": file_id, "records": records, "count": len(records), "needsReview": review_many}
        out["floor"] = floor
        out["schema"] = [*asked(fields)]
        return ("review" if review_many else "ok"), out
    results = one(an_object(answer, "the answer"))
    review = _flagged(results)
    single: Json = {"fileId": file_id, "fields": results, "needsReview": review, "floor": floor}
    single["schema"] = [*asked(fields)]
    return ("review" if review else "ok"), single
