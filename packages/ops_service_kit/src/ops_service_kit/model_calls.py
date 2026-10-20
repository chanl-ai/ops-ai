"""One structured model call through models-service, for a service that is not an agent (c-300): the service holds its
own model key (its budget line in models-service, never a provider credential), sends a system and a user message,
and reads the answer as the `final_result` function's arguments, the form the agent kernel asks structured output in.
documents-service's extraction carries the same call and moves onto this one in a follow-on."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

import httpx

# The alias a service's calls use while models-service has no alias of the service's own name.
FALLBACK_ALIAS = "default"


class ModelCallError(Exception):
    """models-service could not be reached, refused the call, or has neither alias."""


@dataclass
class StructuredCalls:
    http: httpx.AsyncClient
    key: str
    alias: str = FALLBACK_ALIAS

    async def structured(self, system: str, user: str, schema: dict[str, Any], *, tenant: str, step: str) -> Any:
        """The answer's arguments; {} when the model answered with something unreadable, which fails the caller's own
        schema check rather than raising."""
        for name in dict.fromkeys((self.alias, FALLBACK_ALIAS)):
            try:
                r = await self.http.post(
                    "/v1/models/chat/completions",
                    headers={"Authorization": f"Bearer {self.key}", "X-Step-Id": step, "X-Tenant-Id": tenant},
                    json={
                        "model": name,
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                        "tools": [{"type": "function", "function": {"name": "final_result", "parameters": schema}}],
                        "tool_choice": "required",
                    },
                )
            except httpx.HTTPError as e:
                raise ModelCallError(f"models-service could not be reached: {e}") from e
            if r.status_code == 404 and "alias_not_found" in r.text and name != FALLBACK_ALIAS:
                continue
            if r.status_code >= 400:
                raise ModelCallError(f"models-service answered {r.status_code}: {r.text[:300]}")
            message = cast(dict[str, Any], cast(dict[str, Any], r.json())["choices"][0]["message"])
            calls = cast(list[dict[str, Any]], message.get("tool_calls") or [])
            raw = calls[0]["function"]["arguments"] if calls else message.get("content")
            try:
                return json.loads(raw) if isinstance(raw, str) else {}
            except json.JSONDecodeError:
                return {}
        raise ModelCallError(f"models-service has neither {self.alias} nor {FALLBACK_ALIAS}")
