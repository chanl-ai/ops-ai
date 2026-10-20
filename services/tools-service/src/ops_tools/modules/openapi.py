"""OpenAPI 3.0 and 3.1 documents as discovered operations.

Each path and method becomes one operation, named by its operationId in snake case, or `<method>_<path>` when it has
none. Path and query parameters and the JSON request body's top-level properties merge into one input list. An API
key or bearer scheme in a header becomes a `{{NAME}}` secret reference, resolved by the executor at call time.
Access is pre-set from the method: GET is a read, everything else a write, and the builder confirms each one on
import (HEAD is skipped: it answers no body). Each operation's example response becomes its stub. A document whose
operations carry no auth header is flagged (`noAuth`, and a warning), since its calls would go out with no
credentials.
"""

from __future__ import annotations

import re
from typing import Any, cast
from urllib.parse import urljoin, urlsplit

METHODS = ("get", "post", "put", "patch", "delete")
# HEAD answers no body, so it cannot be a tool; a document listing one is told so in the warnings.
SKIPPED = ("head",)
FIELD_TYPES = {"string", "number", "integer", "boolean", "object", "array"}
NAME = re.compile(r"^[a-z][a-z0-9_]{2,}$")


class SpecError(ValueError):
    """The document is not an OpenAPI 3 document this converter can read."""


