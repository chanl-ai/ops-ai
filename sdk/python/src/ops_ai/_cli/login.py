"""`ops login`: signs a person in with their email and password and keeps the session in a profile (its address,
team, access token and refresh token), so every later `ops` command and `OpsAI(profile=...)` acts as them and renews
the session on its own. `--as` signs in a dev seed person on a local stack instead. No token is printed."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from typing import Any, cast

from ops_ai._config import profile_values, save_profile

from .common import dev_sign_in, emit, parser, refuse, sign_in, team_of


def main(argv: list[str]) -> int:
    ap = parser("ops login", "Sign in and keep the session in a profile.")
    ap.add_argument("--email", help="your work email; asked when not given")
    ap.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
    ns = ap.parse_args(argv)
    try:
        return _login(ns)
    except Exception as exc:
        return refuse(exc)


def _login(ns: argparse.Namespace) -> int:
    name = ns.profile or os.environ.get("OPS_PROFILE") or "default"
    if ns.as_role:
        base, services, session, team = dev_sign_in(ns)
    else:
        services: dict[str, str] = {}
        base = ns.base_url or os.environ.get("OPS_BASE_URL") or profile_values(name).get("baseUrl")
        if not base:
            raise ValueError(
                "ops login needs the Ops AI address: --base-url, OPS_BASE_URL, or one saved in the profile"
            )
        email = ns.email or input("Work email: ").strip()
        password = sys.stdin.readline().rstrip("\n") if ns.password_stdin else getpass.getpass("Password: ")
        session = sign_in(base, services, email, password)
        team = team_of(ns.team, session)
    fields = {
        "baseUrl": base,
        "accessToken": session["token"],
        "refreshToken": session["refreshToken"],
        **({"team": team} if team else {}),
        **({"services": services} if services else {}),
    }
    path = save_profile(name, fields, current=True)
    email = str(cast(dict[str, Any], session.get("principal") or {}).get("email", ""))
    return emit(
        ns,
        {"profile": name, "email": email, "team": team, "file": str(path)},
        text=f"Signed in as {email}{f' in {team}' if team else ''}; profile {name} in {path}",
    )
