"""Testing an account's model key before anything uses it, and listing what it reaches: the models of an OpenAI or
Anthropic account, the deployments of an Azure OpenAI resource, the foundation models of a Bedrock region. Where
each provider keeps its list and which header takes the key is the registry entry's `modelList`; the request is
built from it here and nowhere else.

The key leaves only for the provider: at the entry's own address unless the admin names an endpoint, and for Azure
OpenAI at a resource host under openai.azure.com. Every request goes through ops_service_kit's PublicFetch (the
address rule tools-service and platform-service use), which refuses a private, loopback, link-local or metadata
address and, with no redirects allowed, never follows one with the key. A refusal reads by status only; the
provider's body is never passed on."""

from __future__ import annotations

import ipaddress
import json
import re
from urllib.parse import urlsplit

import httpx

from ops_service_kit.narrow import a_list, an_object, json_object
from ops_service_kit.public_address import AddressRefused, FetchFailed, PublicFetch

from .providers import bedrock_pair
from .registry import ProviderEntry
from .sigv4 import signed_headers

AZURE_HOST_SUFFIX = ".openai.azure.com"


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


def _request(
    entry: ProviderEntry, key: str, endpoint: str | None, api_version: str | None, region: str | None
) -> tuple[str, dict[str, str]]:
    """The model-list request the entry describes: its base (the endpoint given, else the entry's own, `{region}`
    filled), its path, and the key in the header the provider reads it from."""
    listing = entry.model_list
    if listing is None:
        raise KeyRefused(f"{entry.label} connections list no models.")
    if listing.host == "azure":
        base: str | None = azure_host(endpoint)
    else:
        # A key goes to an address the admin typed only for a type whose connections name their own base URL;
        # OpenAI's or Gemini's key always goes to the provider's own address.
        own = endpoint if "baseUrl" in entry.connection.properties else None
        base = listing.base or own or entry.base_url
        if base and "{region}" in base:
            # The region's form is the entry's (its connection field's pattern), so it cannot change the host.
            field = entry.connection.properties.get("region")
            if not region or field is None or field.pattern is None or not re.fullmatch(field.pattern, region):
                raise EndpointRefused(f"region is {field.description if field else 'not a field of this type'}")
            base = base.replace("{region}", region)
    if not base:
        raise EndpointRefused(f"endpoint is missing: the base URL of the {entry.label} endpoint")
    path = listing.path.replace("{apiVersion}", api_version or listing.api_version or "")
    url = f"{base.rstrip('/')}{path}"
    headers = dict(listing.headers)
    if listing.auth == "bearer":
        headers["authorization"] = f"Bearer {key}"
    elif listing.auth in ("x-api-key", "api-key"):
        headers[listing.auth] = key
    elif listing.auth == "sigv4":
        pair = bedrock_pair(key)
        if pair is None or region is None:
            raise KeyRefused("The saved key is not an access key pair (accessKeyId and secretAccessKey).")
        headers |= signed_headers(
            "GET", url, b"", access_key=pair[0], secret_key=pair[1], region=region, service="bedrock"
        )
        headers.pop("host", None)
    return url, headers


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
    entry: ProviderEntry,
    key: str,
    *,
    endpoint: str | None = None,
    api_version: str | None = None,
    region: str | None = None,
) -> list[dict[str, str]]:
    """The ids the key reaches ({id, model?}). EndpointRefused for an endpoint outside the rule; KeyRefused
    otherwise when the provider does not answer 200. A type that lists no models (scripted) answers none."""
    if entry.test == "none":
        return []
    url, headers = _request(entry, key, endpoint, api_version, region)
    try:
        body = await fetch.get(http, url, headers)
    except AddressRefused as e:
        raise EndpointRefused(str(e)) from e
    except FetchFailed as e:
        raise KeyRefused(_reason(e.status)) from e
    try:
        loaded: object = json.loads(body) or {}
    except ValueError as e:
        raise KeyRefused("The provider's answer was not a list of models.") from e
    answer = json_object(loaded)
    if not isinstance(loaded, dict):
        raise KeyRefused("The provider's answer was not a list of models.")
    listing = entry.model_list
    assert listing is not None
    found = answer.get(listing.items)
    rows = [an_object(m, "model") for m in (a_list(found, listing.items) if found else [])]
    prefix = listing.id_prefix or ""
    under = listing.model_field
    listed = [
        {"id": str(m[listing.id]).removeprefix(prefix), **({"model": str(m[under])} if under and m.get(under) else {})}
        for m in rows
        if m.get(listing.id)
    ]
    return [m for m in listed if is_chat_model(m.get("model") or m["id"])]


# Providers list every model the key reaches; a chat alias can only use the ones that answer chat turns.
NOT_CHAT = re.compile(
    r"embed|whisper|tts|transcribe|dall-e|gpt-image|image|audio|realtime|moderation|sora|search|davinci|babbage", re.I
)


def is_chat_model(name: str) -> bool:
    return not NOT_CHAT.search(name)
