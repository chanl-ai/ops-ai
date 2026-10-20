"""uc-401 step outputs are known before a run, api layer: docs/usecases/agents-service/step-output-shapes.md.

A builder saves a workflow that has never run (configuration below, nothing in code knows it) and reads its shapes:
the request's fields from its input schema, the Set step's from its values, and a Switch's on each of its ports.
Saving a copy that maps a misspelt field is warned, not refused. No model call is made."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any

from usecase_harness import AGENTS_PORT, TEAM, TOOLS_PORT, agents, check, data, finish, tools


def definition(wid: str, amount_path: str) -> str:
    return f"""
schemaVersion: 2
id: {wid}
name: Fee dispute triage (uc-401)
nodes:
  - id: start
    type: ops.trigger.request
    typeVersion: 1
    name: Dispute
    parameters:
      inputSchema:
        type: object
        additionalProperties: false
        required: [customerId, amount, complaint]
        properties: {{customerId: {{type: string}}, amount: {{type: number}}, complaint: {{type: string}}}}
  - id: fields
    type: ops.data.set
    typeVersion: 1
    name: Fields
    parameters: {{values: {{customer: "$.input.customerId", amount: "$.input.amount"}}}}
  - id: triage
    type: ops.flow.switch
    typeVersion: 1
    name: Triage
    parameters:
      cases: [{{name: large, conditions: [{{left: "$.input.amount", op: gt, right: 100}}]}}]
  - id: note
    type: ops.data.set
    typeVersion: 1
    name: Note
    parameters: {{values: {{amount: "{amount_path}", way: "$.nodes.triage.out.case"}}}}
  - {{id: done, type: ops.flow.end, typeVersion: 1, name: Done}}
connections:
  - {{from: {{node: start, port: payload}}, to: {{node: fields, port: in}}}}
  - {{from: {{node: fields, port: out}}, to: {{node: triage, port: in}}}}
  - {{from: {{node: triage, port: large}}, to: {{node: note, port: in}}}}
  - {{from: {{node: triage, port: otherwise}}, to: {{node: note, port: in}}}}
  - {{from: {{node: note, port: out}}, to: {{node: done, port: in}}}}
"""


def fields(shape: dict[str, Any]) -> set[str]:
    return set(shape.get("properties") or {})


with ExitStack() as stack:
    stack.enter_context(tools({"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    api = stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
    good = definition("uc401_triage", "$.nodes.fields.out.amount")
    saved = api.post("/v1/workflows/definitions", json={"yaml": good}, headers=TEAM)
    version = (data(saved) or {}).get("version")
    check(
        "0 the workflow saves with no warnings",
        saved.status_code == 201 and (data(saved) or {}).get("warnings") == [],
        saved.text[:300],
    )

    shapes = api.get(f"/v1/workflows/definitions/uc401_triage/versions/{version}/shapes", headers=TEAM)
    steps = (data(shapes) or {}).get("steps") or {}
    check(
        "1 before any run, each step lists its output fields by port",
        shapes.status_code == 200
        and fields(steps["start"]["payload"]) == {"customerId", "amount", "complaint"}
        and fields(steps["fields"]["out"]) == {"customer", "amount"}
        and fields(steps["triage"]["large"]) == {"case"}
        and fields(steps["triage"]["otherwise"]) == {"case", "tried"},
        {k: {p: sorted(fields(s)) for p, s in v.items()} for k, v in steps.items()},
    )

    misspelt = definition("uc401_misspelt", "$.nodes.fields.out.amout")
    warned = api.post("/v1/workflows/definitions", json={"yaml": misspelt}, headers=TEAM)
    notes = [w for w in (data(warned) or {}).get("warnings") or [] if w.get("node") == "note"]
    check(
        "2 a copy mapping a misspelt field saves, with a warning that names the field",
        warned.status_code == 201 and len(notes) == 1 and "amout" in notes[0]["message"],
        warned.text[:400],
    )

    other = api.get("/v1/workflows/definitions/uc401_nope/versions/1/shapes", headers=TEAM)
    check("3 a workflow that does not exist has no shapes", other.status_code == 404, other.text[:200])

finish()
