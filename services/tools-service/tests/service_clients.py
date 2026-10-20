"""This service's ServiceClient over a fake callee, and the claims of the token a request carried, so a test checks
which tenant and team a call named."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any

import httpx

from ops_identity import ServiceClient, dev_service_signer

Handler = Callable[[httpx.Request], Any]


def fake_service(handler: Handler, audience: str, scopes: list[str] | None = None) -> ServiceClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=f"http://{audience}")
    return ServiceClient(http, dev_service_signer(), "tools", audience, list(scopes or []))


def claims(request: httpx.Request, header: str = "authorization") -> dict[str, Any]:
    token = request.headers[header].removeprefix("Bearer ")
    return dict(json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==")))
