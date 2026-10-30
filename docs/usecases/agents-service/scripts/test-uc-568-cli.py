# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-568 document workflows, cli layer: docs/usecases/agents-service/document-workflows.md, story S5 (steps 21-24).

A developer describes a workflow ("read a levy notice and the bank's account, merge them, and send disagreements to a
person") and builds it with `scripts/wf_builder.py`, the /wf-builder skill's script, on a fresh team of this run's own
agents-service (dev auth, the scripted model, no model call) and a workflow worker. The script runs in a temporary
folder, so the `workflows/<id>.json` it writes never lands in the repository. Two SDK profiles name the same
agents-service in a temporary OPS_CONFIG: `local`, and `staging`, which the skill must treat as not local."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import httpx
from usecase_harness import AGENTS_PORT, ROOT, agents, check, engine_worker, finish, until

TEAM = f"team_uc568_{uuid.uuid4().hex[:6]}"
HEADERS = {"X-Team-Id": TEAM}
WID = f"levy_bank_match_{uuid.uuid4().hex[:6]}"
GOAL = "read a levy notice and the bank's account, merge them, and send disagreements to a person"
SCRIPT = ROOT / "scripts" / "wf_builder.py"
WORK = Path(tempfile.mkdtemp(prefix="uc568-cli-"))
CONFIG = WORK / "ops-config.json"


def builder(*args: str, profile: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    """`scripts/wf_builder.py`, as the skill runs it, from the developer's own folder."""
    env = {**os.environ, "OPS_CONFIG": str(CONFIG)}
    env.pop("VIRTUAL_ENV", None)
    sdk = str(ROOT / "sdk" / "python")
    argv = ["uv", "run", "--quiet", "--project", str(ROOT), "--with-editable", sdk, "python", str(SCRIPT), *args]
    argv += ["--profile", profile]
    return subprocess.run(
        argv, cwd=WORK, env=env, input=stdin, capture_output=True, text=True, check=False, timeout=600
    )


def said(r: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {"code": r.returncode, "out": r.stdout[-400:], "err": r.stderr[-400:]}


def definition(api: httpx.Client) -> httpx.Response:
    return api.get(f"/v1/workflows/definitions/{WID}", headers=HEADERS)


def main() -> None:
    try:
        with agents() as api, engine_worker("uc568-cli"):
            base = f"http://127.0.0.1:{AGENTS_PORT}"
            profile = {"baseUrl": base, "team": TEAM, "services": {"agents": base}}
            CONFIG.write_text(json.dumps({"current": "local", "profiles": {"local": profile, "staging": profile}}))
            spec = WORK / "goal.json"
            spec.write_text(json.dumps({"id": WID, "goal": GOAL, "example": "two_source_match"}))

            # 21. A dry run writes the definition beside the developer, validated clean, adapted from the example, and
            # prints its steps and ports; nothing is created.
            dry = builder("create", "--file", str(spec), profile="local")
            written = WORK / "workflows" / f"{WID}.json"
            drawn: dict[str, Any] = json.loads(written.read_text()) if written.exists() else {}
            types = [n.get("type") for n in drawn.get("nodes") or []]
            ports = {(c.get("from") or {}).get("port") for c in drawn.get("connections") or []}
            checked = builder("validate", "--file", str(written), profile="local") if written.exists() else None
            check(
                "21 a dry run writes workflows/<id>.json from the two_source_match example (Join, then Combine facts "
                "by its disagree port), validated clean, prints its steps and ports, and creates nothing",
                dry.returncode == 0 and "ops.flow.join" in types and "ops.data.combine" in types
                and "ops.flow.humanReview" in types and "disagree" in ports
                and checked is not None and checked.returncode == 0
                and "disagree" in dry.stdout and "Combine facts" in dry.stdout
                and definition(api).status_code == 404,
                {"dry": said(dry), "written": written.exists(), "types": types, "ports": sorted(p for p in ports if p),
                 "validate": said(checked) if checked else None, "exists": definition(api).status_code},
            )  # fmt: skip

            # 22. --create on the local profile creates it.
            created = builder("create", "--file", str(written if written.exists() else spec), "--create",
                              profile="local")  # fmt: skip
            held = definition(api)
            check(
                "22 --create on the local profile creates the workflow on the team",
                created.returncode == 0 and held.status_code == 200,
                {"create": said(created), "exists": held.status_code},
            )

            # 23. A test run with sources that disagree reaches Human review and shows the disagreements.
            ran = builder(
                "run", WID,
                "--input", "noticeAmount=1284.50", "--input", "bankAmount=1248.50", "--input", "account=CHK-0091",
                "--wait", profile="local",
            )  # fmt: skip

            def waiting() -> dict[str, Any] | None:
                rows = (
                    api.get("/v1/runs", params={"workflowId": WID, "pageSize": 20}, headers=HEADERS).json().get("data")
                    or {}
                ).get("data") or []
                return next((r for r in rows if r.get("status") == "waiting"), None)

            run = until(waiting, 30) if ran.returncode == 0 else None
            check(
                "23 a test run of the built workflow reaches Human review and prints the disagreements",
                ran.returncode == 0
                and run is not None
                and "Waiting at Human review: The notice and the bank disagree" in ran.stdout
                and "Disagreement: balance (bank 1248.50, notice 1284.50)" in ran.stdout,
                {"run": said(ran), "waiting": (run or {}).get("id")},
            )

            # 24. On a profile that is not local, --create without the workflow id typed back creates nothing.
            other = f"{WID}_staging"
            spec2 = WORK / "goal-staging.json"
            spec2.write_text(json.dumps({"id": other, "goal": GOAL, "example": "two_source_match"}))
            refused = builder("create", "--file", str(spec2), "--create", profile="staging", stdin="yes\n")
            gone = api.get(f"/v1/workflows/definitions/{other}", headers=HEADERS)
            check(
                "24 --create on a profile that is not local, without the workflow id typed back, creates nothing",
                refused.returncode != 0 and other in (refused.stdout + refused.stderr) and gone.status_code == 404
                and SCRIPT.exists(),
                {"create": said(refused), "exists": gone.status_code, "script": SCRIPT.exists()},
            )  # fmt: skip
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    finish()


if __name__ == "__main__":
    main()
