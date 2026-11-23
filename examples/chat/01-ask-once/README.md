# Ask once

**Goal.** Send one message to a published agent and print the reply.

**Why.** This is the smallest end-to-end check that your sign-in, team, and a published agent work before you build anything larger.

## Steps

1. Connect with `OpsAI()` (saved sign-in, or `OPS_BASE_URL`, `OPS_API_KEY`, and `OPS_TEAM`).
2. Take any published agent from `ops.agents.list()`.
3. Call `ops.agents.chat` and print `reply`.

```bash
python ask_once.py
```

```python
"""Send one message to a published agent and print the reply."""

from ops_ai import OpsAI


def main() -> None:
    ops = OpsAI()
    # Any published agent works; this path only needs a live reply.
    agent = next(row for row in ops.agents.list() if row.get("status") == "published")
    answer = ops.agents.chat(agent["id"], "What documents open a business account?")
    print(answer["reply"])


if __name__ == "__main__":
    main()
```

**You should see.** A non-empty reply string from the agent (wording depends on the model).

### TypeScript

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

### Command line

```bash
AGENT=$(opsai agents list --json | jq -r '.[] | select(.status=="published") | .id' | head -1)
opsai agents chat "$AGENT" --message "What documents open a business account?"
```

Guide: [Ask once](../../../docs/guide/build-with-ops-ai.md#ask-once).

<details>
<summary>Folder check (CI)</summary>

```bash
uv run python examples/chat/01-ask-once/setup.py
uv run pytest examples/chat/01-ask-once/test_example.py
```

Capability id: `chat.ask-once`.
</details>
