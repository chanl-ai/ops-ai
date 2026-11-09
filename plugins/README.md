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
| Check a plugin offline | `uv run opsai plugin validate <folder>`; `uv run opsai plugin test <folder>` also runs its tests |
| Put one in, or take it out | `uv run opsai plugin install <folder>`, `uv run opsai plugin remove <id>` |
| Load the change on the stack | `make restart SVC=tools`, then `make logs SVC=tools FOLLOW=0` for any `plugin_failed` line |
| Plugins baked into the images | `deploy/plugins.json` (`deploy/images/bake_plugins.py`) |
| Get exactly those on the laptop | `make plugins-sync` (hand copies move to `plugins.bak-<date>/`); `make box-up` runs it in a box |
| Move the pins to the plugins repository's main | `make plugins-bump` (or `REF=<sha>`); prints old and new commit per plugin |
| Develop a plugin from a working copy | `make plugins-sync PLUGINS_DEV=../ops-ai-plugins` links its plugin folders; run it without `PLUGINS_DEV` to go back to the pinned ones |

How a plugin is built: `packages/ops_plugin_sdk/` and [docs/guide/plugins.md](../docs/guide/plugins.md).
