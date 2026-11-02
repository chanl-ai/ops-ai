# Agents

Status: current.

An agent is a reviewed model configuration. It chooses steps inside allowed tools, knowledge, skills, guardrails and budgets. A workflow remains a typed graph. The two meet only through the public bridges on [build-with-ops-ai.md](build-with-ops-ai.md).

## Lifecycle

```bash
ops agents validate resources/agent.yaml
ops agents apply resources/agent.yaml
ops agents publish <id> --note "Ready"
ops agents chat <id> --message "What documents open a business account?"
ops agents test <id> --message "What documents open a business account?"
```

```python
from ops_ai import OpsAI

ops = OpsAI()
ops.agents.apply("resources/agent.yaml")
ops.agents.chat("ag_guide", "What documents open a business account?")
```

`ops agents eval` scores dataset cases on a published agent. Stream, wait and background runs stay **Planned** until the Agent Run API ships.

## Examples

Foundation chat, search and the read tool come first. These folders reuse those resources.

| Folder | Outcome | Status |
|---|---|---|
| `01-answer-from-instructions` | Ask one question | Built |
| `02-cite-the-handbook` | Answer with a citation | Built |
| `03-look-up-a-customer` | Call the read tool | Built |
| `04-draft-a-note-for-approval` | Write waits for approval | Built |
| `05-follow-a-checklist` | Skills and a blocked topic | Built |
| `06-narrow-one-conversation` | Thread overrides | Built |
| `11-eval-a-known-customer` | Score A3 look-up cases | Built |
| `07-start-customer-hold` | workflow tool from chat | Built |
| `08-run-in-three-modes` | Start stream, wait and background | Built |
| `09-delegate-to-a-specialist` | Agent as a tool | Built |
| `10-morning-held-wires` | Scheduled job | Built |

Coverage: [agent-example-coverage.md](agent-example-coverage.md).
