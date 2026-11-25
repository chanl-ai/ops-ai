"""uc-762, api layer: docs/usecases/agents-service/a-builder-tries-one-skill-path.md. A builder writes a skill that
reads an account and, if it is open, freezes it. Trying one path lists the two ways the `if` goes, each tool step with
values and a sample; the read runs for real, the freeze is only planned and reaches nothing until confirmed, a confirm
with edited values is refused, the confirm sends it once and a second confirm replays it. The skill keeps its one
version and no workflow run is made. Platform sign-in (lib/main_chains.py bank_stack), no model call."""

from __future__ import annotations

import time

from main_chains import ACCOUNT, bank_stack, holds, publish_bank_module
from usecase_harness import as_role, bearer, check, data, finish, signed_in

RUN = int(time.time())

with bank_stack() as s:
    # The policy that makes every team write wait for a reviewer is turned back off: the try's confirm is then the
    # person's own yes, as on a team that has not asked for reviewers.
    admin = bearer(signed_in(s.accounts, "w.kamau@harborpine.example"), "team_ops")
    off = s.accounts.put("/v1/policies/toolWritesNeedApproval", json={"value": False}, headers=admin)
    check("setup: team writes do not wait for a reviewer", off.status_code == 200, off.text[:200])
    s.who.update({role: as_role(s.accounts, role) for role in ("builder", "security")})
    builder = s.who["builder"]
    _module, read, write = publish_bank_module(s.gw, RUN, approval=False, team=builder, security=s.who["security"])
    time.sleep(31)  # past agents-service's 30 s tool list, so the skill's steps find the new tools

    made = s.api.post(
        "/v1/skills",
        json={
            "name": f"Freeze an open account {RUN}",
            "ownerTeam": "team_ops",
            "useWhen": "A customer reports a lost card.",
            "instructions": "",
            "exit": {"closed": "The account is already closed"},
            "steps": [
                {
                    "do": f"Look up the account with @tool:{read}.",
                    "use": {"kind": "tool", "id": read},
                    "branch": {"test": {"text": 'result.status == "open"'}, "otherwise": {"exit": "closed"}},
                },
                {
                    "do": f"Freeze it with @tool:{write}.",
                    "use": {"kind": "tool", "id": write},
                    "check": {"text": "result.ok == true"},
                },
            ],
        },
        headers=builder,
    )
    check("setup: the builder saves the skill (201)", made.status_code == 201, made.text[:300])
    skill = data(made) or {}
    versions = len(skill.get("versions") or [])

    listed = s.api.get("/v1/try-targets", params={"skill": skill.get("id", "sk_x")}, headers=builder)
    paths = (data(listed) or {}).get("paths") or []
    both = next((p for p in paths if len(p["steps"]) == 2), {"steps": []})
    steps = {st["tool"]: st for st in both["steps"]}
    check(
        "1 the skill's two paths are listed, the open one with both tool steps, their access and samples",
        listed.status_code == 200
        and len(paths) == 2
        and (steps.get(read, {}).get("access"), steps.get(write, {}).get("access")) == ("read", "write")
        and all(st["sampleFrom"] in ("last_run", "schema", "none") for st in both["steps"]),
        (listed.status_code, [(p["label"], [st["tool"] for st in p["steps"]]) for p in paths]),
    )

    def tried(tool: str, values: dict, **extra: object) -> tuple[int, dict]:
        r = s.gw.post("/v1/tool-modules/tries", json={"tool": tool, "input": values, **extra}, headers=builder)
        return r.status_code, data(r) or {}

    before = len(s.bank.received)
    status, ran = tried(read, {"accountId": ACCOUNT})
    check(
        "2 the read runs for real",
        (status, ran.get("kind"), ran.get("ok")) == (200, "ran", True) and len(s.bank.received) == before + 1,
        (status, ran.get("kind"), ran.get("reasons")),
    )

    status, planned = tried(write, {"accountId": ACCOUNT})
    plan = planned.get("plan") or {}
    check(
        "3 the write is shown as a plan, says it is on a live account, and reaches nothing",
        (status, planned.get("kind"), planned.get("live")) == (200, "planned", True)
        and (plan.get("request") or {}).get("url", "").endswith(f"/v1/accounts/{ACCOUNT}/holds")
        and holds(s.bank) == [],
        (status, planned.get("kind"), plan, planned.get("reasons")),
    )

    status, _ = tried(write, {"accountId": "CHQ-0001"}, planId=planned.get("planId"))
    check("4 a confirm with values edited after the plan is refused (409) and sends nothing", status == 409 and holds(s.bank) == [], status)

    status, sent = tried(write, {"accountId": ACCOUNT}, planId=planned.get("planId"))
    _, again = tried(write, {"accountId": ACCOUNT}, planId=planned.get("planId"))
    check(
        "5 the confirm sends the write once; a second confirm replays it",
        (status, sent.get("kind"), sent.get("ok")) == (200, "sent", True)
        and again.get("replayOf") == sent.get("callId")
        and len(holds(s.bank)) == 1,
        (status, sent.get("kind"), sent.get("reasons"), again.get("replayOf"), len(holds(s.bank))),
    )

    after = data(s.api.get(f"/v1/skills/{skill.get('id', 'sk_x')}", headers=builder)) or {}
    runs = data(s.api.get("/v1/runs", headers=builder)) or {}
    check(
        "6 nothing is saved as a skill version or a workflow run",
        len(after.get("versions") or []) == versions and not (runs.get("data") if isinstance(runs, dict) else runs),
        (versions, len(after.get("versions") or []), runs if not isinstance(runs, dict) else runs.get("pagination")),
    )

finish()
