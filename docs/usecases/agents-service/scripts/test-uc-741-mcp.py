"""uc-741, mcp layer: docs/usecases/agents-service/templates-over-mcp.md. An assistant connected to team_ops' MCP
address with the official MCP Python SDK finds list_templates and install_template among its tools. Priya (admin)
lists and installs the starter skill; Maya (approver, who may run tools but not create skills) is refused with a tool
error and nothing is made."""

from __future__ import annotations

import asyncio
from typing import Any

from steps import MAYA, PRIYA, list_skills, mcp_session, sign_in_as
from templates_stack import SKILL, SOURCE, templates_stack
from usecase_harness import check, finish

TOOLS = ("list_templates", "install_template")


async def tool_names(token: str) -> list[str]:
    async with mcp_session(token, "team_ops") as c:
        return sorted(t.name for t in (await c.list_tools()).tools)


async def call(token: str, name: str, args: dict[str, Any]) -> Any:
    async with mcp_session(token, "team_ops") as c:
        return await c.call_tool(name, args)


def skill_ids(s: Any) -> list[str]:
    return [str(x.get("id")) for x in list_skills(sign_in_as(PRIYA))]


with templates_stack() as s:
    priya, maya = s.token(PRIYA), s.token(MAYA)

    # 1. Both tools are listed for an assistant on the team's address.
    seen = asyncio.run(tool_names(priya))
    check("1 tools/list offers list_templates and install_template", all(t in seen for t in TOOLS), seen)

    if all(t in seen for t in TOOLS):
        # 2. list_templates answers the same list as the API, read-only.
        listed = asyncio.run(call(priya, "list_templates", {"kind": "skill"}))
        rows = (listed.structured_content or {}).get("templates") or []
        check(
            "2 list_templates returns the starter skill, marked read-only",
            listed.is_error is False and any(r.get("id") == SKILL for r in rows),
            rows,
        )

        # 3. Maya may run tools but not create skills: install is a tool error and no skill is made.
        before = skill_ids(s)
        refused = asyncio.run(call(maya, "install_template", {"resource": f"{SOURCE}:{SKILL}"}))
        check(
            "3 install_template is refused for a person without the skills create right, and nothing is made",
            refused.is_error is True and skill_ids(s) == before,
            refused,
        )

        # 4. Priya installs it as herself; the copy is in the team's skills.
        made = asyncio.run(call(priya, "install_template", {"resource": f"{SOURCE}:{SKILL}"}))
        record = str(((made.structured_content or {}).get("copy") or {}).get("recordId") or "")
        check(
            "4 install_template makes the team's copy for Priya, and it is in the skills list",
            made.is_error is False and bool(record) and record in skill_ids(s),
            made,
        )
    else:
        for n in ("2 list_templates returns the starter skill", "3 install is refused without the create right",
                  "4 install_template makes the team's copy"):  # fmt: skip
            check(n, False, "the team MCP address does not offer the template tools")

finish()
