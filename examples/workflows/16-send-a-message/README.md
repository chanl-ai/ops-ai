# Send a message

Reply through the existing send_reply path. The test uses the in-stack mail fake.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/16-send-a-message/setup.py
uv run pytest examples/workflows/16-send-a-message/test_example.py
```

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
