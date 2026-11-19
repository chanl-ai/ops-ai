"""Shared fixtures for the skills-in-chat api scripts (uc-743 to uc-750): a team's published Salesforce skill with two
parts, an agent that may use it, and a chat turn that names a skill and a part. The stack is platform-service and
agents-service on the scripted model, with the dev seed's roles signing in as they do in the console."""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from usecase_harness import AGENTS_PORT, agents, as_role, bearer, data, platform, signed_in, sse, tools

PREPARE = {
    "slug": "prepare-meeting",
    "name": "Prepare a client meeting",
    "useWhen": "Use to brief the adviser before a client meeting.",
    "instructions": "Read the client's account, open cases and opportunities, then write a one-page brief.",
    "inputs": [{"name": "client", "description": "The client's name", "required": True}],
}
UPDATE = {
    "slug": "update-opportunity",
    "name": "Update an opportunity",
    "useWhen": "Use to change an opportunity after a client call.",
    "instructions": "Read the change back to the adviser and ask them to confirm before saving.",
    "inputs": [
        {"name": "client", "description": "The client's name", "required": True},
        {"name": "note", "description": "What was agreed", "required": False},
    ],
}
SALESFORCE = {
    "name": "Salesforce",
    "useWhen": "Use for anything about a client's Salesforce record.",
    "instructions": "Work only from Salesforce. Say what you read.",
    "parts": [PREPARE, UPDATE],
}


# A skill with no parts: setup that works today, so a script about rights, publishing or the menu fails on its own rule.
PLAIN = {
    "useWhen": "Use for anything about a client's Salesforce record.",
    "instructions": "Work only from Salesforce. Say what you read.",
}


@dataclass
class Stack:
    api: httpx.Client
    admin: dict[str, str]
    viewer: dict[str, str]
    chat_user: dict[str, str]

    def make_skill(self, body: dict[str, Any], *, publish: bool = True) -> dict[str, Any]:
        """A skill of the admin's team; with `publish` it is sent for review and live on return (the dev stack
        approves at once). Raises SystemExit naming the refused request, so a refusal is a setup failure."""
        made = self.api.post("/v1/skills", json={"ownerTeam": "team_ops", **body}, headers=self.admin)
        if made.status_code != 201:
            raise SystemExit(f"FAIL make skill {body.get('name')}: {made.status_code} {made.text[:300]}")
        skill = data(made)
        if publish:
            sent = self.api.post(
                f"/v1/skills/{skill['id']}/publish-requests", json={"note": "use case"}, headers=self.admin
            )
            if sent.status_code != 201:
                raise SystemExit(f"FAIL publish skill {body.get('name')}: {sent.status_code} {sent.text[:300]}")
            skill = data(sent)
        return skill

    def make_agent(
        self, name: str = "Desk", *, tool_ids: list[str] | None = None, skill_menu: str | None = None
    ) -> str:
        """A published agent of the admin's team."""
        agent = data(self.api.post("/v1/agents", json={"name": name, "role": "Answers the team"}, headers=self.admin))
        patch: dict[str, Any] = {"toolIds": tool_ids or []}
        if skill_menu:
            patch["skillMenu"] = skill_menu
        saved = self.api.patch(f"/v1/agents/{agent['id']}", json=patch, headers=self.admin)
        if saved.status_code != 200:
            raise SystemExit(f"FAIL set agent {name} {patch}: {saved.status_code} {saved.text[:300]}")
        draft = data(saved)
        sent = self.api.post(
            f"/v1/agents/{agent['id']}/publish-requests", json={"version": draft["version"]}, headers=self.admin
        )
        if sent.status_code not in (200, 201):
            raise SystemExit(f"FAIL publish agent {name}: {sent.status_code} {sent.text[:300]}")
        return str(agent["id"])

    def thread(self, agent: str, headers: dict[str, str] | None = None) -> str:
        return str(
            data(self.api.post("/chat/threads", json={"agentId": agent, "kbIds": []}, headers=headers or self.admin))[
                "id"
            ]
        )

    def send(
        self, thread: str, text: str, skill: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        body: dict[str, Any] = {"content": text}
        if skill:
            body["skill"] = skill
        return self.api.post(
            f"/chat/threads/{thread}/messages",
            json=body,
            headers={**(headers or self.admin), "Accept": "text/event-stream"},
            timeout=120,
        )

    def last_reply(self, thread: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        messages = data(self.api.get(f"/chat/threads/{thread}", headers=headers or self.admin))["messages"]
        return [m for m in messages if m.get("role") == "assistant"][-1]


def refusal(res: httpx.Response) -> tuple[int, str]:
    """(status, error code) of a refused request; the code is empty when the body carries none."""
    try:
        return res.status_code, str(res.json().get("error", {}).get("code", ""))
    except ValueError:
        return res.status_code, ""


def stream_error_code(res: httpx.Response) -> str:
    """The code of an `error` event when a refusal arrives inside the stream."""
    return next((str(e.get("code", "")) for e in sse(res.text) if e.get("type") == "error"), "")


@contextmanager
def skills_stack() -> Generator[Stack]:
    """platform-service signing people in, tools-service with the Salesforce plugin signed in to a fake Salesforce
    for the team (so a skill may name its tools), and agents-service reading it, on the scripted model."""
    from fake_salesforce import salesforce
    from templates_stack import AUTH, PUBLIC, SALESFORCE_PLUGIN, salesforce_on

    with ExitStack() as stack:
        sf = stack.enter_context(salesforce())
        platform_api, _ = stack.enter_context(platform(env=PUBLIC))
        plugins = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps([str(SALESFORCE_PLUGIN)])}
        gw = stack.enter_context(
            tools(
                {
                    **AUTH,
                    **PUBLIC,
                    **plugins,
                    **sf["settings"],
                    "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}",
                    "OPS_CONSOLE_URL": "https://console.kestrel.test",
                }
            )
        )
        api = stack.enter_context(agents(gateway_url=str(gw.base_url).rstrip("/"), env={**AUTH, **PUBLIC}))
        salesforce_on(gw, platform_api, bearer(signed_in(platform_api, "p.shah@harborpine.example"), "team_ops"), sf)
        # Lena Brandt holds the Chat user role: chat:run and her own threads, no skills:view. The viewer reads skills.
        lena = bearer(signed_in(platform_api, "l.brandt@harborpine.example"), "team_ops")
        yield Stack(api, as_role(platform_api, "admin"), as_role(platform_api, "viewer"), lena)
