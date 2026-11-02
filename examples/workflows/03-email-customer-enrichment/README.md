# Enrich an email with customer data

A support email starts the run. The workflow extracts facts, looks up the sender with the `search_customers` read tool, joins those branches, and returns `enriched`, `customer_not_found`, or `analysis_failed`.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/03-email-customer-enrichment/setup.py
uv run pytest examples/workflows/03-email-customer-enrichment/test_example.py
```

After setup:

```bash
cd examples/workflows/03-email-customer-enrichment
OPS_CONFIG=.ops-profile.json ops workflows send-test-email email_customer_enrichment --event fixtures/known-customer.json
```

An unknown sender ends `customer_not_found`. A model that cannot answer (the test sets an alias that does not exist) ends `analysis_failed`. Setup reuses `search_customers` and a published R4 agent when one is live.

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
