# Build a plugin

Status: current. What is not built yet is listed under Limits.

When a system your team uses has no App in the catalog, you can bring it as a plugin: one package that says how a team
signs in, which tools agents may call, and what knowledge it can feed a knowledge base. Most plugins are a single
manifest file with no code, because each tool is a request template the gateway runs.

## A plugin in four files

This one signs in with an API key and has one read tool.

```
ticketdesk/
  pyproject.toml
  src/ops_plugin_ticketdesk/__init__.py
  src/ops_plugin_ticketdesk/plugin.yaml
  tests/test_tools.py
```

The manifest is the plugin:

```yaml
schema: ops-ai/plugin@2
id: acme.ticketdesk
title: Ticket desk
version: 0.1.0
sdk: "1"

connection:
  kinds: [api_key]
  api_key: { placement: header, name: X-Api-Key }
  sign_in: [team]
  health_check: { path: /me }

settings:
  api_url: { type: string, default: "https://api.ticketdesk.example", title: API address }

egress: ["{api_url}"]
endpoint: "{api_url}"

tools:
  - name: get_ticket
    title: Get a ticket
    description: One ticket by its number, with its subject and status
    access: read
    input:
      number: { type: integer, description: "The ticket number, such as 4182" }
    request:
      method: GET
      path: "/tickets/{number}"
```

The package file names the entry point Ops AI finds the plugin by, and the module loads the manifest beside it:

```toml
[project]
name = "ops-plugin-ticketdesk"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = ["ops-plugin-sdk"]

[project.entry-points."ops_ai.plugins"]
ticketdesk = "ops_plugin_ticketdesk:plugin"
```

```python
from ops_plugin_sdk import Plugin

plugin = Plugin.beside(__file__)
```

## Check, test and install it

```bash
opsai plugin validate ./ticketdesk
opsai plugin test ./ticketdesk
opsai plugin install ./ticketdesk
```

Expected:

```text
OK acme.ticketdesk 0.1.0: 1 tools, 0 knowledge sources, 0 templates
1 passed
```

`install` validates the plugin again and copies it into the install's plugins folder; a plugin that fails validation
is not copied. Restart Ops AI's services after installing. The App then shows in **Data Gateway › Apps** for every
team, and a team admin turns it on as any other App. How an operator installs and pins plugins on Compose and
Kubernetes is in [Install and turn on a plugin](../plugins-install.md).

## What a manifest holds

| Part | What it says |
|---|---|
| Connection | The sign-in kinds it accepts, whose account calls use (team, person, or both), and a health check path. See [Sign in with a key or password](authentication.md#sign-in-with-a-key-or-password), [OAuth](authentication.md#sign-in-with-oauth) and [a certificate](authentication.md#sign-in-with-a-certificate) |
| Settings | Values a team fills in, such as an API address; a setting can be fixed for every team by the install |
| Egress | The hosts the plugin's calls may reach. No other host is reachable, and private and metadata addresses stay refused |
| Tools | Each tool's inputs, whether it reads or writes, and its request. Paging and shaping the answer are data too |
| Knowledge sources | Listing and reading tools a knowledge base syncs from, with a schedule |
| Templates | Agents, skills and workflows a team can add as its own copies |

Python is needed only where a manifest cannot say what a tool does, such as several requests in a row or a binary
answer. The [full manifest reference](../plugins.md) lists every field.

## Limits

- Python tools run inside the tools service, not in a separate process.
- A plugin cannot yet declare inbound webhooks (planned).
- An install's plugins and locked settings have no console page; they are install config.

## Next

<!-- site: cards -->
- [Plugin manifest reference](../plugins.md): every field, paging, sign-in steps and updates.
- [Integrations](overview.md): the apps Ops AI ships with, as worked examples.
