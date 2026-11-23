"""One account per member role on any install, so walks, smokes and API calls can act as each role there.

    make seed-roles [ENV=local|staging]     seed, then check; run by make up and by make stg-deploy
    python3 deploy/fly/role_accounts.py check --platform <platform-service URL> [--dev]
    uv run python deploy/fly/role_accounts.py seed --platform <URL> --admin-env <file> [--generate]

Where the accounts come from depends on the install's mode:

- Dev mode (local stack, preview, ci-local): platform-service seeds services/platform-service/seed/people.json at
  boot and every seeded person signs in with the shared dev password (OPS_PLATFORM_DEMO_PASSWORD).
- Deployed (staging): `seed` invites any account the install lacks into one team, as the first admin, with the address
  and password in $OPS_STAGING_CONFIG/staging-roles.env (the GitHub secret STAGING_ROLES_ENV on a runner).

A deployed install seeds no people and accepts no shared password, so the dev people do not exist on it.

`seed` is safe to run again: an account that is an active member with its role is left as it is. A role the file has no
lines for is refused, naming the fix, unless --generate is given (a person's machine only: it makes an address and a
password and appends them to the file; a runner's file is thrown away, so a deploy never invents one).
`check` signs in once as each role (wrong passwords lock an address) and reads /v1/me: it fails on a missing account, a
refused sign-in or another role in the team, and each FAIL line names its fix. It reads only.

Emails and passwords are never printed. Template: deploy/fly/staging-roles.env.example. Runbook:
docs/deploy/fly-staging.md, "Role accounts".
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = ROOT / "services" / "platform-service" / "seed"
# The member roles of packages/ops_access (MEMBER_ROLES_BY_RANK). Fixed here, so a file that drops a role fails.
ROLES = ("admin", "builder", "approver", "viewer", "chat_user")
FILE = "staging-roles.env"
TEAM_KEY = "STG_ROLES_TEAM"
SEED_FIX = "make seed-roles ENV=staging"


@dataclass(frozen=True)
class Account:
    email: str
    password: str
    team: str


def roles_file() -> Path:
    return Path(os.environ.get("OPS_STAGING_CONFIG") or Path.home() / ".config" / "ops-ai") / FILE


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))
    return {k.strip(): v.strip() for k, v in pairs}


def deployed_account(values: dict[str, str], role: str) -> Account | None:
    """The role's account from staging-roles.env, or None when the team, the email or the password is missing."""
    email = values.get(f"STG_ROLE_{role.upper()}_EMAIL", "")
    password = values.get(f"STG_ROLE_{role.upper()}_PASSWORD", "")
    team = values.get(TEAM_KEY, "")
    return Account(email, password, team) if email and password and team else None


def dev_account(role: str) -> Account | None:
    """The role's seeded dev person: the one dev-roles.json names, else the first person who holds only that role."""
    named = json.loads((SEED_DIR / "dev-roles.json").read_text()).get(role)
    password = os.environ.get("OPS_PLATFORM_DEMO_PASSWORD") or "northfield-demo"
    for person in json.loads((SEED_DIR / "people.json").read_text())["people"]:
        teams = [team for team, held in person["teams"].items() if held == role]
        if teams and (person["email"] == named or (named is None and len(person["teams"]) == 1)):
            return Account(person["email"], password, teams[0])
    return None


def _call(platform: str, path: str, body: dict[str, Any] | None = None, token: str = "") -> tuple[int, Any]:
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    req = urllib.request.Request(
        platform + path, data=None if body is None else json.dumps(body).encode(), headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r).get("data")
    except urllib.error.HTTPError as e:
        return e.code, None


def problem_with(platform: str, role: str, who: Account | None, *, dev: bool) -> str | None:
    """None when the role's account signs in and holds the role in its team; else what is wrong and how to fix it."""
    if who is None:
        if dev:
            return "no seeded person holds it in services/platform-service/seed/people.json"
        return f"no account (or no {TEAM_KEY}) in {roles_file()}; fix: {SEED_FIX}"
    status, session = _call(platform, "/v1/auth/sign-in", {"email": who.email, "password": who.password})
    if status != 200 or not session:
        if dev:
            return (
                f"sign-in answered {status}; platform-service seeds its people at boot; fix: make restart SVC=platform"
            )
        return (
            f"sign-in answered {status}; the account's password on this install differs from {roles_file()}; "
            "fix: reset it in the console (Settings, People) and put the new one in the file"
        )
    status, me = _call(platform, "/v1/me", token=session["token"])
    if status != 200 or not me:
        return f"signed in, but /v1/me answered {status}; the session platform issued is not accepted"
    held = next((t.get("role") for t in me.get("teams") or [] if t.get("id") == who.team), None)
    if held != role:
        fix = "make restart SVC=platform" if dev else SEED_FIX
        return f"signed in, but holds {held or 'no role'} in {who.team}, not {role}; fix: {fix}"
    return None


