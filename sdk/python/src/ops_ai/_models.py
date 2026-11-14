"""Models as the console reads them: the chat aliases an agent may name (agents-service, generated), and the model
provider connections and keys an account admin keeps on models-service. models-service has no generated layer, since
its other routes take a service token; the routes the console's settings screens call are declared here."""

from __future__ import annotations

from typing import Any, cast

from ._transport import Operation, page_items

SERVICE = "models"


def _op(method: str, path: str, *params: str, query: tuple[str, ...] = ()) -> Operation:
    body = "json" if method in ("POST", "PUT") else None
    return {
        "method": method,
        "path": path,
        "pathParams": list(params),
        "query": list(query),
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
    "check_key": _op("POST", "/v1/provider-keys/{name}/check", "name"),
    "key_models": _op("GET", "/v1/provider-keys/{name}/models", "name", query=("provider", "endpoint", "apiVersion")),
    "set_chat_model": _op("PUT", "/v1/models/chat-model"),
}


def _where(provider: str, endpoint: str | None, api_version: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {"provider": provider}
    if endpoint:
        out["endpoint"] = endpoint
    if api_version:
        out["apiVersion"] = api_version
    return out


class Models:
    def __init__(self, raw: Any) -> None:
        self._raw = raw
        self._t = raw.agents._t

    def _call(self, name: str, path: dict[str, Any] | None = None, body: Any = None, query: Any = None) -> Any:
        return self._t.call(SERVICE, OPERATIONS[name], path or {}, query or {}, {}, body)

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

    def check_key(self, name: str, provider: str, endpoint: str | None = None, api_version: str | None = None) -> Any:
        """Whether the provider accepts the saved key: {ok, reason, models}."""
        return self._call("check_key", {"name": name}, _where(provider, endpoint, api_version))

    def key_models(self, name: str, provider: str, endpoint: str | None = None, api_version: str | None = None) -> Any:
        """The models (Azure OpenAI: deployments) the saved key reaches."""
        return self._call("key_models", {"name": name}, query=_where(provider, endpoint, api_version))

    def set_chat_model(self, body: dict[str, Any]) -> dict[str, Any]:
        """Points chat at {provider, keyName, model, endpoint?, apiVersion?}."""
        return cast(dict[str, Any], self._call("set_chat_model", body=body))


class AsyncModels:
    def __init__(self, raw: Any) -> None:
        self._raw = raw
        self._t = raw.agents._t

    async def _call(self, name: str, path: dict[str, Any] | None = None, body: Any = None, query: Any = None) -> Any:
        return await self._t.call(SERVICE, OPERATIONS[name], path or {}, query or {}, {}, body)

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

    async def check_key(
        self, name: str, provider: str, endpoint: str | None = None, api_version: str | None = None
    ) -> Any:
        return await self._call("check_key", {"name": name}, _where(provider, endpoint, api_version))

    async def key_models(
        self, name: str, provider: str, endpoint: str | None = None, api_version: str | None = None
    ) -> Any:
        return await self._call("key_models", {"name": name}, query=_where(provider, endpoint, api_version))

    async def set_chat_model(self, body: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call("set_chat_model", body=body))
