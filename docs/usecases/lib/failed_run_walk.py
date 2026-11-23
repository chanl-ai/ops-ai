"""uc-workflows-2's workflow and the failure every layer reads from its test run: a step that reads the customer's
email from a request that has none, wired by its error port to an End its builder marked as a failure."""

from __future__ import annotations

from typing import Any

STEP, STEP_NAME, END_NAME = "pick", "Read the customer email", "No email"
# The failure in the one error model (ops_contracts.errors.CODES, `ended_as_failure`), as GET /v1/runs/{id} returns it.
EXPECTED: dict[str, Any] = {"kind": "refused", "code": "ended_as_failure", "retryable": False}
USER_MESSAGE = "This stopped where the workflow says to stop."
DETAILS = {"end": END_NAME}
# The CLI's exit status for a `refused` failure (ops_ai.errors.EXIT_CODES).
EXIT = 3
# A request with no customer: the step's path reads nothing.
INPUT: dict[str, Any] = {"subject": "Card not working"}


def definition(workflow_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "id": workflow_id,
        "name": f"Reply to a request ({workflow_id})",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "name": "Request", "parameters": {}},
            {
                "id": STEP,
                "type": "ops.data.transform",
                "typeVersion": 1,
                "name": STEP_NAME,
                "parameters": {"expression": "$.input.customer.email", "as": "email"},
            },
            {"id": "found", "type": "ops.flow.end", "typeVersion": 1, "name": "Found", "parameters": {}},
            {
                "id": "no_email",
                "type": "ops.flow.end",
                "typeVersion": 1,
                "name": END_NAME,
                "parameters": {"outcome": "no_email", "result": "failed"},
            },
        ],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": STEP, "port": "in"}},
            {"from": {"node": STEP, "port": "out"}, "to": {"node": "found", "port": "in"}},
            {"from": {"node": STEP, "port": "error"}, "to": {"node": "no_email", "port": "in"}},
        ],
    }


def leaks(sentence: str) -> list[str]:
    """What an end user must never read in `sentence`: the step's id, the code, a path, or an exception's name."""
    return [w for w in (STEP, EXPECTED["code"], "$.", "Error", "Traceback", "Exception") if w in sentence]
