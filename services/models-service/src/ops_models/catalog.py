"""The model catalog: what each catalogued model can do and which knobs it takes, from the committed snapshot
(`catalog/models.json`, written by scripts/sync_catalog.py from models.dev and LiteLLM) and the knob table
(`catalog/knobs.json`). Read once at start-up and never from the network, so a release serves the catalog it was cut
with.

A caller names a knob by its name (`thinking_budget`) or by the request field it reaches the provider as
(`thinking.budget_tokens`); which field that is, what it sets alongside and when it is off are the knob table's.

One rule for knobs, applied to every completion in `fit`: a knob the alias's model does not list is left out of the
call, a number is clamped to the model's range, and a choice the model does not list is left out. A model the catalog
does not hold gets every knob as sent, under its request field, as nothing is known about its limits. agents-service
checks a saved agent's settings against `knob_schema` and refuses one that breaks it, so a builder sees the problem;
the gateway still fits each call, because an alias can later point at a model with other limits."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import Field

from ops_service_kit.http import In, Json, JsonValue
from ops_service_kit.names import Name, Name80

CATALOG_DIR = Path(__file__).resolve().parents[2] / "catalog"

type Scalar = float | int | str


class KnobDef(In):
    type: Literal["number", "integer", "string"]
    title: Name80
    description: str
    # The request field the knob reaches the provider as, dotted for a nested one (`thinking.budget_tokens`).
    wire: str
    also_wire: list[str] = Field(default_factory=list[str])
    # Fields set beside it when it is sent under its own `wire` (`thinking.type: enabled`).
    with_: dict[str, str] = Field(default_factory=dict[str, str], alias="with")
    # At or below this the knob is off and is not sent (a thinking budget of 0).
    off_at: float | None = None


class KnobRange(In):
    minimum: float | None = None
    maximum: float | None = None
    default: Scalar | None = None
    enum: list[str] | None = None
    # Above `off_at`, the smallest value the provider takes (Anthropic's 1,024-token thinking budget).
    x_minimum_on: float | None = Field(default=None, alias="x-minimum-on")
    # This provider takes the knob under another field (Gemini's thinking budget).
    wire: str | None = None


class CatalogModel(In):
    name: Name
    context: int | None = None
    output: int | None = None
    reasoning: bool = False
    tool_call: bool = False
    images: bool = False
    input_per_million: float | None = None
    output_per_million: float | None = None
    knobs: dict[str, KnobRange] = Field(default_factory=dict[str, KnobRange])


class ProviderKnobs(In):
    takes: list[str]
    ranges: dict[str, KnobRange] = Field(default_factory=dict[str, KnobRange])


class Uncatalogued(In):
    takes: list[str]


class CatalogFile(In):
    about: str = ""
    sources: dict[str, str] = Field(default_factory=dict[str, str])
    synced_at: str = ""
    providers: dict[str, dict[str, CatalogModel]]


class KnobsFile(In):
    about: str = ""
    knobs: dict[str, KnobDef]
    providers: dict[str, ProviderKnobs]
    uncatalogued: Uncatalogued


# Schema keywords a knob's range carries into the knobs reply.
_RANGE = ("minimum", "maximum", "default", "enum", "x-minimum-on")


class Catalog:
    def __init__(self, models: CatalogFile, knobs: KnobsFile) -> None:
        self.models = models.providers
        self.knobs = knobs.knobs
        self.providers = knobs.providers
        self.uncatalogued = knobs.uncatalogued.takes
        self.synced_at = models.synced_at

    @classmethod
    def load(cls, folder: Path = CATALOG_DIR) -> Catalog:
        models = CatalogFile.model_validate_json((folder / "models.json").read_text())
        return cls(models, KnobsFile.model_validate_json((folder / "knobs.json").read_text()))

    def model(self, catalog_id: str | None, model_id: str) -> CatalogModel | None:
        return (self.models.get(catalog_id) or {}).get(model_id) if catalog_id else None

    def listed(self, catalog_id: str | None) -> list[tuple[str, CatalogModel]]:
        return sorted((self.models.get(catalog_id) or {}).items()) if catalog_id else []

    def knob_schema(self, catalog_id: str | None, model_id: str) -> Json:
        """A JSON Schema object of the knobs the model takes, each with its title, description, range and catalog
        default; for a model the catalog does not hold, the common knobs with no range or default."""
        found = self.model(catalog_id, model_id)
        ranges = found.knobs if found else {n: KnobRange() for n in self.uncatalogued}
        properties: Json = {}
        for name, held in ranges.items():
            knob = self.knobs[name]
            shown: Json = held.model_dump(by_alias=True, exclude_none=True)
            schema: Json = {"type": knob.type, "title": knob.title, "description": knob.description}
            properties[name] = schema | {k: v for k, v in shown.items() if k in _RANGE}
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "x-catalogued": found is not None,
        }

    def fit(self, body: Json, catalog_id: str | None, model_id: str) -> Json:
        """`body` as the provider receives it under the knob rule in this module's docstring."""
        found = self.model(catalog_id, model_id)
        held: Mapping[str, KnobRange] = found.knobs if found else {n: KnobRange() for n in self.knobs}
        overrides = self.providers[catalog_id].ranges if found and catalog_id in self.providers else {}
        out: Json = dict(body)
        for name, knob in self.knobs.items():
            for path in dict.fromkeys([name, knob.wire, *knob.also_wire]):
                value = _read(out, path)
                if value is None:
                    continue
                _drop(out, path)
                rng = held.get(name)
                kept = None if rng is None else _fitted(knob, value, rng, clamp=found is not None)
                if kept is None:
                    continue
                own = path if path != name else knob.wire
                target = (overrides[name].wire if name in overrides else None) or own
                _write(out, target, kept)
                if target == knob.wire:
                    for field, set_to in knob.with_.items():
                        _write(out, field, set_to)
        return out


def _fitted(knob: KnobDef, value: JsonValue, held: KnobRange, *, clamp: bool) -> Scalar | None:
    if knob.type == "string":
        if not isinstance(value, str):
            return None
        return value if not clamp or held.enum is None or value in held.enum else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if knob.off_at is not None and value <= knob.off_at:
        return None
    fitted: float = value
    if clamp:
        fitted = max(fitted, held.minimum) if held.minimum is not None else fitted
        fitted = min(fitted, held.maximum) if held.maximum is not None else fitted
        fitted = max(fitted, held.x_minimum_on) if held.x_minimum_on is not None else fitted
    return int(fitted) if knob.type == "integer" else float(fitted)


def _read(body: Json, path: str) -> JsonValue:
    node: JsonValue = body
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _drop(body: Json, path: str) -> None:
    # A nested knob's parent object (`thinking`) goes with it: `{type: enabled}` alone would switch thinking on.
    body.pop(path.split(".", maxsplit=1)[0], None)


def _write(body: Json, path: str, value: Scalar) -> None:
    *parents, last = path.split(".")
    node = body
    for part in parents:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[last] = value
