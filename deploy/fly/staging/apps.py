"""Ops AI staging on Fly from the per-service images (deploy/fly/Dockerfile targets): one Fly app per image, talking
over Fly's private network, one public app (the proxy) as the origin. This file is the one source for which apps
exist, their sizes and their settings; runbook docs/deploy/fly.md.

    uv run python deploy/fly/staging/apps.py write              writes deploy/fly/staging/<app>.toml (committed)
    uv run python deploy/fly/staging/apps.py secrets --db <file> --admin <file> --logins <file> [--models <file>]
                                                                 generates keys and stages each app's share
    uv run python deploy/fly/staging/apps.py order              the deploy order, one app per line
    uv run python deploy/fly/staging/apps.py one-secrets --db <file> --admin <file> --logins <file> --models <file>
                                                                 stages every app's share on the one-machine app

`secrets` never prints a value. Each app gets its own signing key, the public keys, and only the keys its service
uses (deploy/images/service_keys.py); a generated key an app holds but does not use is unset. The database URL (the
one `fly postgres attach` printed) and the first admin's email and password come from files; each app's set is piped
to `fly secrets import --stage`. Keys are generated once and kept in `--keep <file>` (mode 600, outside the repo); the
model keys come from connect_model.py, run on the agents app.

`one-secrets` stages the same values on the one-machine app (deploy/fly/fly.toml, runbook docs/deploy/fly-staging.md):
every service's login as OPS_DATABASE_URL_<SERVICE>, every signing key, the superuser as OPS_DATABASE_URL for the
release command alone, and the model keys; deploy/fly/processes.toml hands each process only its own.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def _service_keys() -> dict[str, tuple[str, ...]]:
    spec = importlib.util.spec_from_file_location("service_keys", HERE.parents[1] / "images" / "service_keys.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(dict[str, tuple[str, ...]], module.USES)


USES = _service_keys()
PREFIX = "<your-app>"
ORG = "<your-org>"
REGION = "ewr"
ORIGIN = f"https://{PREFIX}-web.fly.dev"


def internal(app: str, port: int) -> str:
    """An app's address on Fly's private network (IPv6), which every app listens on."""
    return f"{PREFIX}-{app}.internal:{port}"


@dataclass(frozen=True)
class App:
    name: str
    target: str  # the Dockerfile stage
    memory_mb: int
    port: int | None = None
    health: str | None = None
    command: str | None = None
    # The service's own signing key (generate_keys.py names), so each signs as itself.
    signs_as: str | None = None
    env: dict[str, str] = field(default_factory=lambda: {})
    public: bool = False
    release: str | None = None
    # A one-shot app: its process runs to the end and is never restarted (the migrate job).
    once: bool = False
    # A Fly volume mounted at /data, which Fly hands to the image's user (uid 10001), so bytes survive a redeploy.
    volume: str | None = None
    python: bool = True
    models_key: str | None = None


# Sizes from the compose run after the walk (c-203): agents 224 MB, worker 202, console 253, the rest under 110.
# Every Python service reads these (the compose file's x-settings, with Fly's private addresses).
SETTINGS: dict[str, str] = {
    "OPS_ENVIRONMENT": "production",
    "OPS_AUTH_MODE": "platform",
    # Every address: Fly's health checks come over IPv4 and its private network is IPv6.
    "OPS_BIND_HOST": "*",
    "OPS_CORS_ORIGINS": json.dumps([ORIGIN]),
    "OPS_CONSOLE_URL": ORIGIN,
    "OPS_PLATFORM_PUBLIC_URL": f"{ORIGIN}/api/platform",
    "OPS_FILES_PUBLIC_URL": f"{ORIGIN}/api/files",
    "OPS_PLATFORM_URL": f"http://{internal('platform', 8710)}",
    "OPS_PLATFORM_INTERNAL_URL": f"http://{internal('platform', 8711)}",
    "OPS_AGENTS_URL": f"http://{internal('agents', 8700)}",
    "OPS_GATEWAY_URL": f"http://{internal('tools', 8720)}",
    "OPS_TOOLS_URL": f"http://{internal('tools', 8720)}",
    "OPS_MODELS_URL": f"http://{internal('models', 8730)}",
    "OPS_KB_URL": f"http://{internal('kb', 8740)}",
    "OPS_FILES_URL": f"http://{internal('files', 8750)}",
    "OPS_DOCUMENTS_URL": f"http://{internal('documents', 8760)}",
    "OPS_RUNNER_URL": f"http://{internal('runner', 8770)}",
    "OPS_OPA_URL": f"http://{internal('opa', 8181)}",
    # files-service keeps bytes on its volume (below); knowledge-base bytes stay on the kb machine's disk until a
    # Security admin points storage at a bucket (Settings > Storage), and a redeploy of kb loses them.
    "OPS_FILES_DIR": "/tmp/ops/files",
    "OPS_KB_FILES_DIR": "/tmp/ops/kb-files",
    "OPS_FILES_SCANNING": "eicar",
    "OPS_MAILBOX_SOURCE": "none",
    "OPS_MAIL_PROVIDER": "none",
    "OPS_BOOTSTRAP_TENANT_ID": "local",
}

APPS: list[App] = [
    # Every chain, then the first admin (deploy/images/migrate.sh), as the database's superuser: the only app that
    # holds it. Deployed first. The release command migrates on every deploy, before the new image is live; a deploy
    # only reconfigures a stopped machine, so the machine itself runs once, when it is made, and stays stopped.
    App("migrate", "platform", 256, command="migrate", release="migrate", once=True),
    App(
        "platform",
        "platform",
        256,
        8710,
        "/v1/health",
        signs_as="PLATFORM",
    ),
    App(
        "opa",
        "opa",
        256,
        8181,
        "/health",
        command="run --server --addr [::]:8181 --log-level error /policy",
        python=False,
    ),
    App("tools", "tools", 256, 8720, "/health", signs_as="TOOLS"),
    # Code tools' functions on WASM (c-531): 512 MB for two runs at the default 256 MB cap each.
    App("runner", "runner", 512, 8770, "/health", signs_as="RUNNER"),
    App("models", "models", 256, 8730, "/health", signs_as="MODELS"),
    # The fake model: answers from committed rules and never calls a provider. Staging's only model connection.
    App(
        "fake",
        "models",
        256,
        8746,
        "/health",
        command="python -m fake_openai /app/services/models-service/seed/demo-fake-openai",
        env={
            "FAKE_OPENAI_HOST": "*",
            "FAKE_OPENAI_PORT": "8746",
            "PYTHONPATH": "/app/services/models-service/scripts",
        },
        python=False,
    ),
    # The bank stand-in (services/tools-service/scripts/fake_bank): the outside core banking system and webhook
    # receiver the levy workflows call, with synthetic customers only. Public so tools-service reaches it as it would a
    # real bank, over https and the egress allow-list; every route but its OpenAPI document needs FAKE_BANK_KEY.
    App(
        "bank",
        "tools",
        256,
        8080,
        "/openapi.json",
        # IPv4: Fly's proxy connects over it, and uvicorn's "::" socket is IPv6-only. Callers use the public https URL.
        command=(
            "python -m uvicorn --app-dir /app/services/tools-service/scripts fake_bank.app:app"
            " --host 0.0.0.0 --port 8080"
        ),
        env={"FAKE_BANK_PUBLIC_URL": f"https://{PREFIX}-bank.fly.dev"},
        public=True,
        python=False,
    ),
    App("kb", "kb", 256, 8740, "/health", signs_as="KB"),
    App(
        "files",
        "files",
        256,
        8750,
        "/health",
        signs_as="FILES",
        volume="files_data",
        env={"OPS_FILES_DIR": "/data/files"},
    ),
    App("documents", "documents", 512, 8760, "/health", signs_as="DOCUMENTS", models_key="OPS_MODELS_KEY_DOCUMENTS"),
    App(
        "agents",
        "agents",
        512,
        8700,
        "/health",
        signs_as="AGENTS",
        models_key="OPS_MODELS_KEY_AGENTS",
    ),
    # The workflow runner: the agents image with the worker command; it serves no port.
    App(
        "worker",
        "agents",
        512,
        command="python -m ops_agents.api.worker",
        signs_as="AGENTS",
        models_key="OPS_MODELS_KEY_AGENTS",
    ),
    App(
        "console",
        "console",
        512,
        3016,
        "/login",
        python=False,
        env={
            "HOSTNAME": "::",
            "NEXT_PUBLIC_OPS_PLATFORM_API_URL": f"{ORIGIN}/api/platform",
            "NEXT_PUBLIC_OPS_CHAT_API_URL": f"{ORIGIN}/api/agents",
            "NEXT_PUBLIC_OPS_CASES_API_URL": f"{ORIGIN}/api/agents",
            "NEXT_PUBLIC_OPS_REGISTRY_API_URL": f"{ORIGIN}/api/agents",
            "NEXT_PUBLIC_OPS_TOOLS_API_URL": f"{ORIGIN}/api/tools",
            "NEXT_PUBLIC_OPS_KNOWLEDGE_API_URL": f"{ORIGIN}/api/kb",
            "NEXT_PUBLIC_OPS_FILES_API_URL": f"{ORIGIN}/api/files",
            "NEXT_PUBLIC_OPS_DOCUMENTS_API_URL": f"{ORIGIN}/api/documents",
        },
    ),
    App(
        "web",
        "proxy",
        256,
        8080,
        "/api/platform/v1/health",
        public=True,
        python=False,
        env={
            "OPS_UPSTREAM_PLATFORM": internal("platform", 8710),
            "OPS_UPSTREAM_AGENTS": internal("agents", 8700),
            "OPS_UPSTREAM_TOOLS": internal("tools", 8720),
            "OPS_UPSTREAM_KB": internal("kb", 8740),
            "OPS_UPSTREAM_FILES": internal("files", 8750),
            "OPS_UPSTREAM_DOCUMENTS": internal("documents", 8760),
            "OPS_UPSTREAM_CONSOLE": internal("console", 3016),
        },
    ),
]


def _q(v: str) -> str:
    return json.dumps(v)


def toml(app: App) -> str:
    env = {**(SETTINGS if app.python else {}), **app.env}
    lines = [
        f"# Generated by deploy/fly/staging/apps.py; edit there. Image: deploy/fly/Dockerfile target {app.target}.",
        f"# Deploy from the repo root: fly deploy . -c deploy/fly/staging/{app.name}.toml --local-only",
        f'app = "{PREFIX}-{app.name}"',
        f'primary_region = "{REGION}"',
        'kill_signal = "SIGTERM"',
        "kill_timeout = 20",
        "",
        "[build]",
        '  dockerfile = "../Dockerfile"',
        '  ignorefile = "../Dockerfile.dockerignore"',
        f'  build-target = "{app.target}"',
    ]
    if app.release:
        lines += ["", "[deploy]", f'  release_command = "{app.release}"', '  strategy = "immediate"']
    else:
        lines += ["", "[deploy]", '  strategy = "immediate"']
    if app.command:
        lines += ["", "[processes]", f"  app = {_q(app.command)}"]
    if app.once:
        lines += ["", "[[restart]]", '  policy = "never"']
    lines += ["", "[env]"] + [f"  {k} = {_q(v)}" for k, v in env.items()]
    if app.public:
        lines += [
            "",
            "[http_service]",
            f"  internal_port = {app.port}",
            "  force_https = true",
            '  auto_stop_machines = "off"',
            "  auto_start_machines = true",
            "  min_machines_running = 1",
        ]
        # Fly refuses a service with no processes on an app that names one.
        if app.command:
            lines += ['  processes = ["app"]']
    if app.health and app.port:
        lines += [
            "",
            "[checks.health]",
            '  type = "http"',
            f"  port = {app.port}",
            f'  path = "{app.health}"',
            '  interval = "30s"',
            '  timeout = "5s"',
            '  grace_period = "60s"',
        ]
    if app.volume:
        lines += ["", "[[mounts]]", f'  source = "{app.volume}"', '  destination = "/data"', '  initial_size = "1gb"']
    lines += ["", "[[vm]]", '  size = "shared-cpu-1x"', f"  memory = {app.memory_mb}", ""]
    return "\n".join(lines)


def write() -> None:
    for app in APPS:
        (HERE / f"{app.name}.toml").write_text(toml(app))
    print(f"wrote {len(APPS)} configs in {HERE.relative_to(HERE.parents[2])}")


def _read_pairs(path: Path) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            pairs[k.strip()] = v.strip()
    return pairs


def _prune(app: str, not_yours: set[str]) -> None:
    """Unsets every generated key the app holds but does not use: `fly secrets import` adds and updates, never
    removes, so a key handed out by an earlier run would otherwise stay. Names only are read and printed."""
    listed = subprocess.run(["fly", "secrets", "list", "-a", app, "--json"], capture_output=True, text=True, check=True)
    held = {str(x.get("Name") or x.get("name")) for x in json.loads(listed.stdout or "[]")}
    extra = sorted(held & not_yours)
    if extra:
        subprocess.run(["fly", "secrets", "unset", "--stage", "-a", app, *extra], capture_output=True, check=True)
        print(f"{app}: unset {', '.join(extra)}")


def _database(db_file: Path, logins_file: Path) -> tuple[str, Callable[[str], str]]:
    """The superuser DSN and a builder of each service's login DSN, both in SQLAlchemy's asyncpg form."""
    # `fly postgres attach` prints postgres://...?sslmode=disable; asyncpg takes no sslmode and the cluster is reached
    # over the private network.
    url = db_file.read_text().strip().split("?")[0]
    superuser = "postgresql+asyncpg://" + url.split("://", 1)[1]
    host_and_db = url.rsplit("@", 1)[1]
    # One login per service (make db-ddl's roles.sql, applied to the cluster); passwords from `logins_file`.
    logins = _read_pairs(logins_file)

    def login(chain: str) -> str:
        role = f"ops_{chain}_runtime"
        return f"postgresql+asyncpg://{role}:{quote(logins[role], safe='')}@{host_and_db}"

    return superuser, login


def one_secrets(db_file: Path, admin_file: Path, keep: Path, models_file: Path, logins_file: Path, *, app: str) -> None:
    """Every value the per-service apps hold, on one app; processes.toml's `withhold` keeps each with its process."""
    if not app.startswith(PREFIX):
        sys.exit(f"{app}: only {PREFIX}* apps")
    keys = _read_pairs(keep)
    superuser, login = _database(db_file, logins_file)
    values = dict(keys)
    values["OPS_DATABASE_URL"] = superuser
    values |= {f"OPS_DATABASE_URL_{chain.upper()}": login(chain) for chain in USES}
    values |= {k: v for k, v in _read_pairs(admin_file).items() if k.startswith("OPS_BOOTSTRAP_")}
    values |= {k: v for k, v in _read_pairs(models_file).items() if k.startswith("OPS_MODELS_KEY_")}
    run = subprocess.run(
        ["fly", "secrets", "import", "--stage", "-a", app],
        input="".join(f"{k}={v}\n" for k, v in values.items()),
        text=True,
        capture_output=True,
        check=False,
    )
    state = "staged" if run.returncode == 0 else f"FAILED: {run.stderr.strip()[:200]}"
    print(f"{app}: {len(values)} secrets {state} ({', '.join(sorted(values))})")
    if run.returncode:
        sys.exit(1)


