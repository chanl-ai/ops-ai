"""Which model aliases an agent may name: models-service's chat aliases when it is configured, else only the
runtime's own alias. GET /v1/model-aliases lists them for the agent picker, and a publish request is refused when its
agent names an alias outside the same set."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import httpx

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
    """GET /v1/models/aliases on models-service, with this service's Ed25519 token; chat aliases only."""

    def __init__(self, client: httpx.AsyncClient, token: Callable[[], str]) -> None:
        self.client = client
        self.token = token

    async def chat_models(self) -> list[dict[str, Any]]:
        try:
            r = await self.client.get("/v1/models/aliases", headers={"Authorization": f"Bearer {self.token()}"})
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ModelsUnavailable(f"models-service did not answer the alias list: {e}") from e
        rows: list[dict[str, Any]] = r.json()["data"]
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
