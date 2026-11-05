"""The service desk plugin uc-590's resource stories run on, written into a folder at the start of a run.

It brings one resource of each kind, a knowledge source, and one dependency between resources: the triage workflow's
agent step runs the plugin's own agent template, by its template id. The plugin is written per run, not kept as a
fixture folder, so a story can change a template on disk (its body is read on every listing) or start tools-service
on a later version that no longer ships a template. The knowledge tools are Python tools that answer two fixed
articles, so a sync needs no outside system.

`uv run python resources_desk.py <folder> [version]` writes it for a script that is not Python (the ui layer)."""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN = "test.resources"
SOURCE = f"plugin:{PLUGIN}"
# The package folder's name is the module tools-service imports the plugin as.
PACKAGE = "resources_desk"
AGENT, SKILL, WORKFLOW, DOCUMENT_TYPE = "ticket-helper", "close-ticket", "ticket-triage", "ticket-form"
KNOWLEDGE = "articles"
INSTRUCTIONS = "You help a service agent with one ticket. Read it with get_ticket and answer from the help articles."

MANIFEST = """\
schema: ops-ai/plugin@2
id: test.resources
title: Service desk
version: {version}
sdk: "1"
display:
  category: Service desk
  description: Tickets and help articles in a service desk.
connection:
  kinds: [none]
  sign_in: [team]
  health_check: {{ path: "/me" }}
settings:
  base_url: {{ type: string, title: Desk address, default: "https://api.servicedesk.test" }}
egress: ["{{base_url}}"]
endpoint: "{{base_url}}"
tools:
  - name: get_ticket
    title: Read a ticket
    access: read
    input: {{ id: {{ type: string, pattern: "^[A-Z0-9-]+$" }} }}
    request: {{ method: GET, path: "/tickets/{{id}}" }}
  - name: close_ticket
    title: Close a ticket
    access: write
    input: {{ id: {{ type: string, pattern: "^[A-Z0-9-]+$" }} }}
    request: {{ method: POST, path: "/tickets/{{id}}/close" }}
  - name: list_articles
    title: List help articles
    access: read
    knowledge: list_items
    function: resources_desk.kb:list_articles
    input:
      since: {{ type: string, required: false }}
      cursor: {{ type: string, required: false }}
  - name: get_article
    title: Read a help article
    access: read
    knowledge: get_item
    function: resources_desk.kb:get_article
    input: {{ id: {{ type: string }} }}
knowledge_sources:
  - {{ name: articles, title: Help articles, list: list_articles, get: get_article }}
templates:
  - kind: agent
    id: ticket-helper
    version: 1
    path: templates/ticket-helper.yaml
    requires:
      tools: [get_ticket, close_ticket]
      bind: [{{ knowledge_base: "Help articles" }}, {{ model_alias: chat }}]
{skill}  - kind: workflow
    id: ticket-triage
    version: 1
    path: templates/ticket-triage.yaml
    requires:
      tools: [get_ticket]
      resources: [ticket-helper]
  - kind: document_type
    id: ticket-form
    version: 1
    path: templates/ticket-form.yaml
"""

SKILL_ENTRY = """\
  - kind: skill
    id: close-ticket
    version: 1
    path: templates/close-ticket.yaml
    requires:
      tools: [close_ticket]
"""

KB = '''\
"""The service desk's help articles: two fixed items, so a knowledge sync needs no outside system."""

from __future__ import annotations

from typing import Any

from ops_plugin_sdk import Context, tool

ARTICLES = {
    "KB-1": ("Reset a password", "Open Settings, choose Security, then Reset password."),
    "KB-2": ("Replace a meter", "Book a visit; the engineer brings the new meter and reads the old one."),
}


@tool(access="read")
def list_articles(ctx: Context, since: str | None = None, cursor: str | None = None) -> dict[str, Any]:
    return {"items": [{"id": k, "title": t, "updated_at": "2026-10-01T09:00:00Z"} for k, (t, _) in ARTICLES.items()]}


@tool(access="read")
def get_article(ctx: Context, id: str) -> dict[str, Any]:
    title, body = ARTICLES[id]
    return {
        "id": id,
        "title": title,
        "updated_at": "2026-10-01T09:00:00Z",
        "mime": "text/plain",
        "encoding": "utf-8",
        "content": body,
        "url": f"https://help.servicedesk.test/{id}",
    }
'''

