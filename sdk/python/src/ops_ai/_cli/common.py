"""Shared argument parsing, client construction and printing for `ops` areas."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from ops_ai import OpsAI
from ops_ai._config import Session
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
        help="dev only: sign in on a local stack as a seeded person: a dev role, a name (james), or an email",
    )


# A local stack's services, each at its own port as `make` starts them (make/env.mk), when its port is named.
SERVICE_PORTS = {
    "platform": "OPS_PLATFORM_PORT",
    "agents": "OPS_AGENTS_PORT",
    "tools": "OPS_TOOLS_PORT",
    "kb": "OPS_KB_PORT",
    "files": "OPS_FILES_PORT",
    "documents": "OPS_DOCUMENTS_PORT",
    "models": "OPS_MODELS_PORT",
}
SEED = Path("services/platform-service/seed")


def client(ns: argparse.Namespace) -> OpsAI:
    if getattr(ns, "as_role", None):
        return dev_client(ns)
    return OpsAI(profile=ns.profile, team=ns.team, base_url=ns.base_url)


def dev_client(ns: argparse.Namespace) -> OpsAI:
    """`--as`: a dev seed person signed in through the password sign-in, the way `make api AS=<role>` signs in, acting
    in `--team` or the team their sign-in names. Only against a local stack: the dev seed's password opens nothing
    else. The session is kept until it expires and renewed on a 401 with its refresh token."""
    base, services, session, team = dev_sign_in(ns)
    if session.get("refreshToken"):
        keep = Session(session["token"], session["refreshToken"], on_renew=session.get("_keep"))
        return OpsAI(base_url=base, services=services, access_token=session["token"], team=team, session=keep)
    return OpsAI(base_url=base, services=services, access_token=session["token"], team=team)


def dev_sign_in(
    ns: argparse.Namespace, *, fresh: bool = False
) -> tuple[str, dict[str, str], dict[str, Any], str | None]:
    """The address, per-service addresses, session and team of a `--as` sign-in; `fresh` signs in again rather than
    use a kept session, which may hold no refresh token (`make api` keeps none)."""
    services = {s: f"http://127.0.0.1:{os.environ[v]}" for s, v in SERVICE_PORTS.items() if os.environ.get(v)}
    base = ns.base_url or os.environ.get("OPS_BASE_URL") or services.get("platform") or "http://127.0.0.1:8710"
    # Both addresses: under `make` the stack's ports are exported, so the platform address is local even when the
    # caller pointed --base-url at another host.
    platform = services.get("platform") or base
    hosts = {urlparse(u).hostname or "" for u in (base, platform)}
    if not hosts <= {"127.0.0.1", "localhost"}:
        raise ValueError("--as signs in dev seed people on a local stack only")
    email = dev_email(ns.as_role)
    session = None if fresh else _cached(ns.as_role, platform)
    if session is None:
        password = os.environ.get("OPS_PLATFORM_DEMO_PASSWORD") or "northfield-demo"
        session = sign_in(base, services, email, password)
        _keep(ns.as_role, platform, session)
    who, kept = ns.as_role, session
    session["_keep"] = lambda token, refresh: _keep(who, platform, {**kept, "token": token, "refreshToken": refresh})
    return base, services, session, team_of(ns.team, session)


def sign_in(base: str, services: dict[str, str], email: str, password: str) -> dict[str, Any]:
    """The password sign-in: the session platform-service answers (token, refresh token, principal)."""
    anonymous = OpsAI(base_url=base, services=services, access_token="", api_key="", team="")
    try:
        return cast(dict[str, Any], anonymous.raw.platform.auth_sign_in({"email": email, "password": password}))
    finally:
        anonymous.close()


def team_of(chosen: str | None, session: dict[str, Any]) -> str | None:
    """`chosen`, else the team the sign-in names as the person's own, else their first."""
    principal = cast(dict[str, Any], session.get("principal") or {})
    return chosen or principal.get("teamId") or next(iter(principal.get("teamIds") or []), None)


def _seed() -> Path:
    for folder in (Path.cwd(), *Path.cwd().parents):
        if (folder / SEED / "dev-roles.json").is_file():
            return folder / SEED
    raise ValueError(f"--as: no {SEED} above this folder; give an email instead")


