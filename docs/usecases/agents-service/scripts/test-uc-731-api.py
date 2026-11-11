"""uc-731 guardrail names are unique per team, api layer: docs/usecases/agents-service/guardrail-names-per-team.md.

The agents service on its own migrated database; one team creates a guardrail of one name twice."""

from __future__ import annotations

from typing import Any

from usecase_harness import agents, check, data, finish

RULE = {"name": "No investment advice", "topics": ["investment advice"], "message": "I can't give investment advice."}
OPS = {"X-Team-Id": "team_ops", "X-Dev-User": "lee@harborpine.example"}

with agents() as api:
    mine: dict[str, Any] = data(api.post("/v1/guardrails", json=RULE, headers=OPS))
    check("1 the first team's guardrail has the plain slug", mine.get("slug") == "no-investment-advice", mine)
    again = api.post("/v1/guardrails", json=RULE, headers=OPS)
    check(
        "2 the same team making it again is told the name is taken",
        again.status_code == 409 and again.json()["error"]["code"] == "name_taken",
        again.text,
    )
finish()
