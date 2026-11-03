"""Call any Ops AI API as a standard dev user: `make api GET /v1/me AS=viewer`, `make sdk-call CALL=… AS=…`.

Each role in services/platform-service/seed/dev-roles.json is a seeded person; the call acts in the team the sign-in
names as the person's default (TEAM= overrides). The person signs in through the real password sign-in, POST
/v1/auth/sign-in, with the dev demo password from Settings (local) or the staging admin file (ENV=staging, admin).
The session is kept in .run/api-tokens/<env>-<role>.json (mode 600) until it expires; a 401 drops it and signs in once
more. No password is printed or cached.

    uv run python scripts/api_as.py api GET /v1/me --as viewer [--env staging] [--team t] [--service tools]
    uv run python scripts/api_as.py sdk "ops.raw.platform.me_me()" --as builder
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from ops_service_kit.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "services" / "platform-service" / "seed"
# OPS_API_TOKENS moves the cache, so a use case keeps its tokens apart from the developer's.
CACHE = Path(os.environ.get("OPS_API_TOKENS") or ROOT / ".run" / "api-tokens")
# Port settings as scripts/stack.sh reads them, with its defaults.
PORTS = {
    "platform": ("OPS_PLATFORM_PORT", 8710),
    "agents": ("OPS_AGENTS_PORT", 8700),
    "tools": ("OPS_TOOLS_PORT", 8720),
    "kb": ("OPS_KB_PORT", 8740),
    "files": ("OPS_FILES_PORT", 8750),
    "documents": ("OPS_DOCUMENTS_PORT", 8760),
    "models": ("OPS_MODELS_PORT", 8730),
}


class Refused(SystemExit):
    """A setup problem the developer fixes: printed as one line, exit 2."""

    def __init__(self, message: str) -> None:
        super().__init__(2)
        self.message = message


def roles() -> dict[str, str]:
    return {k: v for k, v in json.loads((SEED / "dev-roles.json").read_text()).items() if not k.startswith("_")}


def team_of(principal: dict[str, Any]) -> str | None:
    """The team a call acts in when none is named: the sign-in's own default team, else its first."""
    return principal.get("teamId") or next(iter(principal.get("teamIds") or []), None)


def _staging_file(name: str) -> dict[str, str]:
    path = Path(os.environ.get("OPS_STAGING_CONFIG") or Path.home() / ".config" / "ops-ai") / name
    if not path.is_file():
        raise Refused(f"api: {path} not found (docs/deploy/fly-staging.md)")
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))
    return {k.strip(): v.strip() for k, v in pairs}


def addresses(env: str) -> dict[str, str]:
    """Each service's base URL: the local stack's ports, or staging's one origin with /api/<service>."""
    if env == "staging":
        app = os.environ.get("STG_APP") or _staging_file("staging.env").get("STG_APP")
        if not app:
            raise Refused("api: STG_APP is not set in ~/.config/ops-ai/staging.env")
        return {svc: f"https://{app}.fly.dev/api/{svc}" for svc in PORTS}
    return {svc: f"http://127.0.0.1:{os.environ.get(var) or port}" for svc, (var, port) in PORTS.items()}


def credentials(env: str, role: str) -> tuple[str, str]:
    """The role's email and password; the password goes only into the sign-in body."""
    if env == "staging":
        if role != "admin":
            raise Refused(f"api: only the staging admin's sign-in is on this machine; AS={role} works only locally")
        admin = _staging_file("staging-admin.env")
        return admin["OPS_BOOTSTRAP_ADMIN_EMAIL"], admin["OPS_BOOTSTRAP_ADMIN_PASSWORD"]
    known = roles()
    if role not in known:
        raise Refused(f"api: AS={role} is not a dev role; use one of {', '.join(known)}")
    return known[role], Settings().platform_demo_password.get_secret_value()


