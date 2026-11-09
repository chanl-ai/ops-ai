"""uc-623, cli layer: the same three-node YAML through `opsai workflows` validate, apply and run --test."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from usecase_harness import ROOT, check, finish

FOLDER = ROOT / "examples/workflows/01-normalize-a-request"
YAML = FOLDER / "resources/workflow.yaml"


def _profile() -> dict[str, str]:
    sys.path.insert(0, str(ROOT / "examples" / "_lib"))
    from folder import ops_client

    ops = ops_client()
    path = FOLDER / ".ops-profile.json"
    path.write_text(
        json.dumps(
            {
                "current": "local",
                "profiles": {
                    "local": {
                        "baseUrl": ops.config.base_url,
                        "accessToken": ops.config.access_token,
                        "team": ops.config.team,
                        "services": ops.config.services,
                    }
                },
            }
        )
        + "\n"
    )
    return {**os.environ, "OPS_CONFIG": str(path)}


def _ops(argv: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ops_ai.cli", "workflows", *argv],
        cwd=FOLDER,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def main() -> None:
    env = _profile()
    valid = _ops(["validate", str(YAML)], env)
    check(
        "7 opsai workflows validate accepts the YAML",
        valid.returncode == 0 and "valid" in (valid.stdout + valid.stderr).lower(),
        valid.stdout + valid.stderr,
    )
    applied = _ops(["apply", str(YAML)], env)
    out = applied.stdout + applied.stderr
    check(
        "8 opsai workflows apply stores the draft",
        applied.returncode == 0 and "normalize_support_request" in out,
        out,
    )
    ran = _ops(
        ["run", "normalize_support_request", "--input", str(FOLDER / "fixtures/valid.json"), "--test", "--wait"],
        env,
    )
    check(
        "9 opsai workflows run --test --wait returns accepted",
        ran.returncode == 0 and "accepted" in (ran.stdout + ran.stderr),
        ran.stdout + ran.stderr,
    )
    missing = _ops(
        ["run", "normalize_support_request", "--input", str(FOLDER / "fixtures/missing-email.json"), "--test"],
        env,
    )
    text = missing.stdout + missing.stderr
    check(
        "10 a missing customerEmail is refused with that schema path",
        missing.returncode == 1 and "customerEmail" in text,
        text,
    )
    finish()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        check("7 opsai workflows validate accepts the YAML", False, str(exc))
        finish()
