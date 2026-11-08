"""Models as the console reads them: the chat aliases an agent may name (agents-service, generated), and the model
provider connections and keys an account admin keeps on models-service. models-service has no generated layer, since
its other routes take a service token; the routes the console's settings screens call are declared here."""

from __future__ import annotations

from typing import Any, cast

from ._transport import Operation, page_items

SERVICE = "models"


def _op(method: str, path: str, *params: str) -> Operation:
    body = "json" if method in ("POST", "PUT") else None
    return {
        "method": method,
        "path": path,
        "pathParams": list(params),
        "query": [],
        "headers": [],
        "body": body,
        "stream": False,
    }


OPERATIONS: dict[str, Operation] = {
    "providers": _op("GET", "/v1/models/providers"),
    "add_provider": _op("POST", "/v1/models/providers"),
    "keys": _op("GET", "/v1/provider-keys"),
    "save_key": _op("PUT", "/v1/provider-keys/{name}", "name"),
    "remove_key": _op("DELETE", "/v1/provider-keys/{name}", "name"),
}


class Models:
    def __init__(self, raw: Any) -> None:
        self._raw = raw
        self._t = raw.agents._t

    def _call(self, name: str, path: dict[str, Any] | None = None, body: Any = None) -> Any:
        return self._t.call(SERVICE, OPERATIONS[name], path or {}, {}, {}, body)

    def aliases(self) -> list[dict[str, Any]]:
        """The chat aliases an agent may name, with what each costs and the data it is cleared for."""
        return page_items(self._raw.agents.agents_list_model_aliases())[0]

    def providers(self) -> list[dict[str, Any]]:
        """The account's provider connections (account admins only; 403 admin_only for anyone else)."""
        return page_items(self._call("providers"))[0]

    def add_provider(self, body: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("add_provider", body=body))

    def keys(self) -> list[dict[str, Any]]:
        """The provider keys by name; a key's value is never answered."""
        return page_items(self._call("keys"))[0]

    def save_key(self, name: str, value: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("save_key", {"name": name}, {"value": value}))

    def remove_key(self, name: str) -> Any:
        return self._call("remove_key", {"name": name})


class AsyncModels:
    def __init__(self, raw: Any) -> None:
        self._raw = raw
        self._t = raw.agents._t

    async def _call(self, name: str, path: dict[str, Any] | None = None, body: Any = None) -> Any:
        return await self._t.call(SERVICE, OPERATIONS[name], path or {}, {}, {}, body)

    async def aliases(self) -> list[dict[str, Any]]:
        return page_items(await self._raw.agents.agents_list_model_aliases())[0]

    async def providers(self) -> list[dict[str, Any]]:
        return page_items(await self._call("providers"))[0]

    async def add_provider(self, body: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call("add_provider", body=body))

    async def keys(self) -> list[dict[str, Any]]:
        return page_items(await self._call("keys"))[0]

    async def save_key(self, name: str, value: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call("save_key", {"name": name}, {"value": value}))

    async def remove_key(self, name: str) -> Any:
        return await self._call("remove_key", {"name": name})
