# plugins

The install's one plugins folder. Each plugin is a folder here: its package folder (holding `plugin.yaml`) or its
whole project (`src/<package>/plugin.yaml`). tools-service loads every plugin in it when it starts
(`services/tools-service/src/ops_tools/plugins/host.py`); a broken one is logged as `plugin_failed` in the
tools-service log and the rest still load. kb-service reaches a plugin's knowledge sources through tools-service. An
empty folder means the install has no plugins.

Locally this is the main checkout's `plugins/` (`plugins_dir` in `ops_service_kit` settings); in Docker and Kubernetes
it is a mounted volume named by `OPS_PLUGINS_DIR`. Everything here except this README is ignored by git, so a plugin's
source lives in its own repository or under `examples/plugins/`.

## Working here

| Task | Command (repo root) |
|---|---|
| Check a plugin offline | `uv run ops plugin validate <folder>`; `uv run ops plugin test <folder>` also runs its tests |
| Put one in, or take it out | `uv run ops plugin install <folder>`, `uv run ops plugin remove <id>` |
| Load the change on the stack | `make restart SVC=tools`, then `make logs SVC=tools FOLLOW=0` for any `plugin_failed` line |
| Plugins baked into the images | `deploy/plugins.json` (`deploy/images/bake_plugins.py`) |

How a plugin is built: `packages/ops_plugin_sdk/` and [docs/guide/plugins.md](../docs/guide/plugins.md).