def snake(value: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s if s[:1].isalpha() else f"op_{s}"


def kebab(value: str) -> str:
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", value.lower()))


def _deref(spec: dict[str, Any], node: Any, depth: int = 0) -> dict[str, Any]:
    """Follows local `#/components/...` references; an external or deep reference resolves to an empty schema."""
    while isinstance(node, dict) and "$ref" in node and depth < 8:
        ref = cast(dict[str, Any], node)["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return {}
        target: Any = spec
        for part in ref[2:].split("/"):
            target = cast(dict[str, Any], target).get(part, {}) if isinstance(target, dict) else {}
        node, depth = target, depth + 1
    return cast(dict[str, Any], node) if isinstance(node, dict) else {}


def _field(spec: dict[str, Any], name: str, schema: Any, *, required: bool, description: str | None) -> dict[str, Any]:
    s = _deref(spec, schema)
    kind = s.get("type")
    if isinstance(kind, list):  # 3.1 allows ["string", "null"]
        kind = next((k for k in cast(list[Any], kind) if k != "null"), "string")
    field: dict[str, Any] = {"name": name, "type": kind if kind in FIELD_TYPES else "string", "required": required}
    text = description or s.get("description")
    if text:
        field["description"] = str(text)
    if s.get("format"):
        field["format"] = str(s["format"])
    if isinstance(s.get("enum"), list):
        field["enum"] = [str(v) for v in cast(list[Any], s["enum"])]
    if s.get("example") is not None:
        field["example"] = str(s["example"])
    return field


def _credentials(spec: dict[str, Any], op: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, str]]:
    """The secret references the operation's first satisfiable security requirement needs: headers, and query
    parameters (an API key `in: query`), each reading the secret named after its scheme."""
    schemes: dict[str, Any] = _deref(spec, spec.get("components", {})).get("securitySchemes", {}) or {}
    wanted: Any = op.get("security", spec.get("security")) or []
    headers: list[dict[str, str]] = []
    query: dict[str, str] = {}
    for requirement in cast(list[Any], wanted):
        if not isinstance(requirement, dict):
            continue
        for scheme_name in cast(dict[str, Any], requirement):
            scheme = _deref(spec, schemes.get(scheme_name))
            secret = snake(scheme_name).upper()
            if scheme.get("type") == "apiKey" and scheme.get("in") == "header" and scheme.get("name"):
                headers.append({"key": str(scheme["name"]), "value": f"{{{{{secret}}}}}"})
            elif scheme.get("type") == "apiKey" and scheme.get("in") == "query" and scheme.get("name"):
                query[str(scheme["name"])] = f"{{{{{secret}}}}}"
            elif scheme.get("type") == "http" and str(scheme.get("scheme", "")).lower() == "bearer":
                headers.append({"key": "Authorization", "value": f"Bearer {{{{{secret}}}}}"})
        if headers or query:
            break
    return headers, query


def _example_response(spec: dict[str, Any], op: dict[str, Any]) -> Any:
    """The JSON example of the operation's first success response: the media type's `example`, else its first
    `examples` value, else the schema's `example`; None when the document gives none."""
    responses: dict[str, Any] = op.get("responses") or {}
    for code in sorted(c for c in responses if str(c).startswith("2")):
        media = _deref(
            spec, cast(dict[str, Any], _deref(spec, responses[code]).get("content") or {}).get("application/json")
        )
        if "example" in media:
            return media["example"]
        examples: dict[str, Any] = media.get("examples") or {}
        for example in examples.values():
            value = _deref(spec, example)
            if "value" in value:
                return value["value"]
        schema = _deref(spec, media.get("schema"))
        if "example" in schema:
            return schema["example"]
    return None


def _resolved(spec: dict[str, Any], node: Any, depth: int = 0) -> Any:
    """A schema with its local references followed all the way down, to a depth of 8."""
    if depth > 8:
        return {}
    if isinstance(node, dict):
        found = _deref(spec, node)
        return {k: _resolved(spec, v, depth + 1) for k, v in found.items()}
    if isinstance(node, list):
        return [_resolved(spec, v, depth + 1) for v in cast(list[Any], node)]
    return node


def _response_schema(spec: dict[str, Any], op: dict[str, Any]) -> dict[str, Any] | None:
    """The JSON Schema of the operation's first success response, references resolved; None when it gives none."""
    responses: dict[str, Any] = op.get("responses") or {}
    for code in sorted(c for c in responses if str(c).startswith("2")):
        media = _deref(
            spec, cast(dict[str, Any], _deref(spec, responses[code]).get("content") or {}).get("application/json")
        )
        schema = _resolved(spec, media.get("schema"))
        if schema:
            return cast(dict[str, Any], schema)
    return None


OUTPUT_SHAPES = ("rows", "series", "record", "metric")


def _declared_shape(spec: dict[str, Any], op: dict[str, Any]) -> str | None:
    """`x-ops-shape` on the operation's first success response, or on its JSON media type."""
    responses: dict[str, Any] = op.get("responses") or {}
    for code in sorted(c for c in responses if str(c).startswith("2")):
        response = _deref(spec, responses[code])
        media = _deref(spec, cast(dict[str, Any], response.get("content") or {}).get("application/json"))
        found = response.get("x-ops-shape") or media.get("x-ops-shape")
        if found is not None:
            return str(found)
    return None


def discover(spec: Any, spec_url: str) -> dict[str, Any]:
    """The console's DiscoveryResult for `spec`, with each operation's headers and method kept for import."""
    if not isinstance(spec, dict) or not str(cast(dict[str, Any], spec).get("openapi", "")).startswith("3."):
        raise SpecError("This is not an OpenAPI 3 document.")
    doc = cast(dict[str, Any], spec)
    info: dict[str, Any] = doc.get("info") or {}
    servers: list[Any] = doc.get("servers") or [{"url": "/"}]
    server = str(cast(dict[str, Any], servers[0]).get("url", "/")) if isinstance(servers[0], dict) else "/"
    endpoint = urljoin(spec_url, server).rstrip("/")
    title = str(info.get("title") or urlsplit(spec_url).hostname or "api")
    warnings: list[str] = []
    operations: list[dict[str, Any]] = []
    seen: set[str] = set()
    paths: dict[str, Any] = doc.get("paths") or {}
    for path, item_raw in paths.items():
        item = _deref(doc, item_raw)
        shared: list[Any] = item.get("parameters") or []
        for method in SKIPPED:
            if method in item:
                warnings.append(f"{method.upper()} {path} was skipped: it answers no body, so it cannot be a tool.")
        for method in METHODS:
            if method not in item:
                continue
            op = _deref(doc, item[method])
            name = snake(str(op["operationId"])) if op.get("operationId") else snake(f"{method}_{path}")
            if not NAME.match(name) or name in seen:
                warnings.append(f"{method.upper()} {path} was skipped: no usable unique name.")
                continue
            seen.add(name)
            fields: dict[str, dict[str, Any]] = {}
            headers, keyed = _credentials(doc, op)
            params: list[Any] = [*shared, *(op.get("parameters") or [])]
            for raw in params:
                p = _deref(doc, raw)
                # A query parameter that carries the API key is the secret's, never an input the agent fills.
                if p.get("in") == "query" and p.get("name") in keyed:
                    continue
                if p.get("in") in ("path", "query") and p.get("name"):
                    required = bool(p.get("required")) or p.get("in") == "path"
                    fields[str(p["name"])] = _field(
                        doc, str(p["name"]), p.get("schema"), required=required, description=p.get("description")
                    )
            body = _deref(doc, op.get("requestBody"))
            content: dict[str, Any] = body.get("content") or {}
            if content and "application/json" not in content:
                warnings.append(
                    f"{name} was skipped: it takes a {next(iter(content))} body, which import does not map."
                )
                continue
            schema = _deref(doc, cast(dict[str, Any], content.get("application/json") or {}).get("schema"))
            required_props = set(cast(list[str], schema.get("required") or []))
            for prop, prop_schema in cast(dict[str, Any], schema.get("properties") or {}).items():
                fields.setdefault(
                    prop, _field(doc, prop, prop_schema, required=prop in required_props, description=None)
                )
            segments = [s for s in path.split("/") if s and not s.startswith("{")]
            example = _example_response(doc, op)
            response = _response_schema(doc, op)
            shape = _declared_shape(doc, op)
            if shape is not None and shape not in OUTPUT_SHAPES:
                warnings.append(f"{name}'s x-ops-shape {shape!r} is not one of {', '.join(OUTPUT_SHAPES)}; ignored.")
                shape = None
            operations.append(
                {
                    "name": name,
                    "description": str(op.get("summary") or op.get("description") or name),
                    "access": "read" if method == "get" else "write",
                    "method": method.upper(),
                    "path": path + ("?" + "&".join(f"{k}={v}" for k, v in keyed.items()) if keyed else ""),
                    "group": segments[0] if segments else "operations",
                    "input": list(fields.values()),
                    "headers": headers,
                    **({"stub": example} if example is not None else {}),
                    **({"output_shape": shape} if shape is not None else {}),
                    **({"response_schema": response} if response is not None else {}),
                }
            )
    if not operations:
        raise SpecError("The document lists no operations.")
    no_auth = not any(o["headers"] or "{{" in o["path"] for o in operations)
    if no_auth:
        warnings.append(
            "This document declares no API key or bearer security scheme, so its calls would go out with no "
            "credentials. Add an auth header (for example Authorization: Bearer {{SECRET}}) to each operation after "
            "import."
        )
    return {
        "noAuth": no_auth,
        "type": "openapi",
        "system": title,
        "suggestedName": kebab(title),
        "version": str(info.get("version") or "1.0.0"),
        "endpoint": endpoint,
        "operations": operations,
        "warnings": warnings,
    }
