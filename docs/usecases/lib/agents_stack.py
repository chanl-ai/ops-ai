"""The agents stack a page runs against when its Details row names the starters pack (page_stack.py hands over to it)."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any

PEOPLE = {
    "priya": "p.shah@harborpine.example",
    "maya": "m.okafor@harborpine.example",
}


def agents_stack(stack: ExitStack, names: list[str], mcp: bool) -> dict[str, dict[str, Any]]:
    """The agents stack, which is the templates stack the template use cases share (templates_stack.py): the starters
    pack is on for team_ops. One profile per person. A page about the team's MCP address also gets the token an
    outside assistant holds after the company sign-in (`mcpToken`) and the address (`mcpUrl`), since that sign-in is a
    browser flow and no SDK word makes it."""
    from templates_stack import templates_stack
    from usecase_harness import AGENTS_PORT, PLATFORM_PORT, TOOLS_PORT, signed_in

    s = stack.enter_context(templates_stack(documents=True))
    services = {
        "tools": f"http://127.0.0.1:{TOOLS_PORT}",
        "agents": f"http://127.0.0.1:{AGENTS_PORT}",
        "platform": f"http://127.0.0.1:{PLATFORM_PORT}",
    }
    out: dict[str, dict[str, Any]] = {}
    for name in (n for n in names if n in PEOPLE):
        session = signed_in(s.accounts, PEOPLE[name])
        out[name] = {
            "baseUrl": f"http://127.0.0.1:{PLATFORM_PORT}",
            "team": "team_ops",
            "services": services,
            "accessToken": session.get("token"),
            "refreshToken": session.get("refreshToken"),
        }
        if mcp:
            out[name] |= {"mcpUrl": f"{services['tools']}/mcp/team_ops", "mcpToken": s.token(PEOPLE[name])}
    return out
