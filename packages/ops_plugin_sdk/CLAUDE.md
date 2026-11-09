# ops_plugin_sdk: working rules

Status: current.

What an Ops AI plugin is built with: the `plugin.yaml` manifest (`ops-ai/plugin@2`), the `@tool` mark and the
`Context` a Python tool is handed, the loader, input formats and paging that tools-service also runs, and the
`opsai plugin` verbs. tools-service imports the same code to read manifests, check inputs, build requests and page, so a
plugin's own tests send the requests it will send in production. Imports and commands: [README.md](README.md). Package
rules and test commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

## What it owns

| Module | What it is |
|---|---|
| `manifest` | `Manifest`, `read`, `ManifestError`, `Tool`, `Setting`, `InputField`, sign-in declarations; `SCHEMA = "ops-ai/plugin@2"` (`src/ops_plugin_sdk/manifest.py:16`) |
| `plugin` | `Plugin` (`Plugin.beside(__file__)`) and `tool(access=...)` |
| `context` | `Context`, `Http`, `Response`, `Settings`: the only way a Python tool reaches its system |
| `errors` | `PluginError`, `BadInput`, `NeedsReconnect`, `RateLimited`, `EgressDenied`, `DeadlineExceeded`, mapped onto the gateway's failure codes |
| `formats` | Checks an input against its declared format and writes it into a query so it cannot change the query |
| `paging` | How a data tool reaches its next page, shared by tools-service and `opsai plugin test` |
| `loader` | `discover`: finds and validates installed plugins as tools-service does at start |
| `validate`, `versions` | Offline manifest and function checks; a version's tool declarations, digest and diff |
| `install`, `cli` | `opsai plugin validate|test|install|remove`, which the `opsai` command in `sdk/python` forwards here |
| `testing` | `call` and `Fake`: run one tool against a fake of its system |

## Contract with callers

- A plugin reaches only the hosts its manifest declares; a call elsewhere raises `EgressDenied`.
- A change to `manifest`, `formats` or `paging` changes what every installed plugin sends: tools-service
  (`ops_tools.plugins.host`, `ops_tools.plugins.executor`, `ops_tools.apps`) runs the same functions.
- No settings are read here; tools-service passes the merged settings in `Context.settings`.

Depends on nothing in the workspace. Depended on by tools-service and by `sdk/python`'s `plugin` extra.

## Run and test

| Task | Command |
|---|---|
| The suite | `make test PKG=packages/ops_plugin_sdk`, or `uv run pytest` in this folder |
| One file | `make test PKG=packages/ops_plugin_sdk T=tests/test_validate.py` |
| Check a plugin offline | `uv run opsai plugin validate plugins/ops_plugin_salesforce` prints `OK <id> <version>: ...` or each problem with its field |
| A plugin's own tests | `uv run opsai plugin test <plugin project folder>` |
| Lint, format, types | `uv run ruff check packages/ops_plugin_sdk`, `uv run ruff format --check packages/ops_plugin_sdk`, `uv run pyright packages/ops_plugin_sdk` |

Gaps: no pool job in `make verify` runs this suite ([../CLAUDE.md](../CLAUDE.md#what-make-verify-runs-for-packages)),
and `.importlinter` does not list `ops_plugin_sdk`, so its import contracts are unchecked.
`examples/plugins/vendor-onboarding/plugin.yaml` is written in the older proposed `ops-ai/plugin@1` format and
`opsai plugin validate` refuses it.

## Reference docs

- [docs/guide/plugins.md](../../docs/guide/plugins.md): how to write, test and install a plugin
- [plugins/README.md](../../plugins/README.md): the install's plugins folder
- `src/ops_plugin_sdk/loader.py:1` cites `plugin-architecture.html` section 03, which is not in this repository
