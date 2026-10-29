"""The local stack's first admin (c-542), made by `make up` through platform-service's own bootstrap
(`python -m ops_platform.bootstrap`, as an install's migrate job runs it): a workspace and Security admin who signs in
with a password, so `make sample-team` installs the sample team as a person would.

The email and a generated password are kept in <OPS_RUN_DIR>/dev-admin.env (mode 600, git-ignored) and never printed.
The bootstrap writes only until the admin has a password, so it runs on every `make up`, and after `make reset-db` it
makes the same admin again from the same file.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = Path(os.environ.get("OPS_RUN_DIR") or ROOT / ".run")
ENV_FILE = RUN_DIR / "dev-admin.env"
# The dev tenant and its Security team, under the names platform-service's dev people seed gives them, so the
# bootstrap's insert-if-missing leaves both as they are on a stack that still seeds them.
DEFAULTS = {
    "OPS_BOOTSTRAP_TENANT_ID": "local",
    "OPS_BOOTSTRAP_TENANT_NAME": "Local tenant",
    "OPS_BOOTSTRAP_TEAM_NAME": "Security",
    "OPS_BOOTSTRAP_ADMIN_EMAIL": "dev-admin@harborpine.example",
    "OPS_BOOTSTRAP_ADMIN_NAME": "Dev Admin",
}


def read(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main() -> int:
    values = read(ENV_FILE) if ENV_FILE.exists() else {}
    if not values.get("OPS_BOOTSTRAP_ADMIN_PASSWORD"):
        values = DEFAULTS | values | {"OPS_BOOTSTRAP_ADMIN_PASSWORD": secrets.token_urlsafe(18)}
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        ENV_FILE.touch(mode=0o600)
        ENV_FILE.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
        print(f"first admin: {values['OPS_BOOTSTRAP_ADMIN_EMAIL']}, password kept in {ENV_FILE}")
    env = os.environ | {k: v for k, v in values.items() if k.startswith("OPS_BOOTSTRAP_")}
    done = subprocess.run([sys.executable, "-m", "ops_platform.bootstrap"], env=env, check=False)
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main())
