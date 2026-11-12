"""uc-742, mcp layer: docs/usecases/agents-service/skills-as-mcp-prompts.md. After Priya installs the starter skill
doc-coauthoring, an assistant on team_ops' MCP address finds it in prompts/list, and prompts/get returns the skill's
body with arguments made from its inputs (topic, doc_type)."""

from __future__ import annotations

import asyncio
from typing import Any

from steps import PRIYA, install_template, mcp_session, sign_in_as
from templates_stack import SKILL, SOURCE, templates_stack
from usecase_harness import check, finish


async def prompts(token: str) -> dict[str, Any]:
    async with mcp_session(token, "team_ops") as c:
        return {p.name: p for p in (await c.list_prompts()).prompts}


async def prompt(token: str, name: str, args: dict[str, str]) -> Any:
    async with mcp_session(token, "team_ops") as c:
        return await c.get_prompt(name, args)


with templates_stack() as s:
    token = s.token(PRIYA)

    # 1. Install the starter skill (the SDK step; uc-740 proves it).
    try:
        install_template(sign_in_as(PRIYA), f"{SOURCE}:{SKILL}")
        installed: Any = True
    except Exception as e:
        installed = str(e)
    check("1 the starter skill is installed in team_ops", installed is True, installed)

    # 2. prompts/list names the skill with its inputs as arguments.
    try:
        listed = asyncio.run(prompts(token))
    except Exception as e:  # the address answers no prompts capability yet
        listed = {"failed": str(e)}
    found = listed.get(SKILL) if isinstance(listed, dict) else None
    args = sorted(a.name for a in (getattr(found, "arguments", None) or []))
    check("2 prompts/list offers the skill with arguments topic and doc_type", args == ["doc_type", "topic"], listed)

    # 3. prompts/get returns the skill's body with the arguments filled in.
    try:
        got = asyncio.run(prompt(token, SKILL, {"topic": "Card dispute letters", "doc_type": "runbook"}))
        text = " ".join(str(getattr(m.content, "text", "")) for m in got.messages)
    except Exception as e:
        text = f"failed: {e}"
    check(
        "3 prompts/get returns the skill's instructions with the topic filled in", "Card dispute letters" in text, text
    )

finish()
