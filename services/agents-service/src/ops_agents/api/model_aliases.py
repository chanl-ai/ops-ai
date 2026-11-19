"""Which model aliases an agent may name: models-service's chat aliases when it is configured, else only the
runtime's own alias. GET /v1/model-aliases lists them for the agent picker, and a publish request is refused when its
agent names an alias outside the same set."""

from __future__ import annotations

from typing import NotRequired, Protocol, TypedDict, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.errors import ApiError
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


async def chat_aliases(aliases: ModelAliases) -> set[str]:
    return {str(a["name"]) for a in await aliases.chat_models()}


class StaticModelAliases:
    def __init__(self, names: set[str]) -> None:
        self.names = names

    async def chat_models(self) -> list[Json]:
        return [{"name": n, "kind": "chat"} for n in sorted(self.names)]


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
