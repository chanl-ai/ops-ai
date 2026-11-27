# Build a plugin

Status: current.

Your team uses a system that has no app in the catalog, such as a ticket desk, and every agent that needs it would otherwise
carry its own copy of the request details and its own key. A plugin brings the system in once. It is one package that says
how a team signs in, which tools agents may call, and what knowledge a knowledge base can take from it. Most plugins are a
single manifest file with no code, because each tool is a request template that the gateway runs. If you skip the plugin
and build a tool on a custom app instead, only your team can use it. A plugin can be installed for every team.

## The plan

<!-- site: steps -->
1. **Write the manifest.** It names the sign-in, the settings, the hosts the plugin may reach and the tools.
2. **Check and test it.** `validate` reads the manifest offline, and `test` runs your tests against a fake of the system.
3. **Install it.** `install` copies the plugin into your install's plugins folder.
4. **Turn the app on.** After a restart, the app shows in **Data Gateway › Apps** for every team, and a team admin turns it
   on like any other app.

## A plugin in four files

This plugin signs in with an API key and has one read tool.

```
ticketdesk/
  pyproject.toml
  src/ops_plugin_ticketdesk/__init__.py
  src/ops_plugin_ticketdesk/plugin.yaml
  tests/test_tools.py
```

The manifest is the plugin. It lives in `src/ops_plugin_ticketdesk/plugin.yaml`:

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

The package file names the entry point that Ops AI finds the plugin by, and the module loads the manifest beside it.

```toml
[project]
name = "ops-plugin-ticketdesk"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = ["ops-plugin-sdk"]

[project.entry-points."ops_ai.plugins"]
ticketdesk = "ops_plugin_ticketdesk:plugin"

[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ops_plugin_ticketdesk"]
```

```python
from ops_plugin_sdk import Plugin

plugin = Plugin.beside(__file__)
```

`tests/test_tools.py` calls each tool against a fake of the system. [The plugin manifest reference](../plugins.md) has a
worked test for this plugin.

## Check, test and install it

The plugin commands come from the plugin kit, which is a separate package installed beside the command line (`ops-ai[plugin]`).
From a checkout of Ops AI, run them with `uv run`.

```bash
uv run opsai plugin validate ./ticketdesk
uv run opsai plugin test ./ticketdesk
uv run opsai plugin install ./ticketdesk
```

Expected output from `validate` and `test`:

```text
OK acme.ticketdesk 0.1.0: 1 tools, 0 knowledge sources, 0 templates
1 passed
```

`install` validates the plugin again and copies it into the install's plugins folder, and a plugin that fails validation
is not copied. Restart the tools and knowledge services after installing. The app then shows in **Data Gateway › Apps** for
every team, and a team admin turns it on as any other app. [Install and turn on a plugin](../plugins-install.md) shows how
an operator installs and pins plugins on Compose and Kubernetes.

## What a manifest holds

| Part | What it says |
|---|---|
| Connection | The sign-in kinds it accepts, whose account calls use (team, person or both), and a health check path. See [Sign in with a key or password](sign-in-keys.md), [OAuth](sign-in-oauth.md) and [a certificate](sign-in-certificates.md) |
| Settings | Values that a team fills in, such as an API address. An install can fix a setting for every team |
| Egress | The hosts the plugin's calls may reach. No other host is reachable, and private and metadata addresses stay refused |
| Tools | Each tool's inputs, whether it reads or writes, and its request. Paging and shaping the answer are data too |
| Knowledge sources | Listing and reading tools that a knowledge base syncs from, with a schedule |
| Templates | Agents, skills and workflows that a team can add as its own copies |

Python is needed only where a manifest cannot say what a tool does, such as several requests in a row or a binary answer.
The [full manifest reference](../plugins.md) lists every field.

## Limits

- Python tools run inside the tools service, not in a separate process.
- A plugin cannot yet declare inbound webhooks. This is planned.
- An install's plugins and locked settings have no console page. They are install config.

## Next

<!-- site: cards -->
- [Plugin manifest reference](../plugins.md): every field, paging, sign-in steps and updates.
- [Integrations](overview.md): the apps that Ops AI ships with, as worked examples.
