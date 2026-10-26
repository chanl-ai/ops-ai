"""The one place a call goes out: the base URL per service, the key and team headers, the `{success, data}` envelope,
typed errors and retries. The generated operations and the resource modules call through it; nothing else sends."""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import AsyncIterator, Iterator, Mapping
from typing import Any, TypedDict
from urllib.parse import quote

import httpx

from ._config import Config
from .errors import OpsError, error_for

# Every service is reached through one origin under its own prefix (deploy/fly/Caddyfile); a local stack without the
# proxy is reached by port through Config.services.
PREFIX = {s: f"/api/{s}" for s in ("platform", "agents", "tools", "kb", "files", "documents")}
RETRY_STATUS = (429, 500, 502, 503, 504)
IDEMPOTENCY = "Idempotency-Key"


class Operation(TypedDict):
    method: str
    path: str
    pathParams: list[str]
    query: list[str]
    headers: list[str]
    body: str | None
    stream: bool


def _url(config: Config, service: str, op: Operation, path: Mapping[str, Any]) -> str:
    base = config.services.get(service) or f"{config.base_url.rstrip('/')}{PREFIX[service]}"
    route = op["path"]
    for name in op["pathParams"]:
        value = path.get(name)
        if value is None:
            raise ValueError(f"{name} is required")
        route = route.replace("{" + name + "}", quote(str(value), safe=""))
    return f"{base.rstrip('/')}{route}"


def _headers(config: Config, extra: Mapping[str, Any]) -> dict[str, str]:
    h = {"Accept": "application/json", "User-Agent": "ops-ai-python"}
    if config.api_key:
        h["X-Api-Key"] = config.api_key
    elif config.access_token:
        h["Authorization"] = f"Bearer {config.access_token}"
    if config.team:
        h["X-Team-Id"] = config.team
    h.update({k: str(v) for k, v in extra.items() if v is not None})
    return h


def _retryable(op: Operation, headers: Mapping[str, str]) -> bool:
    """Reads, and writes whose route takes an idempotency key and got one: a retried write without one could run
    twice."""
    return op["method"] == "GET" or (IDEMPOTENCY in op["headers"] and bool(headers.get(IDEMPOTENCY)))


def _result(response: httpx.Response) -> Any:
    request_id = response.headers.get("x-request-id")
    try:
        payload = response.json() if response.content else None
    except json.JSONDecodeError:
        payload = None
    if response.is_error or (isinstance(payload, dict) and payload.get("success") is False):
        err = (payload or {}).get("error") if isinstance(payload, dict) else None
        raise error_for(response.status_code, err or {}, request_id, response.text[:500])
    if isinstance(payload, dict) and "success" in payload and "data" in payload:
        return payload["data"]
    return payload


def _backoff(attempt: int) -> float:
    return min(8.0, 0.5 * 2**attempt) * (0.5 + random.random() / 2)


def _request(  # noqa: PLR0917 - the generated operations pass these in order
    config: Config,
    service: str,
    op: Operation,
    path: Mapping[str, Any],
    query: Mapping[str, Any],
    headers: Mapping[str, Any],
    body: Any,
) -> dict[str, Any]:
    params = {k: v for k, v in query.items() if v is not None}
    req: dict[str, Any] = {
        "method": op["method"],
        "url": _url(config, service, op, path),
        "params": params,
        "headers": _headers(config, headers),
    }
    if body is not None:
        req["json"] = body
    return req


class _Events:
    """Server-sent events as `{event, id, data}`, fed one line at a time; `data` is parsed as JSON when it is JSON."""

    def __init__(self) -> None:
        self.event: dict[str, Any] = {}
        self.raw: list[str] = []

    def feed(self, line: str) -> dict[str, Any] | None:
        if line.startswith(":"):
            return None
        if line:
            key, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if key == "data":
                self.raw.append(value)
            elif key in ("event", "id"):
                self.event[key] = value
            return None
        return self.flush()

    def flush(self) -> dict[str, Any] | None:
        if not self.raw:
            self.event = {}
            return None
        text = "\n".join(self.raw)
        try:
            data: Any = json.loads(text)
        except json.JSONDecodeError:
            data = text
        out = {**self.event, "data": data}
        self.event, self.raw = {}, []
        return out


