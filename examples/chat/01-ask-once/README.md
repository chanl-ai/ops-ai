# Ask once

Send one message to a published agent and read the reply.

```bash
python ask_once.py
```

```python
"""Send one message to a published agent and print the reply."""

from __future__ import annotations

from typing import TypedDict, cast

from ops_ai import OpsAI


class AgentRow(TypedDict):
    id: str
    status: str


class ChatReply(TypedDict):
    reply: str
    threadId: str


def main() -> None:
    ops = OpsAI()
    agent = cast(
        AgentRow,
        next(row for row in ops.agents.list() if row.get("status") == "published"),
    )
    answer = cast(
        ChatReply,
        ops.agents.chat(agent["id"], "What documents open a business account?"),
    )
    print(answer["reply"])


if __name__ == "__main__":
    main()
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

Files: `ask_once.py`, `ask_once.mjs`, `ask_once.sh`. Lesson:
[docs/guide/build-with-ops-ai.md](../../../docs/guide/build-with-ops-ai.md).

<details>
<summary>Folder check (CI)</summary>

```bash
uv run python examples/chat/01-ask-once/setup.py
uv run pytest examples/chat/01-ask-once/test_example.py
```

Capability id: `chat.ask-once`.
</details>
