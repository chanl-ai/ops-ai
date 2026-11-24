"""Refuses a list route that answers every row or cannot be searched, read from each service's committed openapi.json.

A list route is a GET whose 200 reply carries rows: an array in `data`, or an object holding one. Each must take the
shared list query (`ops_service_kit.listing.ListQuery`: `search`, `page`, `pageSize`, `sortBy`, `sortOrder`, `ids`,
filters) and answer a `ListResult`, or be an `/options` route answering an `OptionsPage` (`search`, `cursor`,
`limit`). A picker or table over a route that answers every row can only filter what it loaded, so a team with
thousands of rows cannot find most of them (docs/architecture/api.md, "Lists and errors").

A route that is right to answer every row (a fixed set such as node types, one record's few versions) is named in
list-routes-allowlist.txt with its reason. The allowlist only shrinks: a route on it that now pages is a finding until
it is taken off.

  uv run python scripts/check_list_routes.py              # exit 1 on a finding
  uv run python scripts/check_list_routes.py --self-test  # plants a route that answers every row and one that pages
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "list-routes-allowlist.txt"
# Keys inside a reply object that hold its rows.
ROW_KEYS = ("items", "data", "results", "operations", "templates", "chunks", "rows")

Doc = dict[str, Any]


def _resolve(doc: Doc, schema: Any, depth: int = 0) -> Doc:
    while isinstance(schema, dict) and "$ref" in schema and depth < 10:
        ref = str(cast(Doc, schema)["$ref"])
        schema = doc["components"]["schemas"][ref.rsplit("/", 1)[-1]]
        depth += 1
    return cast(Doc, schema) if isinstance(schema, dict) else {}


def shape(doc: Doc, op: Doc) -> str | None:
    """`paged`, `options` or `every` for a reply that carries rows; None for a reply that does not."""
    try:
        reply = op["responses"]["200"]["content"]["application/json"]["schema"]
    except KeyError:
        return None
    data = _resolve(doc, _resolve(doc, reply).get("properties", {}).get("data"))
    if data.get("type") == "array":
        return "every"
    props = data.get("properties", {})
    if "pagination" in props:
        return "paged"
    if "nextCursor" in props:
        return "options"
    if any(_resolve(doc, props[k]).get("type") == "array" for k in ROW_KEYS if k in props):
        return "every"
    return None


def findings(docs: dict[str, Doc], allowed: dict[str, str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for service, doc in sorted(docs.items()):
        for path, ops in doc.get("paths", {}).items():
            found = cast(Doc, ops).get("get")
            if not isinstance(found, dict):
                continue
            op = cast(Doc, found)
            kind = shape(doc, op)
            if kind is None:
                continue
            route = f"{service} GET {path}"
            given = cast(list[Doc], op.get("parameters", []))
            params = {str(p.get("name")) for p in given if p.get("in") == "query"}
            ok = (kind == "paged" and {"search", "page", "pageSize"} <= params) or (
                kind == "options" and {"search", "cursor", "limit"} <= params
            )
            if ok:
                if route in allowed:
                    out.append(f"{route}: pages and searches now; take it off list-routes-allowlist.txt")
                continue
            seen.add(route)
            if route not in allowed:
                what = "answers every row" if kind == "every" else "pages without search, page and size"
                out.append(f"{route}: {what}; take ListQuery and answer a page (or list it with a reason)")
    out += [f"{r}: on list-routes-allowlist.txt but no such list route" for r in sorted(set(allowed) - seen)]
    return out


def read_allowlist(text: str) -> dict[str, str]:
    """`<service> GET <path>  # <reason>` per line; a line without a reason is refused."""
    out: dict[str, str] = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        route, _, reason = line.partition("#")
        if not reason.strip():
            raise SystemExit(f"list-routes-allowlist.txt:{n}: give the reason after #")
        out[route.strip()] = reason.strip()
    return out


def load() -> dict[str, Doc]:
    return {p.parent.name: json.loads(p.read_text()) for p in sorted(ROOT.glob("services/*/openapi.json"))}


def self_test() -> None:
    def reply(data: Doc) -> Doc:
        return {"200": {"content": {"application/json": {"schema": {"properties": {"data": data}}}}}}

    page = {"properties": {"data": {"type": "array"}, "pagination": {}}}
    q = [{"name": n, "in": "query"} for n in ("search", "page", "pageSize")]
    doc: Doc = {
        "components": {"schemas": {}},
        "paths": {
            "/v1/every": {"get": {"responses": reply({"type": "array"})}},
            "/v1/wrapped": {"get": {"responses": reply({"properties": {"operations": {"type": "array"}}})}},
            "/v1/paged": {"get": {"responses": reply(page), "parameters": q}},
            "/v1/unsearched": {"get": {"responses": reply(page), "parameters": q[1:]}},
            "/v1/one": {"get": {"responses": reply({"properties": {"id": {"type": "string"}}})}},
        },
    }
    found = findings({"x": doc}, {})
    want = {"x GET /v1/every", "x GET /v1/wrapped", "x GET /v1/unsearched"}
    assert {f.split(":")[0] for f in found} == want, found
    assert not findings({"x": doc}, dict.fromkeys(want, "r")), "an allowlisted route must pass"
    assert findings({"x": doc}, {**dict.fromkeys(want, "r"), "x GET /v1/paged": "r"}), "a paged route left on must fail"
    print("PASS a route answering every row, one wrapping its rows and one without search are each reported")


def main() -> int:
    if "--self-test" in sys.argv:
        self_test()
        return 0
    found = findings(load(), read_allowlist(ALLOWLIST.read_text()))
    for f in found:
        print(f)
    print(f"check_list_routes: {len(found)} findings")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