class Transport:
    def __init__(self, config: Config, client: httpx.Client | None = None) -> None:
        self.config = config
        self.http = client or httpx.Client(timeout=config.timeout)

    def call(  # noqa: PLR0917 - the generated operations pass these in order
        self,
        service: str,
        op: Operation,
        path: Mapping[str, Any],
        query: Mapping[str, Any],
        headers: Mapping[str, Any],
        body: Any,
    ) -> Any:
        if op["stream"]:
            return self.stream(service, op, path, query, headers)
        req = _request(self.config, service, op, path, query, headers, body)
        attempts = self.config.max_retries + 1 if _retryable(op, req["headers"]) else 1
        for attempt in range(attempts):
            try:
                response = self.http.request(**req)
            except httpx.TransportError:
                if attempt + 1 == attempts:
                    raise
                time.sleep(_backoff(attempt))
                continue
            if response.status_code in RETRY_STATUS and attempt + 1 < attempts:
                time.sleep(_backoff(attempt))
                continue
            return _result(response)
        raise OpsError(0, "unreachable", "no attempt was made")

    def stream(
        self, service: str, op: Operation, path: Mapping[str, Any], query: Mapping[str, Any], headers: Mapping[str, Any]
    ) -> Iterator[dict[str, Any]]:
        req = _request(self.config, service, op, path, query, headers, None)
        req["headers"]["Accept"] = "text/event-stream"
        with self.http.stream(**req, timeout=httpx.Timeout(self.config.timeout, read=None)) as response:
            if response.is_error:
                response.read()
                _result(response)
            parser = _Events()
            for line in response.iter_lines():
                if (event := parser.feed(line)) is not None:
                    yield event
            if (event := parser.flush()) is not None:
                yield event

    def close(self) -> None:
        self.http.close()


class AsyncTransport:
    def __init__(self, config: Config, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self.http = client or httpx.AsyncClient(timeout=config.timeout)

    async def call(  # noqa: PLR0917 - the generated operations pass these in order
        self,
        service: str,
        op: Operation,
        path: Mapping[str, Any],
        query: Mapping[str, Any],
        headers: Mapping[str, Any],
        body: Any,
    ) -> Any:
        if op["stream"]:
            return self.stream(service, op, path, query, headers)
        req = _request(self.config, service, op, path, query, headers, body)
        attempts = self.config.max_retries + 1 if _retryable(op, req["headers"]) else 1
        for attempt in range(attempts):
            try:
                response = await self.http.request(**req)
            except httpx.TransportError:
                if attempt + 1 == attempts:
                    raise
                await asyncio.sleep(_backoff(attempt))
                continue
            if response.status_code in RETRY_STATUS and attempt + 1 < attempts:
                await asyncio.sleep(_backoff(attempt))
                continue
            return _result(response)
        raise OpsError(0, "unreachable", "no attempt was made")

    async def stream(
        self, service: str, op: Operation, path: Mapping[str, Any], query: Mapping[str, Any], headers: Mapping[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        req = _request(self.config, service, op, path, query, headers, None)
        req["headers"]["Accept"] = "text/event-stream"
        async with self.http.stream(**req, timeout=httpx.Timeout(self.config.timeout, read=None)) as response:
            if response.is_error:
                await response.aread()
                _result(response)
            parser = _Events()
            async for line in response.aiter_lines():
                if (event := parser.feed(line)) is not None:
                    yield event
            if (event := parser.flush()) is not None:
                yield event

    async def close(self) -> None:
        await self.http.aclose()


def page_items(data: Any) -> tuple[list[Any], dict[str, Any] | None]:
    """A list response's items and how to ask for the next page, for both shapes the API uses: `pagination` with
    `hasNext` (page and pageSize), or `nextCursor` (cursor and limit). A bare list is one page."""
    if isinstance(data, list):
        return data, None
    if not isinstance(data, dict):
        return [], None
    items = data.get("items")
    if items is None:
        items = data.get("data") if isinstance(data.get("data"), list) else []
    pagination = data.get("pagination")
    if isinstance(pagination, dict) and pagination.get("hasNext"):
        return items, {"page": int(pagination.get("page", 1)) + 1}
    if data.get("nextCursor"):
        return items, {"cursor": data["nextCursor"]}
    return items, None
