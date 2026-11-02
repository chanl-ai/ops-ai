"""uc-623, sdk layer: a builder validates, applies and test-runs the three-node Example on the fake stack."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from usecase_harness import ROOT, check, finish

FOLDER = ROOT / "examples/workflows/01-normalize-a-request"
TS = FOLDER / "test_example.mjs"


def _clear() -> None:
    for name in (".bindings.json", ".ops-profile.json"):
        path = FOLDER / name
        if path.is_file():
            path.unlink()


def _run(
    argv: list[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd or ROOT, text=True, capture_output=True, check=False, env=env)


def _setup() -> str:
    proc = _run([sys.executable, str(FOLDER / "setup.py")])
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"setup exited {proc.returncode}: {out}")
    return out


def _yaml_only() -> bool:
    text = (FOLDER / "test_example.py").read_text()
    return "outcome:" in text and "workflows" not in text


def _missing_path() -> tuple[bool, str]:
    sys.path.insert(0, str(ROOT / "examples" / "_lib"))
    from folder import ops_client
    from ops_ai.errors import OpsError

    ops = ops_client()
    payload = json.loads((FOLDER / "fixtures/missing-email.json").read_text())
    try:
        ops.workflows.run("normalize_support_request", input=payload, mode="test", wait=True)
    except OpsError as exc:
        details = exc.details if isinstance(exc.details, dict) else {}
        path = str(details.get("path") or "")
        return exc.status == 422 and exc.code == "invalid_input" and path == "customerEmail", f"{exc} {details}"
    return False, "run accepted a payload with no customerEmail"


def main() -> None:
    _clear()
    first = _setup()
    check("1 first setup prints READY", "READY" in first.splitlines(), first)
    pytest = _run([sys.executable, "-m", "pytest", "-q", str(FOLDER / "test_example.py")])
    check(
        "2 folder test validate/apply/test-run through the public SDK returns accepted",
        pytest.returncode == 0 and not _yaml_only(),
        pytest.stdout + pytest.stderr,
    )
    ts = (
        _run(["node", str(TS)])
        if TS.is_file()
        else type("R", (), {"returncode": 2, "stdout": "", "stderr": "missing test_example.mjs"})()
    )
    check(
        "3 TypeScript validate/apply/test-run of the same definition returns accepted",
        ts.returncode == 0 and "accepted" in (ts.stdout + ts.stderr),
        (ts.stdout + ts.stderr) if hasattr(ts, "stdout") else str(ts),
    )
    ok, detail = _missing_path()
    check("4 missing customerEmail fails with path customerEmail", ok, detail)
    again = _setup()
    check("5 second setup prints FOUND", "FOUND" in again, again)
    bindings = json.loads((FOLDER / ".bindings.json").read_text()) if (FOLDER / ".bindings.json").is_file() else {}
    workflow_id = str(bindings.get("workflowId") or "")
    printed = f"/workflows/definitions/{workflow_id}"
    check(
        "6 setup prints the UI definition path",
        bool(workflow_id) and printed in first,
        {"printed": first, "path": printed},
    )
    finish()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        check("1 first setup prints READY", False, str(exc))
        finish()
