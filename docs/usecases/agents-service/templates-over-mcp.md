# List and install templates from an assistant

Status: current. Service: `agents-service`. Layers: sdk (Python; see Gaps).

In this example we will connect an assistant to the team's MCP address with the official MCP client, find the tools
`list_templates` and `install_template`, list the starter skills and install one as the person who signed in. It assumes
the starters pack is on for the team, Priya (admin) may create skills, and Maya (approver) may run tools but not create
skills.

| Use case | |
|---|---|
| Id | `uc-741` |
| Area | Agents |
| Runs | Python |
| Run it | `make usecase-test UC=uc-741 LAYER=sdk` |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| Priya, the team's admin | Admin | the `priya` profile |
| Maya, an approver | Approver | the `maya` profile |

## Before you start

The profile holds the team's MCP address and the token an outside assistant gets after the company sign-in (`mcpUrl`,
`mcpToken`). The sign-in is a browser flow, so the run does it before the first step.

```python tab="Python" tab-group="language"
import asyncio
import json
import os
from contextlib import asynccontextmanager

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import Implementation
from ops_ai import OpsAI

profiles = json.load(open(os.environ["OPS_CONFIG"]))["profiles"]
priya, maya = OpsAI(profile="priya"), OpsAI(profile="maya")
REF = "plugin:opsai.starters:doc-coauthoring"


@asynccontextmanager
async def assistant(who):
    """An assistant on the team's address, as the person who signed it in."""
    p = profiles[who]
    async with (
        httpx2.AsyncClient(headers={"Authorization": f"Bearer {p['mcpToken']}"}, timeout=30) as http,
        Client(streamable_http_client(p["mcpUrl"], http_client=http), client_info=Implementation(name="assistant", version="1.0"), cache=None) as c,
    ):
        yield c


async def call(who, name, args):
    async with assistant(who) as c:
        return await c.call_tool(name, args)


def team_skills():
    skills = priya.raw.agents.agents_list_skills()
    return [s["id"] for s in (skills["data"] if isinstance(skills, dict) else skills)]
```

## Steps

### 1. The assistant finds the template tools

```python tab="Python" tab-group="language"
async def names():
    async with assistant("priya") as c:
        return {t.name for t in (await c.list_tools()).tools}

assert {"list_templates", "install_template"} <= asyncio.run(names())
```

Expected: both tools are listed.

### 2. List the starter skills

```python tab="Python" tab-group="language"
listed = asyncio.run(call("priya", "list_templates", {"kind": "skill"}))
assert listed.is_error is False
assert any(r.get("id") == "doc-coauthoring" for r in listed.structured_content["templates"])
```

Expected: Doc co-authoring is returned.

### 3. A person who may not create skills is refused

```python tab="Python" tab-group="language"
before = team_skills()
refused = asyncio.run(call("maya", "install_template", {"resource": REF}))
assert refused.is_error is True
assert team_skills() == before
```

Expected: a tool error, and the team's skills are unchanged.

### 4. The admin installs it as herself

```python tab="Python" tab-group="language"
made = asyncio.run(call("priya", "install_template", {"resource": REF}))
assert made.is_error is False
record = made.structured_content["copy"]["recordId"]
assert record in team_skills()
```

Expected: the team's copy exists and is in its skills.

### 5. The copy names Priya as its maker

```python tab="Python" tab-group="language"
skills = priya.raw.agents.agents_list_skills()
row = next(s for s in (skills["data"] if isinstance(skills, dict) else skills) if s["id"] == record)
assert row["updatedBy"] == "p.shah@harborpine.example"
```

Expected: not the tools service that called agents-service for her.

## Gaps

| Product fix | Step | What the TypeScript SDK and the command line cannot do |
|---|---|---|
| A TypeScript tab needs an MCP client in the repo's tooling, and `opsai` needs a command that connects to the team's MCP address (`opsai mcp tools`, `opsai mcp call`) | 1 to 5 | Neither tab can list tools or call one on the team's MCP address; the run has no MCP client for TypeScript and `opsai` has no `mcp` area, so the page has Python tabs only |

## What proves it

Step 3 fails if install runs as the service and not as the signed-in person.

## Details

| | |
|---|---|
| Services the run starts | agents stack: platform-service, tools-service with the starters pack and the team MCP address, agents-service |
| Older script | `docs/usecases/agents-service/scripts/test-uc-741-mcp.py` |
