"""The scored answer to an extraction: every field checked (checks.score) and whether a person must look, in the shape
workflows read (`fields`, `needsReview`, `floor`, `schema`, and `records`/`count` for several records)."""

from __future__ import annotations

from typing import Any, Literal, cast

from ops_extract.checks import score

Status = Literal["ok", "review"]


def asked(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The fields asked for, so a person checking the read sees each one's label and type, not only its key. A field
    the document type marks `keyField` keeps the mark, so the check asks for it on its own."""
    return [
        {
            "key": str(f["key"]),
            "label": str(f.get("label") or f["key"]),
            "type": f.get("type"),
            "required": bool(f.get("required")),
        }
        | ({"keyField": True} if f.get("keyField") is True else {})
        for f in fields
    ]


def scored(
    fields: list[dict[str, Any]],
    answer: Any,
    texts: dict[int, str],
    ocr_pages: set[int],
    *,
    file_id: str,
    many: bool,
    review_below: float | None,
    floor: float,
    word_confidence: dict[int, dict[str, float]] | None = None,
) -> tuple[Status, dict[str, Any]]:
    """`answer` has passed the schema; `review` when any field (or record) needs a person."""

    def one(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(f["key"]): score(
                f,
                cast(dict[str, Any] | None, found.get(str(f["key"]))),
                texts,
                ocr_pages,
                file_id=file_id,
                schema_below=review_below,
                floor=floor,
                word_confidence=word_confidence,
            )
            for f in fields
        }

    if many:
        records: list[dict[str, Any]] = []
        for found in cast(list[dict[str, Any]], cast(dict[str, Any], answer)["records"]):
            results = one(found)
            records.append(
                {
                    "values": {k: r["value"] for k, r in results.items()},
                    "fields": results,
                    "needsReview": [k for k, r in results.items() if r["needsReview"]],
                }
            )
        review_many = [i for i, r in enumerate(records) if r["needsReview"]]
        out = {"fileId": file_id, "records": records, "count": len(records), "needsReview": review_many, "floor": floor}
        return ("review" if review_many else "ok"), out | {"schema": asked(fields)}
    results = one(cast(dict[str, Any], answer))
    review = [k for k, r in results.items() if r["needsReview"]]
    single = {"fileId": file_id, "fields": results, "needsReview": review, "floor": floor, "schema": asked(fields)}
    return ("review" if review else "ok"), single