def dev_email(who: str) -> str:
    """The email `who` names: an email, a dev role (seed/dev-roles.json), or a seeded person's full name, first name or
    email name (seed/people.json)."""
    if "@" in who:
        return who
    roles = _roles()
    if who in roles:
        return roles[who]
    people = cast(list[dict[str, Any]], json.loads((_seed() / "people.json").read_text())["people"])
    wanted = who.strip().lower()
    hits = [
        str(p["email"])
        for p in people
        if wanted in (p["name"].lower(), p["name"].split()[0].lower(), p["email"].split("@")[0].lower())
    ]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise ValueError(f"--as {who} names {len(hits)} people; give the email: {', '.join(hits)}")
    names = ", ".join(p["name"].split()[0].lower() for p in people)
    raise ValueError(f"--as {who} is not a dev role or a seeded person; use one of {', '.join(roles)}, {names}")


def _cache_file(who: str) -> Path | None:
    """The session file `make api AS=` keeps too, so the two share one sign-in per person; none outside the repo, where
    an email signs in each time."""
    tokens = os.environ.get("OPS_API_TOKENS")
    try:
        root = Path(tokens) if tokens else _seed().parents[2] / ".run" / "api-tokens"
    except ValueError:
        return None
    key = dev_email(who) if "@" in who or who not in _roles() else who
    return root / f"local-{re.sub(r'[^a-z0-9._-]', '_', key.lower())}.json"


def _roles() -> dict[str, str]:
    known = json.loads((_seed() / "dev-roles.json").read_text())
    return {k: str(v) for k, v in known.items() if not k.startswith("_")}


def _cached(who: str, platform: str) -> dict[str, Any] | None:
    """A kept session that has not expired, issued by this stack's platform-service (another stack signs with another
    key)."""
    path = _cache_file(who)
    if path is None:
        return None
    try:
        saved = cast(dict[str, Any], json.loads(path.read_text()))
        expires = datetime.fromisoformat(str(saved["expiresAt"]).replace("Z", "+00:00")).timestamp()
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if expires < time.time() + 30 or saved.get("platform") != platform:
        return None
    team = saved.get("team")
    return {**saved, "principal": {"email": saved.get("email"), **({"teamId": team} if team else {})}}


def _keep(who: str, platform: str, session: dict[str, Any]) -> None:
    principal = cast(dict[str, Any], session.get("principal") or {})
    saved = {
        "email": principal.get("email") or session.get("email"),
        "team": team_of(None, session),
        "platform": platform,
        "token": session["token"],
        "refreshToken": session.get("refreshToken"),
        "expiresAt": session.get("expiresAt"),
    }
    path = _cache_file(who)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(saved))
    path.chmod(0o600)


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


def short(value: Any, n: int = 160) -> str:
    """One value on one line, cut to `n` characters."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def table(ns: argparse.Namespace, rows: Any, *columns: str) -> int:
    """A list as one line per row, the named fields in order (a dotted name reads a nested field); `--json` prints the
    rows as they came."""
    items = list(rows or [])
    lines = ["  ".join(short(_field(r, c), 80) for c in columns) for r in items]
    return emit(ns, items, text="\n".join(lines) if lines else "(none)")


def _field(row: Any, name: str) -> Any:
    value = row
    for part in name.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return "-" if value is None or value == "" else value


def console_url(path: str) -> str | None:
    """The console's page for `path` on a local stack, when its port is known (`make` exports it)."""
    port = os.environ.get("OPS_CONSOLE_PORT")
    return f"http://localhost:{port}{path}" if port else None


def values(pairs: list[str] | None) -> dict[str, str]:
    """`k=v` arguments as a dict."""
    out: dict[str, str] = {}
    for pair in pairs or []:
        key, sep, item = pair.partition("=")
        if not sep:
            raise ValueError(f"{pair}: give a field as name=value")
        out[key] = item
    return out


# What a test run makes is named with this prefix, in the title or file name the routes already store, so
# `ops test-data clean` finds it later and nothing unmarked is ever taken for test data.
MARK = "[test] "


def testing(ns: argparse.Namespace) -> bool:
    """A dev seed sign-in (`--as`) is a test run on a local stack; OPS_TEST_DATA=1 marks a profile's runs too."""
    return bool(getattr(ns, "as_role", None)) or os.environ.get("OPS_TEST_DATA") == "1"


def marked(ns: argparse.Namespace, name: str) -> str:
    """`name` with the test-data prefix on a test run, as it is otherwise."""
    return f"{MARK}{name}" if testing(ns) and not name.startswith(MARK) else name
