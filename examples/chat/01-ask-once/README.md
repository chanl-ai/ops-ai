# Ask once

Send one message and read the reply.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/chat/01-ask-once/setup.py
uv run pytest examples/chat/01-ask-once/test_example.py
```

Python uses the public SDK (`ops.agents.chat`) and `fixtures/message.json`. The CLI `opsai chat send` is **Planned**.

The full lesson is in [../../../docs/guide/build-with-ops-ai.md](../../../docs/guide/build-with-ops-ai.md).
