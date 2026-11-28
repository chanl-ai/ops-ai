# Build a plugin

Status: current.

Your team uses a system that has no app in the catalog, such as a ticket desk, and every agent that needs it would otherwise
carry its own copy of the request details and its own key. A plugin brings the system in once. It is one package that says
how a team signs in, which tools agents may call, and what knowledge a knowledge base can take from it. Most plugins are a
single manifest file with no code, because each tool is a request template that the gateway runs.

<!-- site: compare caption="A tool on a custom app, and a plugin" -->
- **Tool on a custom app**: Built on **Add custom app** for your own team.
  - **Who can use it**: Only your team
  - **Made of**: A tool you build in the console
- **Plugin**: Installed once for the whole install.
  - **Who can use it**: Every team, once its admin turns the app on
  - **Made of**: One manifest, usually with no code

## From manifest to a working app

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

The manifest describes everything the plugin does, and it lives in `src/ops_plugin_ticketdesk/plugin.yaml`:

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

`tests/test_tools.py` calls each tool against a fake of the system. Copy the worked test for this plugin from [Building a
plugin](../plugins.md), because `test` has nothing to run without it.

## Check, test and install it

The plugin commands come from the plugin kit, a separate package installed beside the command line with `ops-ai[plugin]`.
From a checkout of Ops AI, run them with `uv run`, as below. Without the kit, `opsai plugin` stops with an install hint.

```bash
uv run opsai plugin validate ./ticketdesk
uv run opsai plugin test ./ticketdesk
uv run opsai plugin install ./ticketdesk --into <your plugins folder>
```

Expected output from `validate` and `test`:

```text
OK acme.ticketdesk 0.1.0: 1 tools, 0 knowledge sources, 0 templates
1 passed
```

`install` validates the plugin again and copies it into the install's plugins folder, and a plugin that fails validation
is not copied. Restart tools-service and kb-service after installing, `install` copies into `./plugins` unless you pass `--into`, and `opsai plugin remove <id>` takes a plugin out again. The app then shows in **Data Gateway › Apps** for
every team, and a team admin turns it on as any other app. [Install and turn on a plugin](../plugins-install.md) shows how
an operator installs and pins plugins on Compose and Kubernetes.

## What a manifest holds

| Part | What it says |
|---|---|
| Connection | The sign-in kinds it accepts, whose account calls use (team, person or both), and a health check path. See [Sign in with a key or password](sign-in-keys.md), [OAuth](sign-in-oauth.md) and [a certificate](sign-in-certificates.md) |
| Settings | Values that a team fills in, such as an API address. An install can fix a setting for every team |
| Egress | The hosts the plugin's calls may reach, declared here or listed by a Security admin. No other host is reachable, and private and metadata addresses stay refused |
| Tools | Each tool's inputs, whether it reads or writes, and its request. Paging and shaping the answer are data too |
| Knowledge sources | Listing and reading tools that a knowledge base syncs from, with a schedule |
| Templates | Agents, skills and workflows that a team can add as its own copies |

Python is needed only where a manifest cannot say what a tool does, such as several requests in a row or a binary answer.
The [full manifest reference](../plugins.md) lists every field.

## What a plugin cannot do yet

- Python tools run inside the tools service, not in a separate process.
- A plugin cannot yet declare inbound webhooks. This is planned.
- The console has no page for an install's plugins or its locked settings, because they are set in the install config.

## Next

<!-- site: cards -->
- [Plugin manifest reference](../plugins.md): every field, paging, sign-in steps and updates.
- [Integrations](overview.md): the apps that Ops AI ships with, as worked examples.
