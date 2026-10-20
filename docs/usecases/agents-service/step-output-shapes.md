# A workflow's step outputs are known before it runs

Status: passing (2026-10-19). Id: `uc-401`. Service: `agents-service`. Layers: api. Card: c-353.

A builder mapping a later step's fields needs to know what each earlier step outputs, and until now saw it only on a
past run. Every step type now declares its output by port: fixed by its type, built from its settings (a request's
input schema, a Set step's values, an AI step's answer), or read from its document type or operation. A mapping to a
field a step never outputs is warned when the workflow is saved or validated, never refused.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL for the isolated stack | `make db-up ISOLATED=1` |
| The run | `make usecase-test UC=uc-401 LAYER=api ISOLATED=1` |

The stack is agents-service with tools-service; nothing runs, so no worker or model is needed. The AI steps' answer shapes are covered by the engine test, since AI steps are off by default for a team.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Save a request, Set, Switch and Set workflow | 201 with no warnings |
| 1 | `GET /v1/workflows/definitions/{id}/versions/{v}/shapes` | The request's fields from its input schema, Set's from its values, the Switch's `case` on its named way and `case, tried` on `otherwise` |
| 2 | Save a copy whose last step maps `amout` | 201, with an `unknown_output_field` warning on that step naming `amout` |
| 3 | Shapes of a workflow that does not exist | 404 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-401-api.py` | passing |

## Non-vacuous check

`packages/ops_engine/tests/test_output_shapes.py` runs every built type's executor on fake ports and holds what it
writes to its declared shape: renaming Open case's `caseId` in the executor, or dropping Set file data's `data` from its
shape, fails it by name. Without the open-shape rule, a mapping into a tool with no response schema is warned.

## What this does not cover

The field picker and suggested mappings in the editor (the next card). A tool step's response schema comes from an
OpenAPI import (`services/tools-service/tests/test_operation_output_schema.py`).
