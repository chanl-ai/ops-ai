"""Testing an account's model key before anything uses it, and listing what it reaches: the models of an OpenAI or
Anthropic account, the deployments of an Azure OpenAI resource. Each provider keeps its list in its own place and
takes the key in its own header, so the request is built per provider here and nowhere else.

The key leaves only for the provider: OpenAI and Anthropic at their own fixed addresses, Azure OpenAI at a resource
host under openai.azure.com. Every request goes through ops_service_kit's PublicFetch (the address rule tools-service
and platform-service use), which refuses a private, loopback, link-local or metadata address and, with no redirects
allowed, never follows one with the key. A refusal reads by status only; the provider's body is never passed on."""

from __future__ import annotations

import ipaddress
import json
import re
from typing import Any, Literal, cast
from urllib.parse import urlsplit

import httpx

from ops_service_kit.public_address import AddressRefused, FetchFailed, PublicFetch

Kind = Literal["openai", "azure-openai", "anthropic"]
AZURE_API_VERSION = "2022-12-01"
AZURE_HOST_SUFFIX = ".openai.azure.com"
ANTHROPIC_VERSION = "2023-06-01"
FIXED = {"openai": "https://api.openai.com/v1/models", "anthropic": "https://api.anthropic.com/v1/models"}


class KeyRefused(Exception):
    """The provider did not accept the key or could not be reached; the message says which by status only."""


class EndpointRefused(ValueError):
    """The Azure OpenAI endpoint is not a resource host this service sends a key to."""


def azure_host(endpoint: str | None) -> str:
    """`https://<resource>.openai.azure.com`, checked: https, no user info, port 443 only, a name under
    openai.azure.com (never an IP literal), no path."""
    parts = urlsplit(endpoint or "")
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError as e:
        raise EndpointRefused("endpoint has a port that is not a number") from e
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or literal
        or not host.endswith(AZURE_HOST_SUFFIX)
        or host == AZURE_HOST_SUFFIX[1:]
        or parts.path.strip("/")
        or parts.query
    ):
        raise EndpointRefused("endpoint is the resource's address, such as https://<resource>.openai.azure.com")
    return f"https://{host}"


def _request(kind: Kind, key: str, endpoint: str | None, api_version: str | None) -> tuple[str, dict[str, str]]:
    if kind == "azure-openai":
        # The data-plane deployments list: the names chat is called with on this resource.
        url = f"{azure_host(endpoint)}/openai/deployments?api-version={api_version or AZURE_API_VERSION}"
        return url, {"api-key": key}
    if kind == "anthropic":
        return FIXED["anthropic"], {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    return FIXED["openai"], {"authorization": f"Bearer {key}"}


def _reason(status: int | None) -> str:
    if status in (401, 403):
        return "The provider refused the key."
    if status == 404:
        return "The provider found nothing at that address; check the endpoint."
    if status is None:
        return "The provider could not be reached."
    return f"The provider answered {status}."


async def listed_models(
    http: httpx.AsyncClient,
    fetch: PublicFetch,
    kind: Kind,
    key: str,
    *,
    endpoint: str | None = None,
    api_version: str | None = None,
) -> list[dict[str, str]]:
    """The ids the key reaches ({id, model?}). EndpointRefused for an Azure endpoint outside the rule; KeyRefused
    otherwise when the provider does not answer 200."""
    url, headers = _request(kind, key, endpoint, api_version)
    try:
        body = await fetch.get(http, url, headers)
    except AddressRefused as e:
        raise EndpointRefused(str(e)) from e
    except FetchFailed as e:
        raise KeyRefused(_reason(e.status)) from e
    try:
        rows = cast(list[dict[str, Any]], (json.loads(body) or {}).get("data") or [])
    except (ValueError, AttributeError) as e:
        raise KeyRefused("The provider's answer was not a list of models.") from e
    listed = [
        {"id": str(m["id"]), **({"model": str(m["model"])} if m.get("model") else {})} for m in rows if m.get("id")
    ]
    return [m for m in listed if is_chat_model(m.get("model") or m["id"])]


# Providers list every model the key reaches; a chat alias can only use the ones that answer chat turns.
NOT_CHAT = re.compile(
    r"embed|whisper|tts|transcribe|dall-e|gpt-image|image|audio|realtime|moderation|sora|search|davinci|babbage", re.I
)


def is_chat_model(name: str) -> bool:
    return not NOT_CHAT.search(name)
