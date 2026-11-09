"""A Salesforce test sign-in for end-to-end chat scripts, so a script that needs a person signed out and then signed in
runs with nobody at a browser (`make sf-signin-save|remove|restore|env AS=<person>`).

    save     keeps a copy of the person's own Salesforce sign-in row: its token values stay sealed as the store keeps
             them (or as references into the credential store), in `.run/sf-signin/<email>.json`, mode 600; nothing
             of the token is printed
    remove   deletes that row, as the console's Disconnect does, but without revoking it at Salesforce: Disconnect
             (DELETE /v1/me/accounts/{id}) ends the sign-in at the account's revokeUrl, which would end the kept copy
             too, so this writes to the store
    restore  puts the kept row back (the store; no route takes a stored sign-in)
    env      signs the person in with Salesforce's OAuth 2.0 JWT bearer flow (RFC 7523), from keys in the stack's .env
             read by name: SF_TEST_USERNAME, SF_TEST_CLIENT_ID, SF_TEST_JWT_KEY_FILE and SF_TEST_LOGIN_URL (default
             https://login.salesforce.com). The token is sealed by the same code tools-service uses. The JWT flow
             gives no refresh token: run it again when the hour is up.

The person is found the way `opsai --as` finds them (the dev sign-in), so this runs only against a local stack, and the
account through tools-service's own route (GET /v1/me/accounts). Only the store writes go to the database directly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENV_KEYS = ("SF_TEST_USERNAME", "SF_TEST_CLIENT_ID", "SF_TEST_JWT_KEY_FILE")
LOGIN_DEFAULT = "https://login.salesforce.com"
# What a kept row carries back; the store's own keys (tenant, connection, person, team) are named on restore.
KEPT = (
    "access_ct",
    "refresh_ct",
    "expires_at",
    "scopes",
    "account",
    "rotations",
    "refreshed_at",
    "pinned",
    "person_name",
)


class Refused(SystemExit):
    """A plain-words refusal: printed, exit status 2."""

    def __init__(self, said: str) -> None:
        print(f"sf-signin: {said}", file=sys.stderr)
        super().__init__(2)


def env_values(path: Path, keys: tuple[str, ...]) -> dict[str, str]:
    """The named keys from an env file (KEY=value lines), else from the environment; nothing else is read."""
    found: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name.strip().removeprefix("export ").strip() in keys:
                found[name.strip().removeprefix("export ").strip()] = value.strip().strip('"').strip("'")
    return {k: found.get(k) or os.environ.get(k, "") for k in keys}


def missing_keys(values: dict[str, str]) -> list[str]:
    return [k for k in ENV_KEYS if not values.get(k)]


def jwt_assertion(client_id: str, username: str, audience: str, key_pem: str, now: float | None = None) -> str:
    """The JWT bearer grant's assertion: the connected app's consumer key as issuer, the user as subject, the login
    host as audience, three minutes to live, RS256 with the key whose certificate the connected app holds."""
    import jwt  # noqa: PLC0415

    at = int(now if now is not None else time.time())
    claims = {"iss": client_id, "sub": username, "aud": audience.rstrip("/"), "exp": at + 180}
    return jwt.encode(claims, key_pem, algorithm="RS256")


def person(who: str) -> tuple[Any, dict[str, Any]]:
    """The person's SDK client and principal, signed in as `opsai --as` signs in."""
    sys.path.insert(0, str(ROOT / "sdk" / "python" / "src"))
    from ops_ai._cli.common import dev_client, dev_sign_in  # noqa: PLC0415

    ns = argparse.Namespace(as_role=who, team=None, base_url=None, profile=None)
    import jwt  # noqa: PLC0415

    _, _, session, team = dev_sign_in(ns)
    # The session's token names the person's subject and tenant: what tools-service keys their own sign-in by.
    claims = jwt.decode(str(session["token"]), options={"verify_signature": False})
    principal = {**claims, **dict(session.get("principal") or {}), "_team": team}
    return dev_client(ns), principal


def account(ops: Any, app: str) -> dict[str, Any]:
    rows = [r for r in ops.accounts.mine() if r.get("app") == app]
    if not rows:
        raise Refused(f"this person's team has no {app} account to sign in to")
    return rows[0]


def keep_path(email: str) -> Path:
    folder = Path(os.environ.get("OPS_RUN_DIR") or ROOT / ".run") / "sf-signin"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{email.lower()}.json"


def _jsonable(v: Any) -> Any:
    return v.isoformat() if isinstance(v, datetime) else v


def _from_json(k: str, v: Any) -> Any:
    return datetime.fromisoformat(v) if k in ("expires_at", "refreshed_at") and isinstance(v, str) else v


