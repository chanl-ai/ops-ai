"""What a Python tool is handed for one call: the merged settings, an HTTP client and a deadline.

`ctx.http` belongs to the service running the call. It carries the credential the call signs in with and sends every
request through that service's egress check, so a function never sees a token and reaches only the plugin's hosts.
A function holds no state between calls and learns nothing of the caller beyond what the context gives it."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import DeadlineExceeded


@dataclass(frozen=True)
class Response:
    status_code: int
    text: str
    headers: Mapping[str, str] = field(default_factory=dict[str, str])

    def json(self) -> Any:
        return json.loads(self.text)


# (method, url, params, json body) -> Response, supplied by the service; it raises the SDK's errors.
Send = Callable[[str, str, Mapping[str, Any] | None, Any], Response]


class Http:
    def __init__(self, send: Send, deadline: float) -> None:
        self._send = send
        self._deadline = deadline

    def request(self, method: str, url: str, *, params: Mapping[str, Any] | None = None, json: Any = None) -> Response:
        if time.monotonic() > self._deadline:
            raise DeadlineExceeded("The call ran past its deadline.")
        return self._send(method, url, params, json)

    def get(self, url: str, *, params: Mapping[str, Any] | None = None) -> Response:
        return self.request("GET", url, params=params)

    def post(self, url: str, *, json: Any = None) -> Response:
        return self.request("POST", url, json=json)

    def patch(self, url: str, *, json: Any = None) -> Response:
        return self.request("PATCH", url, json=json)


class Settings:
    """The merged settings, read as attributes (`ctx.settings.instance_url`); an unknown name is an AttributeError."""

    def __init__(self, values: Mapping[str, Any]) -> None:
        self._values = dict(values)

    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def get(self, name: str, default: Any = None) -> Any:
        return self._values.get(name, default)

    def as_dict(self) -> dict[str, Any]:
        return dict(self._values)


@dataclass(frozen=True)
class Context:
    settings: Settings
    http: Http
    deadline: float

    @classmethod
    def of(cls, settings: Mapping[str, Any], send: Send, *, timeout_s: float = 30.0) -> Context:
        deadline = time.monotonic() + timeout_s
        return cls(Settings(settings), Http(send, deadline), deadline)
