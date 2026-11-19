# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-676 typed text and pushed items become cited knowledge, cli layer: docs/usecases/kb-service/typed-text-and-
pushed-items.md, story S7 (steps 14-16). A developer makes a knowledge base and a push source and pushes an item with `opsai kb`,
reading the address from a saved profile. Own kb-service with its files-service and documents-service; no model is
called."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from usecase_harness import ROOT, check, finish, kb

TEXT = "An overdraft fee of 25 dollars is waived once a year."


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uc-676-cli-") as tmp, kb(Path(tmp) / "files") as k:
        config = Path(tmp) / "ops-config.json"
        profile = {"baseUrl": "http://127.0.0.1", "team": "team_ops", "services": {"kb": str(k.base_url).rstrip("/")}}
        config.write_text(json.dumps({"profiles": {"local": profile}, "current": "local"}))
        env = {**os.environ, "OPS_CONFIG": str(config)}
        env.pop("VIRTUAL_ENV", None)

        def opsai(*args: str) -> Any:
            argv = ["uv", "run", "--quiet", "--project", str(ROOT / "sdk" / "python"), "opsai", "kb", *args, "--json"]
            ran = subprocess.run(argv, env=env, capture_output=True, text=True, check=False, timeout=300)
            return (
                json.loads(ran.stdout) if ran.returncode == 0 and ran.stdout.strip() else {"error": ran.stderr[-400:]}
            )

        base = opsai("create", "Deposit fees", "--owner", "maya@harborpine.example")
        src = opsai("add-source", "Fee schedule feed", "--kb", str(base.get("id")))
        check(
            "14 opsai kb create and add-source make a base and a push source",
            bool(base.get("id") and src.get("id")),
            {"base": base, "source": src},
        )
        push = ("push", str(src.get("id")), "--name", "fees/overdraft", "--title", "Overdraft fee", "--text", TEXT)
        first, again = opsai(*push), opsai(*push)
        check(
            "15 opsai kb push creates the item, then the same push is unchanged",
            first.get("outcome") == "created" and again.get("outcome") == "unchanged",
            {"first": first, "again": again},
        )
        found = opsai("search", str(base.get("id")), "overdraft fee waived")
        check("16 opsai kb search returns the pushed text", "25 dollars" in json.dumps(found), found)
    finish()


main()