async def run(action: str, who: str, app: str) -> str:
    from ops_service_kit.settings import Settings  # noqa: PLC0415
    from ops_store import isolation  # noqa: PLC0415
    from ops_store.database import open_database  # noqa: PLC0415
    from ops_tools.store.connections import ConnectionStore  # noqa: PLC0415

    values = env_values(Path(os.environ.get("OPS_ENV_FILE") or ROOT / ".env"), (*ENV_KEYS, "SF_TEST_LOGIN_URL"))
    if action == "env" and (missing := missing_keys(values)):
        env_file = Path(os.environ.get("OPS_ENV_FILE") or ROOT / ".env")
        raise Refused(f"add {', '.join(missing)} to {env_file} (the JWT bearer flow's user, connected app and key)")
    ops, principal = person(who)
    tenant = str(principal.get("tenantId") or principal.get("tenant_id") or "")
    key = str(principal.get("sub") or "")
    email = str(principal.get("email") or who)
    if action == "restore":
        # Signed out, the person's accounts list no longer shows the account: the kept copy names it.
        path = keep_path(email)
        if not path.is_file():
            ops.close()
            raise Refused(f"no kept sign-in for {email}; run make sf-signin-save AS={who} while signed in")
        kept = json.loads(path.read_text())
        conn, label = str(kept["connectionId"]), str(kept.get("connection") or app)
    else:
        acc = account(ops, app)
        conn, label = str(acc["connectionId"]), str(acc.get("connection") or app)
    settings = Settings()
    engine = open_database(settings.database_url)
    store = ConnectionStore(engine)
    try:
        with isolation.scope(tenant, str(principal["_team"] or "") or None):
            if action == "save":
                row = await store.token(tenant, conn, key)
                if row is None:
                    raise Refused(f"{email} has no {label} sign-in to keep; sign in once from the Connect card")
                path = keep_path(email)
                kept = {"connectionId": conn, "connection": label, **{k: _jsonable(row[k]) for k in KEPT}}
                path.write_text(json.dumps(kept))
                path.chmod(0o600)
                return f"kept {email}'s {label} sign-in (rotation {row['rotations']}) in {path}"
            if action == "remove":
                gone = await store.forget_token(tenant, conn, key)
                if not gone:
                    return f"{email} had no {label} sign-in; nothing removed"
                return f"removed {email}'s {label} sign-in, not revoked at Salesforce, so restore can put it back"
            if action == "restore":
                values = {k: _from_json(k, kept[k]) for k in KEPT if k in kept}
                await store.replace_token(tenant, str(kept["connectionId"]), values, key)
                return f"restored {email}'s {label} sign-in"
            if action == "env":
                return await sign_in_with_jwt(settings, store, values, tenant, conn, key, email, label)
    finally:
        await engine.dispose()
        ops.close()
    raise Refused(f"unknown action {action}")


async def sign_in_with_jwt(  # noqa: PLR0917
    settings: Any, store: Any, values: dict[str, str], tenant: str, conn: str, key: str, email: str, label: str
) -> str:
    import httpx  # noqa: PLC0415

    from ops_service_kit.credentials import credential_store  # noqa: PLC0415
    from ops_tools.auth.tokens import Tokens  # noqa: PLC0415

    key_file = Path(values["SF_TEST_JWT_KEY_FILE"]).expanduser()
    if not key_file.is_file():
        raise Refused(f"SF_TEST_JWT_KEY_FILE names no file ({key_file})")
    login = (values.get("SF_TEST_LOGIN_URL") or LOGIN_DEFAULT).rstrip("/")
    assertion = jwt_assertion(values["SF_TEST_CLIENT_ID"], values["SF_TEST_USERNAME"], login, key_file.read_text())
    form = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(f"{login}/services/oauth2/token", data=form)
    if r.status_code != 200:
        said = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        why = f"{said.get('error', '')}: {said.get('error_description', '')}"
        raise Refused(f"Salesforce refused the JWT sign-in ({r.status_code} {why})")
    answer = r.json()
    tokens = Tokens(store, credential_store(settings), None, None)
    await tokens.store_answer(tenant, conn, answer, key)
    # The bearer flow answers no id token, so the account is named by the user it signed in as, as a sign-in names it.
    await store.name_token(tenant, conn, key, values["SF_TEST_USERNAME"])
    return f"signed {email} in to {label} as {values['SF_TEST_USERNAME']} by the JWT bearer flow (no refresh token)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("save", "remove", "restore", "env"))
    ap.add_argument("--as", dest="who", required=True, help="a dev seed person: a role, a name or an email")
    ap.add_argument("--app", default="Salesforce")
    ns = ap.parse_args()
    print(asyncio.run(run(ns.action, ns.who, ns.app)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