def check(platform: str, *, dev: bool) -> int:
    values = {} if dev else read_env(roles_file())
    failed = 0
    for role in ROLES:
        problem = problem_with(platform, role, dev_account(role) if dev else deployed_account(values, role), dev=dev)
        failed += problem is not None
        print(
            f"FAIL role {role}: {problem}" if problem else f"ok role {role} signs in and holds it in its team",
            flush=True,
        )
    return failed


def seed(platform: str, admin_env: Path, *, generate: bool) -> int:
    """Invites each role account the deployed install lacks; returns how many roles could not be seeded."""
    # sample_team owns invitations (ensure_members); it needs httpx, so this half runs under uv.
    sys.path.insert(0, str(ROOT / "scripts"))
    import sample_team  # noqa: PLC0415

    admin_values = sample_team.read_env(admin_env)
    admin_email = admin_values["OPS_BOOTSTRAP_ADMIN_EMAIL"]
    path = roles_file()
    values = read_env(path)
    team = os.environ.get(TEAM_KEY) or values.get(TEAM_KEY, "")
    if not team:
        print(f"seed-roles: {TEAM_KEY} is not set in {path} (deploy/fly/staging-roles.env.example)", file=sys.stderr)
        return 1
    urls = {"platform": platform}
    admin = sample_team.sign_in(urls, admin_email, admin_values["OPS_BOOTSTRAP_ADMIN_PASSWORD"], team)
    new_lines = [] if values.get(TEAM_KEY) else [f"{TEAM_KEY}={team}"]
    failed = 0
    for role in ROLES:
        who = deployed_account(values | {TEAM_KEY: team}, role)
        made = who is None
        if who is None:
            if not generate:
                failed += 1
                print(f"FAIL role {role}: no account in {path}; fix: {SEED_FIX} on a machine that keeps the file")
                continue
            domain = admin_email.rpartition("@")[2]
            who = Account(f"walk-{role.replace('_', '-')}@{domain}", secrets.token_urlsafe(18), team)
        try:
            # ensure_members prints the address; a deploy log is public, so its lines are kept out of it.
            with contextlib.redirect_stdout(io.StringIO()) as said:
                sample_team.ensure_members(admin, team, [(who.email, role)], who.password)
        except sample_team.Refused as refused:
            failed += 1
            print(
                f"FAIL role {role}: the invitation was refused ({refused.code}); the address may have an account "
                f"with another password: reset it in the console and put it in {path}"
            )
            continue
        if made and not said.getvalue().startswith("FAIL"):
            new_lines += [
                f"STG_ROLE_{role.upper()}_EMAIL={who.email}",
                f"STG_ROLE_{role.upper()}_PASSWORD={who.password}",
            ]
        state = said.getvalue().split(" ", 1)[0]
        if state == "FAIL":
            failed += 1
            print(f"FAIL role {role}: no invitation was made for it", flush=True)
            continue
        print(f"{state} role {role}", flush=True)
    if new_lines:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write("\n".join(new_lines) + "\n")
        path.chmod(0o600)
    return failed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "seed"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--platform", required=True, help="platform-service's public URL, e.g. <origin>/api/platform")
        cmd.add_argument("--dev", action="store_true", help="a dev-mode install: the seeded people, the dev password")
    sub.choices["seed"].add_argument("--admin-env", type=Path, help="the first admin's env file (deployed installs)")
    sub.choices["seed"].add_argument("--generate", action="store_true", help="make an account for a role with no lines")
    args = ap.parse_args()
    platform = args.platform.rstrip("/")
    if args.cmd == "check":
        return check(platform, dev=args.dev)
    if args.dev:
        # platform-service seeded these people when it started; there is nothing to invite.
        return check(platform, dev=True)
    if not args.admin_env:
        ap.error("seed needs --admin-env on a deployed install")
    return seed(platform, args.admin_env, generate=args.generate) or check(platform, dev=False)


if __name__ == "__main__":
    sys.exit(main())
