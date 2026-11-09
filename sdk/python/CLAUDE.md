# Python SDK: working rules

Status: current.

The `ops-ai` package (import `ops_ai`): `OpsAI` and `AsyncOpsAI` over the public API, and the `opsai` command line.
Shared SDK rules, the generator and every command: [../CLAUDE.md](../CLAUDE.md). User guide:
[docs/sdk/python.md](../../docs/sdk/python.md).

| Path | Holds |
|---|---|
| `src/ops_ai/_generated/` | Written by `sdk/generate.py`; never edited |
| `src/ops_ai/_client.py` | `OpsAI`, `AsyncOpsAI`, `Raw`, the nouns (`Runs` and the rest) with `list`, `get`, `create`, `wait`, `stream` |
| `src/ops_ai/_agents.py`, `_workflows.py`, `_words.py` | Agents, workflows (`WorkflowCheck`), apps, credentials, accounts, tools, resources, usage |
| `src/ops_ai/_transport.py`, `_config.py`, `errors.py` | HTTP, the profile and env (`OPS_BASE_URL`, `OPS_API_KEY`, `OPS_TEAM`), the error classes |
| `src/ops_ai/_chat.py`, `_models.py` | The chat screen's `/v1/chat/*` routes and models-service's provider keys and connections, which the generated layer lacks |
| `src/ops_ai/cli.py`, `_cli/` | `opsai login`, `workflows`, `agents`, `resources`, `chat`, `kb`, `apps`, `tools`, `runs`, `tasks`, `cases`, `files`, `documents`, `people`, `models`, `memories`, `test-data`; `opsai plugin` forwards to `packages/ops_plugin_sdk`. The root's make targets call these ([make/CLAUDE.md](../../make/CLAUDE.md)) |
| `tests/` | Unit tests on fake transports; no stack |
| `examples/seed_team.py` | Seeds a fresh team on the local stack; `make sdk-check` runs it |

| Task | Command (repo root) |
|---|---|
| Tests | `uv run --isolated --quiet --with pytest --with-editable sdk/python pytest -q sdk/python/tests` |
| One test file | the same with `sdk/python/tests/test_cli.py` |
| Lint and format | `uv run ruff check sdk/python` and `uv run ruff format --check sdk/python` |