def secrets(db_file: Path, admin_file: Path, keep: Path, models_file: Path | None, logins_file: Path) -> None:
    from generate_keys import generate  # noqa: PLC0415 - deploy/fly, on the path above

    if keep.exists():
        keys = _read_pairs(keep)
    else:
        keys = generate()
        keep.touch(mode=0o600)
        keep.write_text("".join(f"{k}={v}\n" for k, v in keys.items()))
    # `fly postgres attach` prints postgres://...?sslmode=disable; asyncpg takes no sslmode and the cluster is reached
    # over the private network.
    superuser, login = _database(db_file, logins_file)
    admin = _read_pairs(admin_file)
    models = _read_pairs(models_file) if models_file else {}
    for app in APPS:
        if not app.python and app.name != "fake":
            continue
        values: dict[str, str] = {}
        if app.signs_as:
            values |= {
                "OPS_DATABASE_URL": login(app.signs_as.lower()),
                "OPS_SERVICE_PUBLIC_KEYS": keys["OPS_SERVICE_PUBLIC_KEYS"],
                "OPS_SERVICE_SIGNING_KEY": keys[f"OPS_SVC_KEY_{app.signs_as}"],
                "OPS_SERVICE_SIGNING_KID": f"svc-{app.signs_as.lower()}-1",
            }
        if app.signs_as:
            # Only the keys the service uses (deploy/images/service_keys.py), so none holds one it does not need.
            values |= {k: keys[k] for k in USES[app.signs_as.lower()]}
        if app.once:
            values |= {"OPS_DATABASE_URL": superuser}
            values |= {k: v for k, v in admin.items() if k.startswith("OPS_BOOTSTRAP_")}
        if app.models_key and models.get(app.models_key):
            values["OPS_MODELS_KEY"] = models[app.models_key]
        if not values:
            continue
        # The attach's DATABASE_URL (a superuser) and the first admin's values belong to the migrate app alone.
        managed = set(keys) | {"DATABASE_URL"} | {k for k in admin if k.startswith("OPS_BOOTSTRAP_")}
        _prune(f"{PREFIX}-{app.name}", managed - set(values))
        body = "".join(f"{k}={v}\n" for k, v in values.items())
        run = subprocess.run(
            ["fly", "secrets", "import", "--stage", "-a", f"{PREFIX}-{app.name}"],
            input=body,
            text=True,
            capture_output=True,
            check=False,
        )
        state = "staged" if run.returncode == 0 else f"FAILED: {run.stderr.strip()[:200]}"
        print(f"{PREFIX}-{app.name}: {len(values)} secrets {state} ({', '.join(sorted(values))})")
        if run.returncode:
            sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("write")
    sub.add_parser("order")
    s = sub.add_parser("secrets")
    s.add_argument("--db", type=Path, required=True, help="a file holding the attach's DATABASE_URL")
    s.add_argument("--admin", type=Path, required=True, help="OPS_BOOTSTRAP_* lines for the first admin")
    s.add_argument("--keep", type=Path, default=Path(os.path.expanduser("~/.config/ops-ai/staging-keys.env")))
    s.add_argument("--models", type=Path, help="OPS_MODELS_KEY_AGENTS and OPS_MODELS_KEY_DOCUMENTS lines")
    s.add_argument(
        "--logins", type=Path, required=True, help="ops_<service>_runtime=password lines (roles.sql's logins)"
    )
    o = sub.add_parser("one-secrets")
    o.add_argument("--db", type=Path, required=True, help="a file holding the attach's DATABASE_URL")
    o.add_argument("--admin", type=Path, required=True, help="OPS_BOOTSTRAP_* lines for the first admin")
    o.add_argument("--keep", type=Path, default=Path(os.path.expanduser("~/.config/ops-ai/staging-keys.env")))
    o.add_argument("--models", type=Path, required=True, help="OPS_MODELS_KEY_* lines")
    o.add_argument("--logins", type=Path, required=True, help="ops_<service>_runtime=password lines")
    o.add_argument("--app", default=f"{PREFIX}-one")
    a = ap.parse_args()
    if a.cmd == "write":
        write()
    elif a.cmd == "one-secrets":
        one_secrets(a.db, a.admin, a.keep, a.models, a.logins, app=a.app)
    elif a.cmd == "order":
        print("\n".join(f"{PREFIX}-{app.name}" for app in APPS))
    else:
        a.keep.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        secrets(a.db, a.admin, a.keep, a.models, a.logins)


if __name__ == "__main__":
    main()
