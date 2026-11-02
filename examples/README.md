# Examples

Copyable folders that teach one idea each. They are repository data. The product does not list them.

The landing page is [docs/guide/build-with-ops-ai.md](../docs/guide/build-with-ops-ai.md). Coverage is generated into [docs/guide/workflow-example-coverage.md](../docs/guide/workflow-example-coverage.md).

| Track | Start |
|---|---|
| Chat | `examples/chat/01-ask-once/` |
| Knowledge | `examples/knowledge/01-search-a-page/` |
| Tool | `examples/tools/01-find-a-customer/` |
| Agent | `examples/agents/01-answer-from-instructions/` |
| Workflow | `examples/workflows/01-normalize-a-request/` |
| Composition | `examples/compositions/01-workflow-asks-agent/` |

Shared setup lives in `_lib/folder.py`. Helpers name the example they use (`CITE_HANDBOOK_FOLDER`, `NORMALIZE_REQUEST_ID`), not a board slice. Copy a folder, then pass it to `ops workflows` or `ops agents`. Do not add an examples catalog command.
