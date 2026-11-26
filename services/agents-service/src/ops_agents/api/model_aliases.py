"""Which model aliases an agent may name: models-service's chat aliases when it is configured, else only the
runtime's own alias. GET /v1/model-aliases lists them for the agent picker, and a publish request is refused when its
agent names an alias outside the same set."""

from __future__ import annotations

from collections.abc import Mapping
from typing import NotRequired, Protocol, TypedDict, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_identity.client import segment
from ops_service_kit.errors import ApiError, Unprocessable
from ops_service_kit.http import Json


class ServingAlias(TypedDict):
    """The fields of models-service's alias row this reads."""

    name: str
    kind: str
    clearedSensitivity: NotRequired[str | None]
    inputPerMillion: NotRequired[str | None]
    outputPerMillion: NotRequired[str | None]


class Paging(TypedDict):
    hasNext: bool


class AliasPage(TypedDict):
    """One page of `GET /v1/models/aliases` (the shared list contract), as far as this reads it."""

    data: list[ServingAlias]
    pagination: Paging


class ModelsUnavailable(ApiError):
    status = 503
    code = "models_unavailable"


class ModelAliases(Protocol):
    async def chat_models(self) -> list[Json]:
        """Wire rows, `{name, kind: "chat"}` plus clearance and prices when models-service knows them."""
        ...

    async def knobs(self, alias: str) -> Json:
        """models-service's knobs reply for the alias: `knobs` is a JSON Schema object of only the settings its model
        takes. Unprocessable `unknown_model_alias` when models-service has no such alias."""
        ...


# Without models-service nothing is known about the runtime alias's model, so no setting can be checked or saved.
NO_KNOBS: Json = {"type": "object", "additionalProperties": False, "properties": {}, "x-catalogued": False}


async def chat_aliases(aliases: ModelAliases) -> set[str]:
    return {str(a["name"]) for a in await aliases.chat_models()}


class StaticModelAliases:
    def __init__(self, names: set[str]) -> None:
        self.names = names

    async def chat_models(self) -> list[Json]:
        return [{"name": n, "kind": "chat"} for n in sorted(self.names)]

    async def knobs(self, alias: str) -> Json:
        if alias not in self.names:
            raise _unknown(alias, self.names)
        return {"alias": alias, "version": 1, "modelId": alias, "catalogued": False, "knobs": NO_KNOBS}


def _unknown(alias: str, known: set[str]) -> Unprocessable:
    return Unprocessable(
        f"Model alias {alias} is not one models-service serves. Aliases: {', '.join(sorted(known))}.",
        code="unknown_model_alias",
    )


class HttpModelAliases:
    """GET /v1/models/aliases on models-service through ServiceClient; chat aliases only. With no client (no service
    signing key) the list is unavailable."""

    def __init__(self, models: ServiceClient | None) -> None:
        self.models = models

    async def chat_models(self) -> list[Json]:
        if self.models is None:
            raise ModelsUnavailable("models-service cannot be called: no service signing key")
        rows: list[ServingAlias] = []
        page = 1
        try:
            # Every page: the picker offers every chat alias, and the list holds a page of them at a time.
            while True:
                body = cast(AliasPage, await self.models.get("/v1/models/aliases", params={"page": page}))
                rows += body["data"]
                if not body["pagination"]["hasNext"]:
                    break
                page += 1
        except (ServiceCallError, ServiceUnreachable) as e:
            raise ModelsUnavailable(f"models-service did not answer the alias list: {e}") from e
        return [
            {
                "name": str(a["name"]),
                "kind": "chat",
                "clearedSensitivity": a.get("clearedSensitivity"),
                "inputPerMillion": a.get("inputPerMillion"),
                "outputPerMillion": a.get("outputPerMillion"),
            }
            for a in rows
            if a["kind"] == "chat"
        ]

    async def knobs(self, alias: str) -> Json:
        if self.models is None:
            raise ModelsUnavailable("models-service cannot be called: no service signing key")
        try:
            path = f"/v1/models/aliases/{segment(alias)}/knobs"
        except ValueError as e:
            raise _unknown(alias, set()) from e
        try:
            return cast(Json, await self.models.get(path))
        except ServiceCallError as e:
            if e.status == 404:
                raise _unknown(alias, set()) from e
            raise ModelsUnavailable(f"models-service did not answer the alias's knobs: {e}") from e
        except ServiceUnreachable as e:
            raise ModelsUnavailable(f"models-service did not answer the alias's knobs: {e}") from e


def model_setting_problem(values: Mapping[str, float | int | str], schema: Json) -> str | None:
    """The first knob in `values` the alias's knobs schema refuses, as a sentence naming it and what it takes; None
    when all fit. The schema is models-service's (`catalog.knob_schema`): only the knobs the model takes."""
    properties = cast(dict[str, Json], schema.get("properties") or {})
    for name, value in values.items():
        knob = properties.get(name)
        if knob is None:
            offered = ", ".join(sorted(properties)) or "none"
            return f"{name} is not a setting this alias's model takes. It takes: {offered}."
        title = str(knob.get("title") or name)
        if knob.get("type") == "string":
            allowed = cast(list[str] | None, knob.get("enum"))
            if not isinstance(value, str) or (allowed is not None and value not in allowed):
                return f"{title} is one of {', '.join(allowed or [])}."
            continue
        if isinstance(value, str) or (knob.get("type") == "integer" and not isinstance(value, int)):
            return f"{title} is a {'whole number' if knob.get('type') == 'integer' else 'number'}."
        lo, hi = cast(float | None, knob.get("minimum")), cast(float | None, knob.get("maximum"))
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            return f"{title} is from {lo if lo is not None else 'any'} to {hi if hi is not None else 'any'}."
        on = cast(float | None, knob.get("x-minimum-on"))
        if on is not None and 0 < value < on:
            return f"{title} is 0 (off) or at least {on}."
    return None
