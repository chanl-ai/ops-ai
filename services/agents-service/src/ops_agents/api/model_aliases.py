"""Which model aliases an agent may name: models-service's chat aliases when it is configured, else only the
runtime's own alias. GET /v1/model-aliases lists them for the agent picker, and a publish request is refused when its
agent names an alias outside the same set."""

from __future__ import annotations

from typing import Any, Protocol, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.errors import ApiError


class ModelsUnavailable(ApiError):
    status = 503
    code = "models_unavailable"


class ModelAliases(Protocol):
    async def chat_models(self) -> list[dict[str, Any]]:
        """Wire rows, `{name, kind: "chat"}` plus clearance and prices when models-service knows them."""
        ...


async def chat_aliases(aliases: ModelAliases) -> set[str]:
    return {str(a["name"]) for a in await aliases.chat_models()}


class StaticModelAliases:
    def __init__(self, names: set[str]) -> None:
        self.names = names

    async def chat_models(self) -> list[dict[str, Any]]:
        return [{"name": n, "kind": "chat"} for n in sorted(self.names)]


class HttpModelAliases:
    """GET /v1/models/aliases on models-service through ServiceClient; chat aliases only. With no client (no service
    signing key) the list is unavailable."""

    def __init__(self, models: ServiceClient | None) -> None:
        self.models = models

    async def chat_models(self) -> list[dict[str, Any]]:
        if self.models is None:
            raise ModelsUnavailable("models-service cannot be called: no service signing key")
        try:
            rows = cast(list[dict[str, Any]], await self.models.get("/v1/models/aliases"))
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
            if a.get("kind") == "chat"
        ]
