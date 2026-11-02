# Normalize a support request

An app posts a support request; the workflow maps the fields and returns `accepted`.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/01-normalize-a-request/setup.py
uv run pytest examples/workflows/01-normalize-a-request/test_example.py
node examples/workflows/01-normalize-a-request/test_example.mjs
```

After setup:

```bash
cd examples/workflows/01-normalize-a-request
OPS_CONFIG=.ops-profile.json ops workflows validate resources/workflow.yaml
OPS_CONFIG=.ops-profile.json ops workflows apply resources/workflow.yaml
OPS_CONFIG=.ops-profile.json ops workflows run normalize_support_request --input fixtures/valid.json --test --wait
```

A payload without `customerEmail` is refused with that schema path. Open the printed `/workflows/definitions/<id>`.

The full lesson is in [../../../docs/guide/build-with-ops-ai.md](../../../docs/guide/build-with-ops-ai.md).