TEMPLATES = {
    "ticket-helper.yaml": f"""\
name: Ticket helper
role: Reads a ticket, explains it from the help articles, and closes it when the person asks
channels: [chat]
instructions: |-
  {INSTRUCTIONS}
""",
    "close-ticket.yaml": """\
name: Close a ticket politely
use_when: The person asks to close a ticket
instructions: |-
  Before closing a ticket, say what happens next and ask the person to confirm. Then close it.
""",
    # The agent step names the plugin's agent template by its id: the team's copy of the workflow can run only once
    # that agent is the team's too.
    "ticket-triage.yaml": """\
schemaVersion: 2
id: ticket_triage
name: Ticket triage
description: Reads a ticket and has the ticket helper suggest the next step.
nodes:
  - { id: start, type: ops.trigger.request, typeVersion: 1, name: Request, parameters: { inputSchema: { type: object, required: [ticketId], properties: { ticketId: { type: string, title: Ticket } } } } }
  - { id: read, type: ops.action.tool, typeVersion: 1, name: Read the ticket, parameters: { operation: resources_get_ticket, input: { id: "$.input.ticketId" } } }
  - { id: suggest, type: ops.ai.agent, typeVersion: 1, name: Suggest the next step, parameters: { agent: ticket-helper, prompt: "Suggest the next step for this ticket.", input: { ticket: "$.nodes.read.out" }, outputSchema: { type: object, properties: { next: { type: string } }, required: [next] } } }
  - { id: done, type: ops.flow.end, typeVersion: 1, name: Suggested, parameters: { outcome: suggested } }
  - { id: failed, type: ops.flow.end, typeVersion: 1, name: Not read, parameters: { outcome: not_read, result: failed } }
connections:
  - { from: { node: start, port: payload }, to: { node: read, port: in } }
  - { from: { node: read, port: ok }, to: { node: suggest, port: in } }
  - { from: { node: read, port: refused }, to: { node: failed, port: in } }
  - { from: { node: read, port: error }, to: { node: failed, port: in } }
  - { from: { node: suggest, port: ok }, to: { node: done, port: in } }
  - { from: { node: suggest, port: error }, to: { node: failed, port: in } }
""",
    "ticket-form.yaml": """\
name: Ticket form
description: A service request form, with its ticket number and the date it was raised
fields:
  - { key: ticket_number, label: Ticket number, type: text, required: true, keyField: true }
  - { key: raised_on, label: Raised on, type: date, required: true }
""",
}


def write_desk(parent: Path, *, version: str = "0.1.0", with_skill: bool = True) -> Path:
    """Writes the plugin into `parent/resources_desk` and returns that folder, for OPS_PLUGIN_PATHS. `with_skill`
    False writes a later version that no longer ships the skill."""
    folder = parent / PACKAGE
    (folder / "templates").mkdir(parents=True, exist_ok=True)
    (folder / "__init__.py").write_text("from ops_plugin_sdk import Plugin\n\nplugin = Plugin.beside(__file__)\n")
    (folder / "kb.py").write_text(KB)
    (folder / "plugin.yaml").write_text(MANIFEST.format(version=version, skill=SKILL_ENTRY if with_skill else ""))
    for name, body in TEMPLATES.items():
        (folder / "templates" / name).write_text(body)
    return folder


def change_agent_instructions(folder: Path, instructions: str) -> None:
    """The plugin's agent template changes on disk at the same version, as a plugin's own fix would."""
    path = folder / "templates" / "ticket-helper.yaml"
    path.write_text(path.read_text().replace(INSTRUCTIONS, instructions))


if __name__ == "__main__":
    print(write_desk(Path(sys.argv[1]), version=sys.argv[2] if len(sys.argv) > 2 else "0.1.0"))
