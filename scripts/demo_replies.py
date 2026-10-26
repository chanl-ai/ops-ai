"""The email-to-reply walk on the shared stack (`make demo-replies`).

Runs `deploy/fly/staging/mailbox_demo.py replies` against the local console origin. Prefers `.run/demo.env` when that
admin can sign in; otherwise uses the people `make up` seeds (same as `scripts/demo_mailbox.py`). The mailbox is one
already connected in the demo team whose host tools-service can resolve (the stack maps mail.harborpine.test).
PASS or FAIL per step; the exit status is the number of failures.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import demo_mailbox as local_demo  # noqa: E402

RUN_DIR = Path(os.environ.get("OPS_RUN_DIR", ROOT / ".run"))
DEMO_ENV = Path(os.environ.get("OPS_DEMO_ENV", RUN_DIR / "demo.env"))
PEOPLE = RUN_DIR / "demo-people.env"
ADMIN_ENV = RUN_DIR / "demo-replies.admin.env"
ORIGIN = os.environ.get("OPS_CONSOLE_ORIGIN", f"http://localhost:{os.environ.get('OPS_CONSOLE_PORT', '3016')}")
TEAM_FILE = ROOT / "scripts" / "demo" / "team.json"
MAILPIT = f"http://127.0.0.1:{os.environ.get('OPS_MAILPIT_HTTP_PORT', '8025')}"
SEND_SMTP = f"127.0.0.1:{os.environ.get('OPS_GREENMAIL_SMTP_PORT', '3025')}"
HARBORPINE_BOX = "notices@harborpine.example"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()))


def sign_in(platform: str, email: str, password: str) -> str | None:
    r = httpx.post(f"{platform}/v1/auth/sign-in", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        return None
    return str(r.json()["data"]["token"])


def main() -> int:
    env = read_env(DEMO_ENV)
    platform = f"http://127.0.0.1:{os.environ.get('OPS_PLATFORM_PORT', '8710')}"
    email = env.get("OPS_DEMO_ADMIN_EMAIL") or env.get("OPS_BOOTSTRAP_ADMIN_EMAIL")
    password = env.get("OPS_DEMO_ADMIN_PASSWORD") or env.get("OPS_BOOTSTRAP_ADMIN_PASSWORD")
    token = sign_in(platform, email, password) if email and password else None
    if token is None:
        email, password = local_demo.SECURITY_ADMIN, local_demo.PASSWORD
        token = sign_in(platform, email, password)
    if token is None:
        print("FAIL  sign-in as the demo admin or the seeded Security admin", flush=True)
        return 1
    write_env(ADMIN_ENV, {"OPS_BOOTSTRAP_ADMIN_EMAIL": email, "OPS_BOOTSTRAP_ADMIN_PASSWORD": password})
    write_env(PEOPLE, {"APPROVER_EMAIL": local_demo.MAYA, "APPROVER_PASSWORD": local_demo.PASSWORD})
    team_name = json.loads(TEAM_FILE.read_text())["team"]["name"]
    teams = httpx.get(
        f"{platform}/v1/settings/teams",
        params={"search": team_name},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if teams.status_code != 200:
        print(f"FAIL  list teams: {teams.status_code}", flush=True)
        return 1
    body = teams.json().get("data") or teams.json()
    rows = body if isinstance(body, list) else body.get("data") or body.get("items") or body.get("rows") or []
    team = next((t for t in rows if str(t.get("name", "")).lower() == team_name.lower()), None)
    if team is None:
        print(
            f"FAIL  demo team '{team_name}' is not on this stack; run scripts/demo/seed_demo_team.py first", flush=True
        )
        return 1
    mailbox = HARBORPINE_BOX
    wanted = env.get("OPS_DEMO_MAILBOX")
    if wanted and "harborpine." in wanted:
        mailbox = wanted
    cmd = [
        sys.executable,
        str(ROOT / "deploy" / "fly" / "staging" / "mailbox_demo.py"),
        "replies",
        "--origin",
        ORIGIN,
        "--admin-env",
        str(ADMIN_ENV),
        "--people",
        str(PEOPLE),
        "--team",
        str(team["id"]),
        "--mailbox",
        mailbox,
        "--send-smtp",
        env.get("OPS_DEMO_SMTP") or SEND_SMTP,
        "--intake-workflow",
        "levy_mail_intake",
        "--document-workflow",
        "levy_reply_document",
        "--read-mailpit",
        MAILPIT,
        "--no-tls",
    ]
    print(f"      demo-replies: team {team['id']} mailbox {mailbox} via {ORIGIN}", flush=True)
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
