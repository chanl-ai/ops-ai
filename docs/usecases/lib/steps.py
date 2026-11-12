"""Named setup steps for a Python use case script, the twin of packages/usecase-runner/src/steps.ts.

Each step calls the public Python SDK (sdk/python), so a script that uses them proves the SDK can do what a person's
tools do. A step the SDK cannot do is a product gap: file a card and show the step as open in the use case; do not add
a raw HTTP call here. The table of steps is in docs/usecases/README.md ("Shared steps").
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from usecase_harness import (
    AGENTS_PORT,
    DOCUMENTS_PORT,
    FILES_PORT,
    INVITED_PASSWORD,
    KB_PORT,
    PLATFORM_PORT,
    ROOT,
    TOOLS_PORT,
)

sys.path.insert(0, str(ROOT / "sdk" / "python" / "src"))
from ops_ai import OpsAI

PASSWORD = "northfield-demo"
# The dev seed's people (services/platform-service/seed), all in team_ops.
JAMES = "j.richardson@harborpine.example"
PRIYA = "p.shah@harborpine.example"
MAYA = "m.okafor@harborpine.example"
SAM = "s.adeyemi@harborpine.example"
# The workspace-wide admin: the only person who creates teams.
PLATFORM_ADMIN = "w.kamau@harborpine.example"


def _here(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _services() -> dict[str, str]:
    ports = {
        "platform": PLATFORM_PORT,
        "agents": AGENTS_PORT,
        "tools": TOOLS_PORT,
        "kb": KB_PORT,
        "files": FILES_PORT,
        "documents": DOCUMENTS_PORT,
    }
    return {name: _here(port) for name, port in ports.items() if port}


def sign_in_as(email: str, *, team: str | None = "team_ops", password: str = PASSWORD) -> OpsAI:
    """Signs a seeded person in through the SDK; the client acts in `team` (None: in none, for the workspace admin)."""
    return OpsAI.sign_in(
        email, password, base_url=_here(PLATFORM_PORT), services=_services(), **({"team": team} if team else {})
    )


class Made:
    """Everything a run made, so a script can remove it at the end: `made.add("agent", lambda: ...)`, then
    `made.clean_up()`. Cleanup runs in reverse order and every failure is reported together."""

    def __init__(self) -> None:
        self._undo: list[tuple[str, Callable[[], Any]]] = []

    def add(self, what: str, run: Callable[[], Any]) -> None:
        self._undo.append((what, run))

    def clean_up(self) -> None:
        failed: list[str] = []
        while self._undo:
            what, run = self._undo.pop()
            try:
                run()
            except Exception as e:  # report every leftover, not only the first
                failed.append(f"{what}: {e}")
        if failed:
            raise RuntimeError(f"clean up left {len(failed)} behind: {'; '.join(failed)}")


def make_team(
    admin: OpsAI,
    name: str,
    *,
    first_admin: str,
    members: list[tuple[str, str]] | None = None,
    made: Made | None = None,
) -> tuple[dict[str, Any], dict[str, OpsAI]]:
    """A team made the way a workspace admin makes one: `admin` creates it with `first_admin` (a seeded person's
    email), who invites each (email, role) in `members`; each accepts with a name and INVITED_PASSWORD. Returns the
    team and a client per member, acting in the team. Raises on any refusal."""
    team = admin.raw.platform.teams_create_team({"name": name, "admin": first_admin})
    if made:
        # The platform deletes a team only 30 days after it is archived, so archived is as clean as a run can leave it.
        made.add(f"team {name}", lambda: admin.raw.platform.teams_archive_team(team["id"]))
    # The workspace admin is not a member of the team it makes; the team's first admin invites the others.
    in_team = sign_in_as(first_admin, team=team["id"])
    people: dict[str, OpsAI] = {}
    for email, role in members or []:
        sent = in_team.raw.platform.members_invite_members({"emails": [email], "role": role})
        invites = sent.get("invites") or []
        if not invites or not invites[0].get("token"):
            raise RuntimeError(f"inviting {email} as {role} returned no invitation")
        person = email.split("@", maxsplit=1)[0].replace(".", " ").title()
        session = in_team.raw.platform.invites_accept_invite(
            invites[0]["token"], {"name": person, "password": INVITED_PASSWORD}
        )
        people[email] = OpsAI(
            base_url=_here(PLATFORM_PORT),
            services=_services(),
            team=team["id"],
            access_token=session["token"],
        )
    return team, people


def add_knowledge_base(
    ops: OpsAI, name: str, *, owner: str, items: list[dict[str, str]], made: Made | None = None
) -> tuple[str, str]:
    """A knowledge base with one push source holding `items` (each indexed before this returns, as the push route
    does). `owner` is the email of the person who answers for it. Returns (knowledge base id, source id)."""
    base = ops.raw.kb.knowledge_bases_create_knowledge_base({"name": name, "owner": owner})
    if made:
        made.add(f"knowledge base {name}", lambda: ops.raw.kb.knowledge_bases_remove_knowledge_base(base["id"]))
    source = ops.raw.kb.sources_create_source({"type": "push", "name": f"{name} feed", "kbIds": [base["id"]]})
    if made:
        made.add(f"source of {name}", lambda: ops.raw.kb.sources_remove_source(source["id"]))
    for item in items:
        ops.raw.kb.sources_put_item(source["id"], item)
    return base["id"], source["id"]


def publish_agent(
    ops: OpsAI,
    name: str,
    *,
    role: str,
    model: str | None = None,
    instructions: str | None = None,
    made: Made | None = None,
) -> tuple[str, int]:
    """An agent created and sent for publish; on a stack that auto-approves (the default) it is live when this
    returns. Without `model` it uses the first chat alias the stack offers, since the aliases differ between stacks.
    Returns (agent id, published version)."""
    alias = model or next(iter(ops.raw.agents.agents_list_model_aliases()), {}).get("name")
    if not alias:
        raise RuntimeError("the stack offers no model alias to give the agent")
    agent = ops.agents.create({"name": name, "role": role, "model": alias, "instructions": instructions})
    if made:
        made.add(f"agent {name}", lambda: ops.raw.agents.agents_delete_agent(agent["id"]))
    version = agent.get("draftVersion") or agent.get("version") or 1
    ops.agents.publish(agent["id"], note="Published by the use case", version=version)
    return agent["id"], version


def run_workflow(
    ops: OpsAI, workflow_id: str, input: dict[str, Any] | None = None, *, timeout: float = 600.0
) -> dict[str, Any]:
    """Starts a run of a workflow's current version and waits until it ends or stops at a human task (`taskId`)."""
    started = ops.runs.start(workflow_id, input=input or {})
    return ops.runs.wait(started["runId"], timeout=timeout)
