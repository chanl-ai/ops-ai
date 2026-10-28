"""The overlay's secret env files carry a database login a driver reads back exactly, whatever its password holds, and
a service added since an overlay's keys were made gets a key."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa

WRITE = Path(__file__).resolve().parents[1] / "write_secrets.py"
SERVICES = ("platform", "agents", "tools", "models", "kb", "files", "documents")


def write(tmp_path: Path, password: str) -> Path:
    roles = ["ops_migrator", *(f"ops_{s}_runtime" for s in SERVICES)]
    (tmp_path / "logins").write_text("".join(f"{r}={password}\n" for r in roles))
    (tmp_path / "admin").write_text("OPS_BOOTSTRAP_ADMIN_EMAIL=a@b.example\n")
    overlay = tmp_path / "overlay"
    overlay.mkdir(exist_ok=True)
    args = ["--overlay", overlay, "--db-host", "postgres:5432", "--db-name", "ops"]
    args += ["--logins", tmp_path / "logins", "--admin", tmp_path / "admin"]
    subprocess.run([sys.executable, WRITE, *map(str, args)], check=True, capture_output=True)
    return overlay


def test_a_password_with_url_characters_reaches_the_driver_unchanged(tmp_path: Path) -> None:
    password = "p@ss:w/rd?#%+ x"
    overlay = write(tmp_path, password)
    for name, role in [("migrate", "ops_migrator"), ("platform", "ops_platform_runtime")]:
        line = next(x for x in (overlay / f"{name}.env").read_text().splitlines() if x.startswith("OPS_DATABASE_URL="))
        url = sa.make_url(line.split("=", 1)[1])
        assert (url.username, url.password, url.host, url.port, url.database) == (
            role,
            password,
            "postgres",
            5432,
            "ops",
        )


def test_keys_made_before_the_runner_are_made_again_with_its_key(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    (overlay / "keys.env").write_text("".join(f"OPS_SVC_KEY_{s.upper()}=old\n" for s in SERVICES))
    write(tmp_path, "pw")
    runner = (overlay / "runner.env").read_text()
    assert "OPS_SERVICE_SIGNING_KEY=" in runner and "=old" not in runner
    assert "OPS_DATABASE_URL" not in runner
