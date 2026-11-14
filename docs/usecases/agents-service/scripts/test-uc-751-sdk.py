"""uc-751, sdk layer: docs/usecases/agents-service/evals-keep-saved-cases-and-runs.md. The same flow through the Python SDK:
a builder saves cases and runs them, a viewer reads suites and runs, a member of another team reads nothing."""

from __future__ import annotations

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
AGENT = "ag_branch"
CASES = {"cases": [{"name": "Greets", "input": "Hello", "checks": [{"type": "reply_contains", "text": "help"}]}]}


def refused(call: Any) -> OpsError | None:
    try:
        call()
    except OpsError as e:
        return e
    return None


with platform(), agents(env=AUTH):
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

finish()
