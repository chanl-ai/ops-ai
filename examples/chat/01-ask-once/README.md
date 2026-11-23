# Ask once

Send one message to a published agent and read the reply.

```python
from ops_ai import OpsAI

ops = OpsAI()
agent = next(a for a in ops.agents.list() if a.get("status") == "published")
print(ops.agents.chat(agent["id"], "What documents open a business account?")["reply"])
```

```ts
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI();
let agent;
for await (const row of ops.agents.list()) {
  if (row.status === 'published') {
    agent = row;
    break;
  }
}
const reply = await ops.agents.chat(agent.id, 'What documents open a business account?');
console.log(reply.reply);
```

```bash
AGENT=$(opsai agents list --json | jq -r '.[] | select(.status=="published") | .id' | head -1)
opsai agents chat "$AGENT" --message "What documents open a business account?"
```

Same files in this folder: `ask_once.py`, `ask_once.mjs`, `ask_once.sh`.

Lesson: [docs/guide/build-with-ops-ai.md](../../../docs/guide/build-with-ops-ai.md).

<details>
<summary>Run the folder check</summary>

```bash
uv run python examples/chat/01-ask-once/setup.py
uv run pytest examples/chat/01-ask-once/test_example.py
```

Capability id: `chat.ask-once`.
</details>
