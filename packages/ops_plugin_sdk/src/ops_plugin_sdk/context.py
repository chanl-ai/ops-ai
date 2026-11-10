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

from .errors import BadInput, DeadlineExceeded


@dataclass(frozen=True)
class Response:
    status_code: int
    text: str
    headers: Mapping[str, str] = field(default_factory=dict[str, str])
    # The body as sent, for an answer that is not text (a PDF a page links to).
    content: bytes = b""

    def json(self) -> Any:
        return json.loads(self.text)


# (method, url, params, json body, headers) -> Response, supplied by the service; it raises the SDK's errors. The
# headers are the request's own, from ASKED_HEADERS only; the sign-in and the plugin's headers are the service's.
Send = Callable[[str, str, Mapping[str, Any] | None, Any, Mapping[str, str] | None], Response]

# The headers a function may set on one request: asking for a page only if it changed, and what kind of answer it takes.
# Anything else (a sign-in, a cookie, a host) is the service's to send.
ASKED_HEADERS = frozenset({"if-none-match", "if-modified-since", "accept", "accept-language"})


class Http:
    def __init__(self, send: Send, deadline: float) -> None:
        self._send = send
        self._deadline = deadline

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        if time.monotonic() > self._deadline:
            raise DeadlineExceeded("The call ran past its deadline.")
        if headers and (refused := sorted(h for h in headers if h.lower() not in ASKED_HEADERS)):
            raise BadInput(f"A tool sets only {', '.join(sorted(ASKED_HEADERS))}, not {', '.join(refused)}.")
        return self._send(method, url, params, json, dict(headers) if headers else None)

    def get(
        self, url: str, *, params: Mapping[str, Any] | None = None, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self.request("GET", url, params=params, headers=headers)

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
