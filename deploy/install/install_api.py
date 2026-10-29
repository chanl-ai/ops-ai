"""install.sh's steps that need Python, run inside a service image on the install's own network (no Python on the host):

    python install_api.py secret          sign in as the first admin and save the account's model provider key
    python install_api.py schema          each service's schema version against this image's migration chains
    python install_api.py upgrade-sql DIR each chain's offline upgrade from the revision the database records to head

Inputs come from the environment only, so no secret is ever on a command line: OPS_INSTALL_ADMIN_EMAIL,
OPS_INSTALL_ADMIN_PASSWORD, OPS_INSTALL_SECRET_NAME, OPS_INSTALL_SECRET_VALUE, and OPS_DATABASE_URL_<SERVICE> (or
OPS_DATABASE_URL). Nothing secret is printed.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import httpx

APP = Path("/app")
# The chains in the order deploy/images/chains lists them; each service reads its own version table.
CHAINS = [
    line.strip()
    for line in (APP / "deploy/images/chains").read_text().splitlines()
    if line.strip() and not line.startswith("#")
]


def env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"install: {name} is not set")
    return value


def dsn(chain: str) -> str:
    return os.environ.get(f"OPS_DATABASE_URL_{chain.upper()}") or env("OPS_DATABASE_URL")


def secret() -> None:
    """Saves the key as the account's model provider key (models-service's provider keys) as the first admin, an
    account admin: a new name is created, an existing one replaced. models-service reads it by name (the connection's
    key_ref)."""
    platform = os.environ.get("OPS_PLATFORM_URL", "http://platform:8710")
    models = os.environ.get("OPS_MODELS_URL", "http://models:8730")
    name, value = env("OPS_INSTALL_SECRET_NAME"), env("OPS_INSTALL_SECRET_VALUE")
    with httpx.Client(timeout=20) as c:
        r = c.post(
            f"{platform}/v1/auth/sign-in",
            json={"email": env("OPS_INSTALL_ADMIN_EMAIL"), "password": env("OPS_INSTALL_ADMIN_PASSWORD")},
        )
        if r.status_code != 200:
            sys.exit(f"install: the first admin's sign-in answered {r.status_code}")
        session = r.json()["data"]
        headers = {"Authorization": f"Bearer {session['token']}", "X-Team-Id": session["principal"]["teamId"]}
        saved = c.put(f"{models}/v1/provider-keys/{name}", json={"value": value}, headers=headers)
        if saved.status_code != 200:
            sys.exit(f"install: saving model provider key {name} answered {saved.status_code}: {saved.text[:300]}")
    version = saved.json()["data"]["version"]
    print(f"install: model provider key {'saved' if version == 1 else 'replaced'} as {name}")


async def recorded(url: str) -> list[str]:
    from sqlalchemy.ext.asyncio import create_async_engine  # noqa: PLC0415

    from ops_store.schema_version import recorded_revisions  # noqa: PLC0415

    engine = create_async_engine(url)
    try:
        return await recorded_revisions(engine)
    finally:
        await engine.dispose()


def schema() -> None:
    """Exit 0 when every chain's head is recorded, as each service checks before it serves."""
    from alembic.script import ScriptDirectory  # noqa: PLC0415

    from ops_store.schema_version import verdict  # noqa: PLC0415

    behind = 0
    for chain in CHAINS:
        migrations = APP / "services" / f"{chain}-service" / "migrations"
        try:
            found = asyncio.run(recorded(dsn(chain)))
        except Exception as e:  # unreachable server, refused login: the schema is not readable yet
            print(f"schema: {chain}: not readable ({type(e).__name__})")
            behind += 1
            continue
        problem = verdict(ScriptDirectory(str(migrations)), found, f"{chain}-service")
        print(f"schema: {chain}: {'current' if problem is None else problem}")
        behind += problem is not None
    sys.exit(1 if behind else 0)


def upgrade_sql(out: Path) -> None:
    """Alembic's offline SQL for each chain from the revision the database records to this image's head. A chain
    already at head writes nothing. The DBA runs the files in the order of their numbers, then grants.sql."""
    from alembic.script import ScriptDirectory  # noqa: PLC0415

    out.mkdir(parents=True, exist_ok=True)
    written = 0
    for i, chain in enumerate(CHAINS, 1):
        folder = APP / "services" / f"{chain}-service"
        scripts = ScriptDirectory(str(folder / "migrations"))
        mine = [r for r in asyncio.run(recorded(dsn(chain))) if scripts.get_revision(r) is not None]
        heads = set(scripts.get_heads())
        if not mine:
            sys.exit(f"upgrade-sql: {chain}: the database records none of this release's revisions")
        if any(r in heads for r in mine):
            continue
        run = subprocess.run(
            [str(APP / ".venv/bin/alembic"), "upgrade", f"{mine[0]}:head", "--sql"],
            cwd=folder,
            env={**os.environ, "OPS_DATABASE_URL": "postgresql+asyncpg://offline:offline@localhost:1/offline"},
            capture_output=True,
            text=True,
            check=False,
        )
        if run.returncode:
            sys.exit(f"upgrade-sql: {chain}: alembic could not render {mine[0]} to head: {run.stderr[-800:]}")
        (out / f"{i:02d}-{chain}.sql").write_text(run.stdout)
        print(f"upgrade-sql: {chain}: {mine[0]} to {', '.join(sorted(heads))}")
        written += 1
    print(f"upgrade-sql: {written} chain(s) to upgrade")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "secret":
        secret()
    elif cmd == "schema":
        schema()
    elif cmd == "upgrade-sql" and len(sys.argv) == 3:
        upgrade_sql(Path(sys.argv[2]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
