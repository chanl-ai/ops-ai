# Built-in plugins

The apps and template packs Ops AI ships with. Every stack and image loads each folder here at start, with no fetch or
sync step (`builtin_plugins_dir` in `packages/ops_service_kit/src/ops_service_kit/settings.py`; the image sets
`OPS_BUILTIN_PLUGINS_DIR=/app/builtin-plugins`).

| Folder | Plugin | What it brings |
|---|---|---|
| `ops_plugin_core` | opsai.core | Task types and case types |
| `ops_plugin_starters` | opsai.starters | Starter skills; `THIRD_PARTY_NOTICES.txt` names the sources they were adapted from |
| `ops_plugin_salesforce` | opsai.salesforce | Salesforce tools, knowledge source, case helper agent and triage workflow |
| `ops_plugin_github` | opsai.github | GitHub tools |
| `ops_plugin_sharepoint` | opsai.sharepoint | SharePoint tools and knowledge source |
| `ops_plugin_confluence` | opsai.confluence | Confluence tools and knowledge source |
| `ops_plugin_web` | opsai.web | The website knowledge source |

Each was copied from github.com/chanl-ai/ops-ai-plugins at the commit `deploy/plugins.json` pinned, checked against its
pinned sha256. All are Apache-2.0, as Ops AI is. Their tests stay in that repository.

A folder of the same package name in the plugins folder (`OPS_PLUGINS_DIR`, filled by `make plugins-sync` or
`opsai plugin install`) replaces the built-in one, and `make up` names each such folder. `deploy/plugins.json` now pins
only outside plugins an install adds.

How plugins load, and how a team turns one on: [docs/architecture/integrations.md](../docs/architecture/integrations.md).
Templates and copies: [docs/architecture/templates.md](../docs/architecture/templates.md).
