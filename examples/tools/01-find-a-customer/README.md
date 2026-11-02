# Find a customer

Call one read operation with a known email and see the customer record. This folder reuses the sample-team read tool.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/tools/01-find-a-customer/setup.py
uv run pytest examples/tools/01-find-a-customer/test_example.py
```

Python uses the public SDK and `fixtures/input.json`. The CLI `ops tools call` is **Planned**.

The full lesson is in [../../../docs/guide/build-with-ops-ai.md](../../../docs/guide/build-with-ops-ai.md).
