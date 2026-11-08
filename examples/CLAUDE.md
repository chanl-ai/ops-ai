# Examples: working rules

Status: current.

Copyable folders, one idea each, in tracks (`chat`, `knowledge`, `tools`, `agents`, `workflows`, `compositions`,
`plugins`). They are repository data that a developer copies and runs against a stack through the public surfaces
(the console, `ops`, the Python and TypeScript SDKs); the product does not list them. Landing page:
[docs/guide/build-with-ops-ai.md](../docs/guide/build-with-ops-ai.md). Rules shared with every folder:
[Working in one folder](../CLAUDE.md#working-in-one-folder).

## A folder's shape

| File | Holds |
|---|---|
| `example.yaml` | The manifest, checked against `example.schema.json`: `id`, `title`, `track`, `status` (`built`, `partial`, `planned`), `difficulty`, `outcome`, `capabilities` (each with its own status), `entrypoint`, `resources`, `fixtures`, `expected`, `surfaces` |
| `resources/` | What the example installs: a workflow (`workflow.yaml`, checked against `workflow.schema.json`), an agent, a tool, knowledge pages |
| `fixtures/`, `expected/` | Inputs and the outputs a run must match |
| `setup.py` | Installs the resources into a team on a running stack and writes `.bindings.json` and `.ops-profile.json` (both ignored by git) |
| `test_example.py`, `test_example.mjs` | The same check through the Python and the TypeScript SDK |
| `README.md` | The commands, top to bottom, and a link to the lesson |

Shared setup is `_lib/folder.py`; a helper there is named for the example it serves (`CITE_HANDBOOK_FOLDER`).

## Commands

| Task | Command (repo root) |
|---|---|
| Every manifest, schema and generated coverage page in step (offline) | `uv run python scripts/check_examples.py --check` (part of `make docs-verify`) |
| Rewrite the coverage pages after a manifest change | `uv run python scripts/check_examples.py` (writes `docs/guide/workflow-example-coverage.md`, `agent-example-coverage.md`, `developer-surface-coverage.md`) |
| Run one example on the live stack | its README: `uv run python examples/<track>/<slug>/setup.py`, then `uv run pytest examples/<track>/<slug>/test_example.py` and `node examples/<track>/<slug>/test_example.mjs`; `setup.py` creates records in the stack's team |
| Lint a script you changed | `uv run ruff check examples/<track>/<slug>`: a plain `ruff check` skips `examples/` (`extend-exclude` in `pyproject.toml`), a path named on the command line is checked with the relaxed `examples/**` rules |

## Rules

| Rule | Detail |
|---|---|
| Public surfaces only | An example calls `ops_ai`, `@chanl-ai/ops-ai` or `ops`, never a service's code or a private route; `check_examples.py` refuses a Python import outside `ops_ai`, the standard modules it lists and the example's own files (`scripts/check_examples.py:29`) |
| Status is honest | A capability or surface marked `built` runs today; anything else is `partial` or `planned` |
| No catalogue command | Examples are copied, not listed by the product |
