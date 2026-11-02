# plugins

The install's one plugins folder. Each plugin is a folder here: its package folder (holding `plugin.yaml`) or its
whole project (`src/<package>/plugin.yaml`). tools-service and kb-service load every plugin in it when they start; a
broken one is reported at `GET /v1/plugins` and the rest still load. An empty folder means the install has no plugins.

Locally this is the repo's `plugins/`; in Docker and Kubernetes it is a mounted volume named by `OPS_PLUGINS_DIR`.
Everything here except this README is ignored by git.

Guide: [docs/guide/plugins.md](../docs/guide/plugins.md).
