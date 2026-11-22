# Ask once

**Capability id:** `chat.ask-once`

Send one message to a published agent and read the reply. Full Py / TS / CLI snippets:
[docs/guide/build-with-ops-ai.md](../../../docs/guide/build-with-ops-ai.md) and the hub
[docs/guide/examples/README.md](../../../docs/guide/examples/README.md).

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/chat/01-ask-once/setup.py
uv run pytest examples/chat/01-ask-once/test_example.py
```

```python
from ops_ai import OpsAI

ops = OpsAI()
agent = next(a for a in ops.agents.list() if a.get("status") == "published")
print(ops.agents.chat(agent["id"], "What documents open a business account?")["reply"])
```

```bash
AGENT=$(opsai agents list --json | jq -r '.[] | select(.status=="published") | .id' | head -1)
opsai agents chat "$AGENT" --message "What documents open a business account?"
```

**You should see.** A non-empty reply. Surfaces: Python, TypeScript, and CLI are **built** (`ops.agents.chat` /
`opsai agents chat`; console-shaped alternative `opsai chat say`).
