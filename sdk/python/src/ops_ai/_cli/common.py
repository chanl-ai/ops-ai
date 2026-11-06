"""Shared argument parsing, client construction and printing for `ops` areas."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ops_ai import OpsAI
from ops_ai._io import load_data
from ops_ai.errors import OpsError


def parser(prog: str, description: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=prog, description=description)
    _options(ap)
    return ap


def verb_options() -> argparse.ArgumentParser:
    """The same options for a verb's own parser, so they may follow its arguments (`ops resources list x --json`). Unset
    there, they keep what was given before the verb."""
    parent = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    _options(parent)
    return parent


def _options(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--profile")
    ap.add_argument("--team")
    ap.add_argument("--base-url")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument(
        "--as",
        dest="as_role",
        metavar="ROLE",
        help="dev only: sign in as a dev seed person (a role of seed/dev-roles.json, or an email) on a local stack",
    )


# A local stack's services, each at its own port as `make` starts them (make/env.mk), when its port is named.
SERVICE_PORTS = {
    "platform": "OPS_PLATFORM_PORT",
    "agents": "OPS_AGENTS_PORT",
    "tools": "OPS_TOOLS_PORT",
    "kb": "OPS_KB_PORT",
    "files": "OPS_FILES_PORT",
    "documents": "OPS_DOCUMENTS_PORT",
}
DEV_ROLES = Path("services/platform-service/seed/dev-roles.json")


def client(ns: argparse.Namespace) -> OpsAI:
    if getattr(ns, "as_role", None):
        return dev_client(ns)
    return OpsAI(profile=ns.profile, team=ns.team, base_url=ns.base_url)


def dev_client(ns: argparse.Namespace) -> OpsAI:
    """`--as`: a dev seed person signed in through the password sign-in, the way `make api AS=<role>` signs in, acting
    in `--team` or the team their sign-in names. Only against a local stack: the dev seed's password opens nothing
    else."""
    services = {s: f"http://127.0.0.1:{os.environ[v]}" for s, v in SERVICE_PORTS.items() if os.environ.get(v)}
    base = ns.base_url or os.environ.get("OPS_BASE_URL") or services.get("platform") or "http://127.0.0.1:8710"
    if (urlparse(services.get("platform") or base).hostname or "") not in ("127.0.0.1", "localhost"):
        raise ValueError("--as signs in dev seed people on a local stack only")
    email = _dev_email(ns.as_role)
    password = os.environ.get("OPS_PLATFORM_DEMO_PASSWORD") or "northfield-demo"
    anonymous = OpsAI(base_url=base, services=services, access_token="", api_key="", team="")
    session = anonymous.raw.platform.auth_sign_in({"email": email, "password": password})
    anonymous.close()
    principal = session.get("principal") or {}
    team = ns.team or principal.get("teamId") or next(iter(principal.get("teamIds") or []), None)
    return OpsAI(base_url=base, services=services, access_token=session["token"], team=team)


def _dev_email(role: str) -> str:
    if "@" in role:
        return role
    for folder in (Path.cwd(), *Path.cwd().parents):
        if (folder / DEV_ROLES).is_file():
            known: dict[str, str] = json.loads((folder / DEV_ROLES).read_text())
            if role not in known or role.startswith("_"):
                raise ValueError(
                    f"--as {role} is not a dev role; use one of {', '.join(k for k in known if k[0] != '_')}"
                )
            return known[role]
    raise ValueError(f"--as {role}: no {DEV_ROLES} above this folder; give an email instead")


def payload(value: str | None) -> Any:
    if value is None or value == "":
        return {}
    if value == "-":
        return load_data(sys.stdin.read())
    if "=" in value and not Path(value).exists() and not value.startswith("{"):
        out: dict[str, Any] = {}
        for part in value.split(","):
            key, _, item = part.partition("=")
            out[key] = item
        return out
    return load_data(value)


def emit(ns: argparse.Namespace, data: Any, *, text: str | None = None) -> int:
    if ns.as_json:
        sys.stdout.write(json.dumps(data, default=str) + "\n")
        return 0
    if ns.quiet:
        return 0
    sys.stdout.write((text if text is not None else _plain(data)) + "\n")
    return 0


def refuse(exc: BaseException) -> int:
    if isinstance(exc, OpsError):
        path = exc.details.get("path") if isinstance(exc.details, dict) else None
        where = path[0] if isinstance(path, list) and path else path
        sys.stderr.write(f"{exc.code}: {where}: {exc.message}\n" if where else f"{exc.code}: {exc.message}\n")
        return 1
    if isinstance(exc, NotImplementedError):
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stderr.write(f"{exc}\n")
    return 1 if isinstance(exc, ValueError) else 2


def _plain(data: Any) -> str:
    if isinstance(data, str):
        return data
    return json.dumps(data, indent=2, default=str)