def token(env: str, role: str, urls: dict[str, str], *, fresh: bool = False) -> dict[str, Any]:
    """The role's session (token, email, team), from the cache while it lasts, else from the password sign-in."""
    path = CACHE / f"{env}-{role}.json"
    if not fresh and path.is_file():
        try:
            saved = json.loads(path.read_text())
            live = datetime.fromisoformat(saved["expiresAt"].replace("Z", "+00:00")).timestamp() > time.time() + 30
        except (ValueError, KeyError, TypeError):
            live = False  # an unreadable cache file is no cache
        # A token is good only at the platform-service that issued it: another stack signs with another key.
        if live and saved.get("platform") == urls["platform"]:
            return saved
    email, password = credentials(env, role)
    r = httpx.post(f"{urls['platform']}/v1/auth/sign-in", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        raise Refused(f"api: {email} could not sign in ({r.status_code}): {r.text[:200]}")
    session = r.json()["data"]
    CACHE.mkdir(parents=True, exist_ok=True)
    saved = {
        "email": email,
        "team": team_of(session["principal"]),
        "platform": urls["platform"],
        "token": session["token"],
        "expiresAt": session["expiresAt"],
    }
    path.write_text(json.dumps(saved))
    path.chmod(0o600)
    return saved


def service_for(path: str) -> str:
    """The service whose OpenAPI document holds the path, so a caller names a route and nothing else."""
    bare = path.split("?", 1)[0]
    held: list[str] = []
    for svc in PORTS:
        doc = ROOT / "services" / f"{svc}-service" / "openapi.json"
        templates = json.loads(doc.read_text()).get("paths", {}) if doc.is_file() else {}
        if any(re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", t), bare) for t in templates):
            held.append(svc)
    if len(held) == 1:
        return held[0]
    if held:
        raise Refused(f"api: {bare} is in {' and '.join(held)}; name one with SVC=")
    raise Refused(f"api: no service's OpenAPI document holds {bare}; name one with SVC=")


def call_api(args: argparse.Namespace) -> int:
    urls = addresses(args.env)
    svc = args.service or service_for(args.path)
    body = json.loads(args.body) if args.body else None
    for attempt in (0, 1):
        session = token(args.env, args.role, urls, fresh=attempt == 1)
        email = session["email"]
        headers = {"Authorization": f"Bearer {session['token']}"}
        team = args.team or session.get("team")
        if team:
            headers["X-Team-Id"] = team
        r = httpx.request(args.method.upper(), f"{urls[svc]}{args.path}", json=body, headers=headers, timeout=60)
        if r.status_code != 401 or attempt == 1:
            break
    acting = f", {team}" if team else ""
    print(f"{args.method.upper()} {svc}{args.path} as {args.role} ({email}{acting}): {r.status_code}")
    try:
        print(json.dumps(r.json(), indent=2))
    except ValueError:
        print(r.text)
    return 0 if r.status_code < 400 else 1


def call_sdk(args: argparse.Namespace) -> int:
    # The SDK is a workspace member, so the repo's environment has it; outside the repo `pip install ./sdk/python`.
    from ops_ai import OpsAI  # noqa: PLC0415

    urls = addresses(args.env)
    session = token(args.env, args.role, urls)
    team = args.team or session.get("team")
    with OpsAI(base_url=urls["platform"], services=urls, access_token=session["token"], team=team) as ops:
        # The developer's own one-line call, as `python -c` would run it; nothing outside the command line reaches it.
        result = eval(args.call, {"ops": ops})
    print(json.dumps(result, indent=2, default=str))
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("api", "sdk"):
        s = sub.add_parser(name)
        if name == "api":
            s.add_argument("method")
            s.add_argument("path")
            s.add_argument("--body")
            s.add_argument("--service")
        else:
            s.add_argument("call")
        s.add_argument("--as", dest="role", default="admin")
        s.add_argument("--env", choices=("local", "staging"), default="local")
        s.add_argument("--team")
    args = p.parse_args(argv)
    try:
        return call_api(args) if args.cmd == "api" else call_sdk(args)
    except Refused as e:
        print(e.message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
