# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""tools-service, as a service that reads sources calls it: the sources a team can make, the hosts a source's values
would reach, and one gateway call. The caller holds no token and loads no plugin code: tools-service signs each call
with the team's sign-in and sends it through the egress policy, and every page and fetch is in its call log."""

from __future__ import annotations

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.http import JsonValue
from ops_service_kit.ids import new_id
from ops_service_kit.narrow import json_object

from .contract import Answer


class ToolReader:
    """tools-service, as this service calls it: the sources a team can create, and one gateway call. `key_prefix`
    names the calling service in each call's idempotency key."""

    def __init__(self, tools: ServiceClient, *, key_prefix: str) -> None:
        self.tools = tools
        self.key_prefix = key_prefix

    async def declared(self, tenant_id: str, team_id: str) -> list[dict[str, JsonValue]]:
        return list(await self.tools.get("/v1/knowledge-sources", tenant=tenant_id, team=team_id) or [])

    async def source_hosts(
        self,
        tenant_id: str,
        team_id: str,
        cfg: dict[str, JsonValue],
        *,
        credentials: dict[str, str] | None = None,
    ) -> list[dict[str, JsonValue]]:
        """Each host the source's values would have its sync reach, decided by the account's egress rule as any new
        outside address is (tools-service `/v1/knowledge-sources/hosts`): asked as the person adding or changing the
        source (`credentials`), it lists the host where they may, asks the Security team, or is refused; asked as
        this service, it only reads whether each host passes now."""
        body: dict[str, JsonValue] = {
            "plugin": cfg.get("plugin"),
            "source": cfg.get("source"),
            "values": cfg.get("values") or {},
        }
        # The person's own credentials decide when given; this service's token rides beside them.
        answer = await self.tools.post(
            "/v1/knowledge-sources/hosts",
            json=body,
            tenant=tenant_id,
            team=team_id,
            headers=credentials or None,
            token_header="X-Service-Authorization" if credentials else "Authorization",
        )
        return list(answer or [])

    async def call(
        self, tenant_id: str, team_id: str, tool: str | None, args: dict[str, JsonValue], *, act: str
    ) -> Answer:
        body = {
            "tool": tool,
            "input": args,
            "key": new_id(self.key_prefix),
            # A read acts on the source as it is: a live run (tools-service takes test or live).
            "runContext": {"act": act, "environment": "live"},
        }
        try:
            data = await self.tools.post("/v1/calls", json=body, tenant=tenant_id, team=team_id)
        except ServiceCallError as e:
            return Answer(False, code=str(e.code or "refused"), message=e.message)
        except ServiceUnreachable as e:
            return Answer(False, code="UPSTREAM_UNREACHABLE", message=str(e))
        answer = json_object(data)
        if not answer.get("ok"):
            error = json_object(json_object(answer.get("output")).get("error"))
            return Answer(False, code=str(error.get("code") or "TOOL_FAILED"), message=str(error.get("message") or ""))
        return Answer(True, answer.get("output"))
