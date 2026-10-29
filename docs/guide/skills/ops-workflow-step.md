# ops-workflow-step: add a workflow step type

Status: current. Proven by `make skills-proof` (c-554).

skill: ops-workflow-step
description: Add a new workflow step type (node kind) to the engine: its definition, ports, parameters and form, its executor, and its tests. Use when someone needs a step that no existing type can be configured to do.
targets: uv run pytest packages/ops_engine/tests, make usecase-test UC=uc-081

## When to use it

Only when no existing type can be configured to do the job: a use case is configuration, never a step written for one
use case (`docs/design/workflows/workflow-nodes.md`, "The rule every type follows").

## Steps

1. Read `docs/design/workflows/workflow-nodes.md`: a type is a namespaced id and version, a group, input and output
   ports, parameters as JSON Schema, a generated form (`ui`), an effects class and an executor.
2. Add the `NodeType` to `packages/ops_engine/src/ops_engine/node_types.py`. The console draws its form from `ui`,
   with the closed set of widgets and option sources listed there, so no console code changes.
3. Add its port function to `shapes.py` and its executor to the map in `compiler.py`; a write's executor gets one
   attempt and a reconciliation read (`docs/architecture/workflow-runner.md`).
4. Test it in `packages/ops_engine/tests/` (one test per failure mode), then run a workflow that uses it.
5. The engine package belongs to its own lane; ask its owner before changing it.

## Proof

```bash proof
uv run --frozen pytest -q packages/ops_engine/tests
make usecase-test UC=uc-081 LAYER=api
```
