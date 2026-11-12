"""uc-740, sdk layer: docs/usecases/agents-service/start-from-a-template-sdk.md. Priya, signed in through the Python
SDK, lists templates of each kind, installs the starter skill doc-coauthoring and finds it in the team's skills."""

from __future__ import annotations

from typing import Any

from steps import PRIYA, install_template, list_templates, sign_in_as
from templates_stack import SKILL, SOURCE, STARTERS, templates_stack
from usecase_harness import check, finish

KINDS = ("agent", "skill", "workflow", "guardrail", "case_type", "task_type")


def attempt(what: str, run: Any) -> Any:
    try:
        return run()
    except Exception as e:  # a missing SDK word is the step failing, shown with its reason
        return {"failed": what, "reason": str(e)}


with templates_stack() as s:
    check("0 the starters pack is on this machine", STARTERS.exists(), str(STARTERS))
    ops = sign_in_as(PRIYA)

    # 1. Templates of each kind, one list per kind.
    lists = {k: attempt(f"list {k}", lambda k=k: list_templates(ops, k)) for k in KINDS}
    check(
        "1 the SDK lists templates of every kind, each list holding only its kind",
        all(isinstance(v, list) and all(t.get("kind") == k for t in v) for k, v in lists.items()),
        {k: v if isinstance(v, dict) else [t.get("id") for t in v] for k, v in lists.items()},
    )
    skills = lists["skill"] if isinstance(lists["skill"], list) else []
    check(
        "1 the starter skill doc-coauthoring is offered and Priya may add it",
        any(t.get("source") == SOURCE and t.get("id") == SKILL and t.get("canAdd") for t in skills),
        [t.get("id") for t in skills],
    )

    # 2. Install the starter skill into the team.
    made = attempt("install", lambda: install_template(ops, f"{SOURCE}:{SKILL}"))
    record = str(((made or {}).get("copy") or {}).get("recordId") or "")
    check("2 the SDK installs the skill as the team's own copy", bool(record) and made.get("created") is True, made)

    # 3. The team's skills list holds it.
    team_skills = attempt("team skills", ops.raw.agents.agents_list_skills)
    page = team_skills.get("data") if isinstance(team_skills, dict) and "data" in team_skills else team_skills
    names = [str(x.get("id")) for x in page] if isinstance(page, list) else page
    check("3 the skill is in the team's skills list", bool(record) and record in (names or []), names)

finish()
