# ops_plugin_sdk

The plugin kit: what a plugin package imports, and the `opsai plugin` commands that check, test and install it.
tools-service uses the same code to read manifests, check inputs, build requests and page, so a plugin's tests send
the requests it will send. How to write a plugin: [docs/guide/plugins.md](../../docs/guide/plugins.md).

| Import | What it is |
|---|---|
| `Plugin.beside(__file__)` | The plugin object, from the `plugin.yaml` next to the package's `__init__.py` |
| `tool(access=...)` | Marks a Python tool function; its first parameter is a `Context` |
| `Context` | `ctx.settings` and `ctx.http`, the only way a Python tool reaches its system |
| `BadInput`, `NeedsReconnect`, `RateLimited`, `EgressDenied` | What a Python tool raises, and what a call outside the plugin's hosts raises |
| `ops_plugin_sdk.testing.call`, `Fake` | Runs one tool against a fake of the system as tools-service runs it |

| Command (from an ops-ai checkout) | What it does |
|---|---|
| `uv run opsai plugin validate <folder>` | Checks the manifest and its functions; prints `OK <id> <version>: ...` or each problem with its field |
| `uv run opsai plugin test <folder>` | Validates, then runs the plugin's own pytest suite with its `src/` on the path |
| `uv run opsai plugin install <folder>` | Validates, then copies the package into the install's plugins folder (`--into` names another) |
| `uv run opsai plugin remove <id>` | Takes it out of the plugins folder |

Run the kit's own tests with `make test PKG=packages/ops_plugin_sdk` from the root, or `uv run pytest` in this folder.
