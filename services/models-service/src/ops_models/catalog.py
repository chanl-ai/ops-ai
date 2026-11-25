"""The model catalog: what each catalogued model can do and which knobs it takes, from the committed snapshot
(`catalog/models.json`, written by scripts/sync_catalog.py from models.dev and LiteLLM) and the knob table
(`catalog/knobs.json`). Read once at start-up and never from the network, so a release serves the catalog it was cut
with.

One rule for knobs, applied to every completion in `fit`: a knob the alias's model does not list is left out of the
call, a number is clamped to the model's range, and a choice the model does not list is left out. A model the catalog
does not hold gets what the caller sent, as nothing is known about its limits. agents-service checks a saved agent's
settings against `knob_schema` and refuses one that breaks it, so a builder sees the problem; the gateway still fits
each call, because an alias can later point at a model with other limits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ops_service_kit.http import Json

CATALOG_DIR = Path(__file__).resolve().parents[2] / "catalog"
# Schema keywords a knob's range carries into the knobs reply.
_RANGE = ("minimum", "maximum", "default", "enum", "x-minimum-on")


class Catalog:
    def __init__(self, models: dict[str, Any], knobs: dict[str, Any]) -> None:
        self.models: dict[str, dict[str, dict[str, Any]]] = models["providers"]
        self.knobs: dict[str, dict[str, Any]] = knobs["knobs"]
        self.providers: dict[str, dict[str, Any]] = knobs["providers"]
        self.uncatalogued: list[str] = knobs["uncatalogued"]["takes"]
        self.synced_at = str(models.get("syncedAt") or "")

    @classmethod
    def load(cls, folder: Path = CATALOG_DIR) -> Catalog:
        return cls(json.loads((folder / "models.json").read_text()), json.loads((folder / "knobs.json").read_text()))

    def model(self, catalog_id: str | None, model_id: str) -> dict[str, Any] | None:
        return (self.models.get(catalog_id) or {}).get(model_id) if catalog_id else None

    def listed(self, catalog_id: str | None) -> list[tuple[str, dict[str, Any]]]:
        return sorted((self.models.get(catalog_id) or {}).items()) if catalog_id else []

    def knob_schema(self, catalog_id: str | None, model_id: str) -> Json:
        """A JSON Schema object of the knobs the model takes, each with its title, description, range and catalog
        default; for a model the catalog does not hold, the common knobs with no range or default."""
        found = self.model(catalog_id, model_id)
        ranges: dict[str, dict[str, Any]] = found["knobs"] if found else {n: {} for n in self.uncatalogued}
        properties: Json = {}
        for name, held in ranges.items():
            knob = self.knobs[name]
            schema: dict[str, Any] = {k: knob[k] for k in ("type", "title", "description")}
            schema |= {k: held[k] for k in _RANGE if k in held}
            properties[name] = schema
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "x-catalogued": found is not None,
        }

    def fit(self, body: Json, catalog_id: str | None, model_id: str) -> Json:
        """`body` as the provider receives it under the knob rule in this module's docstring."""
        found = self.model(catalog_id, model_id)
        if found is None:
            return body
        out: dict[str, Any] = dict(body)
        ranges: dict[str, dict[str, Any]] = found["knobs"]
        overrides = self.providers.get(str(catalog_id)) or {}
        for name, knob in self.knobs.items():
            for wire in [knob["wire"], *knob.get("alsoWire", [])]:
                value = _read(out, wire)
                if value is None:
                    continue
                held = ranges.get(name)
                kept = None if held is None else _fitted(knob["type"], value, held, name)
                _drop(out, wire)
                if kept is not None:
                    override: dict[str, Any] = overrides.get(name) or {}
                    _write(out, str(override.get("wire") or wire), kept)
        return out


def _fitted(kind: str, value: Any, held: dict[str, Any], name: str) -> Any:
    if kind == "string":
        allowed = held.get("enum")
        return value if isinstance(value, str) and (allowed is None or value in allowed) else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if name == "thinking_budget" and value <= 0:
        return None
    lo, hi = held.get("minimum"), held.get("maximum")
    fitted = max(value, lo) if lo is not None else value
    fitted = min(fitted, hi) if hi is not None else fitted
    if (on := held.get("x-minimum-on")) is not None:
        fitted = max(fitted, on)
    return int(fitted) if kind == "integer" else float(fitted)


def _read(body: dict[str, Any], wire: str) -> Any:
    node: Any = body
    for part in wire.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]  # pyright: ignore[reportUnknownVariableType]
    return node  # pyright: ignore[reportUnknownVariableType]


def _drop(body: dict[str, Any], wire: str) -> None:
    *path, last = wire.split(".")
    if not path:
        body.pop(last, None)
        return
    # A nested knob's parent object (`thinking`) goes with it: `{type: enabled}` alone would switch thinking on.
    body.pop(path[0], None)


def _write(body: dict[str, Any], wire: str, value: Any) -> None:
    *path, last = wire.split(".")
    node = body
    for part in path:
        node = node.setdefault(part, {})
    if wire == "thinking.budget_tokens":
        node["type"] = "enabled"
    node[last] = value
