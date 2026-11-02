# Roles refuse a start

This is the first Example that explains a refusal. It extends [02-route-a-support-message](../02-route-a-support-message/) (the route-a-support-message workflow). It does not add a second classify graph.

A signed-in sample-team person without the `workflows.edit` cell is refused `403 role_required` when they start it. The same start succeeds for a person who has that cell. People are chosen through `can()` (`GET /v1/me/why`), not by a role name.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/02-route-a-support-message/setup.py
uv run python examples/workflows/12-roles-refuse-a-start/setup.py
uv run pytest examples/workflows/12-roles-refuse-a-start/test_example.py
```

Python uses `ops.workflows.run` and the public why/members routes. CLI start-as-another-person is **Planned**.

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md) and [../../../docs/guide/security-and-governance.md](../../../docs/guide/security-and-governance.md).
