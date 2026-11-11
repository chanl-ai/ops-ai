"""uc-702, cli layer: docs/usecases/tools-service/a-person-adds-a-second-account-of-their-own.md, step 4.

`opsai apps accounts` shows what each account points at, and `opsai apps default github Corp --mine` makes the person's
own second account their default, which their calls then use (lib/several_accounts.py, lib/apps_walk.py)."""

from __future__ import annotations

from apps_walk import ops_cli
from several_accounts import GH, MAYA, git_rig, issues, maya_second_github, my_github
from usecase_harness import check, finish

with git_rig("uc-702c") as r:
    maya_second_github(r)
    code, listed = ops_cli("admin", "apps", "accounts", GH)
    points = {str(a.get("name")): str(a.get("pointsAt")) for a in listed} if isinstance(listed, list) else {}
    check(
        "4a opsai apps accounts shows where each team account points",
        code == 0 and points.get("Platform server", "").startswith("github.test"),
        points or listed,
    )
    code, answer = ops_cli("approver", "apps", "default", GH, "corp", "--mine")
    used = r.call(acting_for=MAYA)
    corp = next((a for a in my_github(r).get("accounts") or [] if a.get("name") == "Corp"), {})
    check(
        "4b opsai apps default github corp --mine makes Corp Maya's default, and her call answers issue 412",
        code == 0 and corp.get("primary") is True and issues(used) == [412],
        {"code": code, "answer": str(answer)[:300], "corp": corp, "used": used.text[:200]},
    )

finish()
