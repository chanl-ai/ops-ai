# Examples

Copyable folders that teach one idea each. They are repository data. The product does not list them.

**Capability registry:** edit [`capabilities.yaml`](capabilities.yaml) to register a capability (id, guide, folder,
status). `uv run python scripts/check_examples.py` refreshes [`registry.json`](registry.json) for
`apps/docs` / opsai.chanl.ai deep links. Schema: [`capability.schema.json`](capability.schema.json).

The landing page is [docs/guide/build-with-ops-ai.md](../docs/guide/build-with-ops-ai.md). Coverage is generated into [docs/guide/workflow-example-coverage.md](../docs/guide/workflow-example-coverage.md).

| Track | Start |
|---|---|
| Chat | `examples/chat/01-ask-once/` (`chat.ask-once`) |
| Skill | `examples/skills/01-publish-and-pick/` (`skill.publish-and-pick`) |
| Knowledge | `examples/knowledge/01-search-a-page/` |
| Tool | `examples/tools/01-find-a-customer/` |
| Agent | `examples/agents/01-answer-from-instructions/` |
| Workflow | `examples/workflows/01-normalize-a-request/` |
| Composition | `examples/compositions/01-workflow-asks-agent/` |

Shared setup lives in `_lib/folder.py`. Helpers name the example they use (`CITE_HANDBOOK_FOLDER`, `NORMALIZE_REQUEST_ID`), not a board slice. Copy a folder, then pass it to `opsai workflows` or `opsai agents`. Do not add an examples catalog command.
