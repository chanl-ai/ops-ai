"""uc-751, sdk layer: docs/usecases/agents-service/evals-keep-saved-cases-and-runs.md. The same flow through the Python SDK:
a builder saves cases and runs them, a viewer reads suites and runs, a member of another team reads nothing. S7: the SDK runs the saved cases, reads the run's gate and cost, and the publish
request is refused naming the step."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from usecase_harness import AGENTS_PORT, PLATFORM_INTERNAL_PORT, PLATFORM_PORT, agents, check, finish, platform

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "sdk" / "python" / "src"))
from ops_ai import OpsAI
from ops_ai.errors import OpsError

PASSWORD = "northfield-demo"
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
CONN: dict[str, Any] = {
    "base_url": "http://127.0.0.1",
    "services": {"platform": f"http://127.0.0.1:{PLATFORM_PORT}", "agents": f"http://127.0.0.1:{AGENTS_PORT}"},
}
# The scripted model's alias needs a price, or every run costs 0 and unpriced.
PRICED = {"OPS_PRICES": json.dumps({"default": {"input": "1000", "output": "3000"}})}
AGENT = "ag_branch"
CASES = {"cases": [{"name": "Greets", "input": "Hello", "checks": [{"type": "reply_contains", "text": "help"}]}]}


def refused(call: Any) -> OpsError | None:
    try:
        call()
    except OpsError as e:
        return e
    return None


with platform(), agents(env={**AUTH, **PRICED}):
    james = OpsAI.sign_in("j.richardson@harborpine.example", PASSWORD, team="team_ops", **CONN)
    viewer = OpsAI.sign_in("r.menon@harborpine.example", PASSWORD, team="team_ops", **CONN)
    outsider = OpsAI.sign_in("w.kamau@harborpine.example", PASSWORD, team="team_platform", **CONN)

    james.raw.agents.assurance_save_agent_cases(AGENT, CASES)
    run = james.raw.agents.agents_create_eval_run(AGENT, {})
    again = james.raw.agents.agents_create_eval_run(AGENT, {})
    check("11 James saves a case and runs it twice through the SDK: two different runs", run["id"] != again["id"], [run["id"], again["id"]])

    runs = viewer.raw.agents.assurance_list_runs()
    check(
        "12 a viewer reads the two runs, newest first, with the asset's name",
        [r["id"] for r in runs["data"]] == [again["id"], run["id"]] and runs["tabCounts"]["runs"] == 2,
        runs["tabCounts"],
    )

    suites = viewer.raw.agents.assurance_list_suites(result=["not_run"])
    check("13 filtering suites to not run lists none, and the facet counts say why", suites["data"] == [] and "not_run" not in suites["facets"]["result"], suites["facets"])

    save = refused(lambda: viewer.raw.agents.assurance_save_agent_cases(AGENT, CASES))
    check("14 a viewer's save is refused (403)", save is not None and save.status == 403, save and save.status)

    theirs = outsider.raw.agents.assurance_list_suites()
    cant = refused(lambda: outsider.raw.agents.agents_create_eval_run(AGENT, {}))
    check("15 another team sees no suites and cannot run the agent (404)", theirs["data"] == [] and cant is not None and cant.status == 404, cant and cant.status)

    # S7
    priya = OpsAI.sign_in("p.shah@harborpine.example", PASSWORD, team="team_ops", **CONN)
    desk = james.agents.create({"name": "Fee desk", "role": "Answers questions about fees"})
    judged = [
        {
            "name": "Never says it",
            "input": "Hello",
            "checks": [
                {"type": "reply_contains", "text": "zzq-never-said-zzq"},
                {"type": "judge", "rubric": "Greets the customer politely"},
            ],
        }
    ]
    james.agents.add_eval_cases(desk["id"], judged)
    saved = james.agents.eval_cases(desk["id"])
    refused_trigger = refused(lambda: james.agents.eval(desk["id"], trigger="other"))
    run = james.agents.eval(desk["id"], trigger="cli")
    rows = james.agents.eval_runs(desk["id"])
    one = james.agents.eval_run(run["id"])
    step = next((x for x in run["gate"]["steps"] if x["step"] == "pass_rate"), {})
    check(
        "30 the SDK saves a judged case, runs it as cli (another trigger is 422) and reads the run: blocked, cost above 0, listed without results, read with them",
        len(saved["cases"]) == 1
        and refused_trigger is not None
        and refused_trigger.status == 422
        and run["gate"]["blocked"] is True
        and step.get("result") == "fail"
        and run["costUsd"] > 0
        and [r["id"] for r in rows["data"]] == [run["id"]]
        and rows["data"][0]["trigger"] == "cli"
        and "results" not in rows["data"][0]
        and len(one["results"]) == 1,
        {"gate": run["gate"]["blocked"], "cost": run["costUsd"], "rows": rows["data"]},
    )
    asked = refused(lambda: james.agents.publish(desk["id"], note="go"))
    problems = ((asked.details or {}).get("problems") or []) if asked else []
    check(
        "31 the publish request is refused naming the failing pass-rate step",
        asked is not None and asked.status == 422 and [p["kind"] for p in problems] == ["eval_failed"] and "Pass rate" in problems[0]["message"],
        asked and asked.details,
    )
    priya.raw.platform.policies_set_policy("evalsRequired", {"value": True})
    bare = james.agents.create({"name": "Bare desk", "role": "Answers questions about hours"})
    needs = refused(lambda: james.agents.publish(bare["id"], note="go"))
    kinds = [p["kind"] for p in ((needs.details or {}).get("problems") or [])] if needs else []
    check("32 with Require passing evals to publish on, an agent with no saved cases is refused", needs is not None and needs.status == 422 and kinds == ["eval_no_cases"], needs and needs.details)
    priya.raw.platform.policies_set_policy("evalsRequired", {"value": False})

finish()
