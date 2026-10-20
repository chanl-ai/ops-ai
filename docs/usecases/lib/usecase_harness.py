"""What every Python use case script shares: checks that print PASS or FAIL, and services started on the scripted
model on the use-case ports.

The runner (packages/usecase-runner) puts this folder on PYTHONPATH and reads the output: one `PASS <name>` or
`FAIL <name>: <detail>` line per check. A script that prints no check line fails, so a script that silently skips
its assertions cannot pass. Services are started fresh per script and stopped when it ends; a port already in use is
refused rather than reused, so a script never reads another session's state.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Generator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

import httpx

from ops_service_kit.opa_server import opa_server
from ops_signin.fake_idp import self_signed

ROOT = Path(__file__).resolve().parents[3]
AGENTS_DIR = ROOT / "services" / "agents-service"
AGENTS_PORT = int(os.environ.get("OPS_USECASE_AGENTS_PORT", "8790"))
TOOLS_PORT = int(os.environ.get("OPS_USECASE_TOOLS_PORT", "8791"))
MODELS_PORT = int(os.environ.get("OPS_USECASE_MODELS_PORT", "8792"))
KB_PORT = int(os.environ.get("OPS_USECASE_KB_PORT", "8793"))
# The runner does not assign this one yet; unset, a free port, so two runs never share it.
FILES_PORT = int(os.environ.get("OPS_USECASE_FILES_PORT", "0"))
# The committed fake-OpenAI rules (the levy's and the banker demo's), for fake_openai(DEMO_RULES).
DEMO_RULES = ROOT / "services" / "models-service" / "seed" / "demo-fake-openai"
CONSOLE_PORT = int(os.environ.get("OPS_USECASE_CONSOLE_PORT", "3018"))
PLATFORM_PORT = int(os.environ.get("OPS_USECASE_PLATFORM_PORT", "8810"))
PLATFORM_INTERNAL_PORT = int(os.environ.get("OPS_USECASE_PLATFORM_INTERNAL_PORT", "8811"))
IDP_PORT = int(os.environ.get("OPS_USECASE_IDP_PORT", "8797"))
DB = os.environ.get("OPS_USECASE_DB", "ops_usecase")
LOG_DIR = Path(os.environ.get("OPS_LOG_DIR", ROOT / ".logs")) / "usecase"
TEAM = {"X-Team-Id": "team_all"}

# Counts of this run's checks, read by finish().
_tally = {"checked": 0, "failed": 0}


def check(name: str, ok: bool, detail: Any = "") -> bool:
    _tally["checked"] += 1
    if ok:
        print(f"PASS {name}", flush=True)
    else:
        _tally["failed"] += 1
        print(f"FAIL {name}: {detail}", flush=True)
    return ok


def service_headers(
    audience: str,
    *,
    tenant: str = "local",
    service: str = "agents",
    scopes: list[str] | None = None,
    team: str | None = None,
) -> dict[str, str]:
    """A calling service's Ed25519 token for `audience` (the dev key, dev only), naming the tenant it acts for and,
    when given, the `area:action` scopes and team it claims; the callee caps the scopes by `service`."""
    from ops_identity import dev_service_signer, mint_service_token  # noqa: PLC0415

    token = mint_service_token(
        dev_service_signer(),
        service=service,
        audience=audience,
        tenant_id=tenant,
        ttl_s=600,
        scopes=scopes,
        team_id=team,
    )
    return {"Authorization": f"Bearer {token}"}


def finish() -> None:
    if _tally["checked"] == 0:
        print("FAIL no checks ran", flush=True)
        sys.exit(1)
    sys.exit(1 if _tally["failed"] else 0)


def sse(raw: str) -> list[dict[str, Any]]:
    """Splits a stream the way apps/console/src/lib/api/chat-http.ts does: blank-line frames, data lines."""
    out: list[dict[str, Any]] = []
    for frame in raw.split("\n\n"):
        data = "".join(line[5:].strip() for line in frame.split("\n") if line.startswith("data:"))
        if data:
            out.append(json.loads(data))
    return out


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _wait(url: str, proc: subprocess.Popen[bytes], log: Path, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"FAIL service exited before it was healthy; log: {log}\n{log.read_text()[-2000:]}")
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    proc.terminate()
    raise SystemExit(f"FAIL {url} not healthy after {timeout}s; log: {log}")


def _env() -> dict[str, str]:
    # The root .env, exported by make, routes the shared stack through models-service, and make exports the stack's
    # platform-service URL; a use case stack builds its own routes (or none), so the shared values never reach its
    # services. An inherited OPS_PLATFORM_URL made a stack without platform-service build policy readers that fail
    # closed: every publish waited for a review.
    dropped = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPS_MODELS_URL",
        "OPS_MODELS_KEY",
        "OPS_MODELS_FAKE_OPENAI_URL",
        "OPS_PLATFORM_URL",
    )
    env = {k: v for k, v in os.environ.items() if k not in dropped}
    env.pop("VIRTUAL_ENV", None)
    return env


@contextmanager
def _serve(
    name: str, argv: list[str], port: int, env: dict[str, str], *, health: str = "/health", cwd: Path = AGENTS_DIR
) -> Generator[str]:
    if not _port_free(port):
        raise SystemExit(f"FAIL port {port} is already in use; stop that process or set OPS_USECASE_*_PORT")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / f"{name}-{port}.log"
    with log.open("ab") as fh:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        _wait(f"{base}{health}", proc, log)
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@contextmanager
def agents(
    *,
    cors: list[str] | None = None,
    gateway_url: str | None = None,
    models_url: str | None = None,
    models_key: str | None = None,
    model_alias: str | None = None,
    kb_url: str | None = None,
    env: dict[str, str] | None = None,
    timer_poll_seconds: float | None = None,
) -> Generator[httpx.Client]:
    """The agents service on the scripted model, with its own migrated database. With `models_url` it asks that
    models-service which model aliases an agent may name; with `models_key` too, its turns run there, on the scripted
    provider, spending from that key. `model_alias` is the runtime's alias for agents that name none."""
    argv = ["uv", "run", "python", "scripts/scripted_server.py", "--port", str(AGENTS_PORT), "--db", DB]
    for origin in cors or []:
        argv += ["--cors", origin]
    if gateway_url:
        argv += ["--gateway-url", gateway_url]
    if timer_poll_seconds is not None:
        # The timer poller, the one scheduler; off unless a use case waits on a timer (no HTTP route fires one).
        argv += ["--timer-poll-seconds", str(timer_poll_seconds)]
    extra = env or {}
    env = _env()
    # `env` adds OPS_* values a use case needs, e.g. OPS_AGENTS_SEED_FILE for the demo's agents.
    env.update(extra)
    if models_url:
        env["OPS_MODELS_URL"] = models_url
    if models_key:
        env["OPS_MODELS_KEY"] = models_key
    if model_alias:
        env["OPS_MODEL_ALIAS"] = model_alias
    if kb_url:
        env["OPS_KB_URL"] = kb_url
    # Tool module reviews decided in Reviews are applied in tools-service (c-163), with or without a gateway.
    env.setdefault("OPS_TOOLS_URL", f"http://127.0.0.1:{TOOLS_PORT}")
    with ExitStack() as stack:
        if kb_url is None:
            # Every agents stack has a knowledge service: without one, agents that hold knowledge bases are refused.
            files = stack.enter_context(tempfile.TemporaryDirectory(prefix="usecase-kb-"))
            kb_client = stack.enter_context(kb(Path(files)))
            seed_fixture_knowledge(str(kb_client.base_url), kb_client.files_url)
            env["OPS_KB_URL"] = str(kb_client.base_url).rstrip("/")
        base = stack.enter_context(_serve("agents", argv, AGENTS_PORT, env))
        yield stack.enter_context(httpx.Client(base_url=base, timeout=60))


@contextmanager
def engine_worker(name: str, env: dict[str, str] | None = None) -> Generator[subprocess.Popen[bytes]]:
    """The workflow worker on the use case database, polling every 0.2 s, logging to `.logs/usecase/worker-<name>.log`.
    `env` adds the services a use case's steps call (OPS_GATEWAY_URL, OPS_MODELS_URL, ...)."""
    pg = os.environ.get("OPS_PG_PORT", "5477")
    full = (
        _env()
        | {"OPS_DATABASE_URL": f"postgresql+asyncpg://ops:ops@localhost:{pg}/{DB}", "OPS_ENGINE_POLL_SECONDS": "0.2"}
        | (env or {})
    )
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / f"worker-{name}.log").open("ab") as fh:
        proc = subprocess.Popen(
            ["uv", "run", "python", "-m", "ops_agents.api.worker"], cwd=AGENTS_DIR, env=full, stdout=fh, stderr=fh
        )
    try:
        yield proc
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def until(what: Callable[[], Any], timeout: float = 60) -> Any:
    """What `what` returns once it is truthy; None after `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if found := what():
            return found
        time.sleep(0.3)
    return None


@contextmanager
def models(settings: dict[str, str] | None = None) -> Generator[str]:
    """models-service on the use-case database, seeded with its scripted aliases (bank-standard, bank-reasoning,
    bank-embed). `settings` adds OPS_* values, e.g. OPS_MODELS_FAKE_OPENAI_URL. Yields its base URL."""
    migrate = ["uv", "run", "python", "scripts/scripted_server.py", "--port", "0", "--db", DB, "--migrate-only"]
    subprocess.run(migrate, cwd=AGENTS_DIR, env=_env(), check=True, capture_output=True)
    env = _env()
    pg = os.environ.get("OPS_PG_PORT", "5477")
    env["OPS_DATABASE_URL"] = f"postgresql+asyncpg://ops:ops@localhost:{pg}/{DB}"
    env["OPS_MODELS_PORT"] = str(MODELS_PORT)
    env.update(settings or {})
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=ROOT / "services" / "models-service",
        env=env,
        check=True,
        capture_output=True,
    )
    with _serve("models", ["uv", "run", "python", "-m", "ops_models"], MODELS_PORT, env) as base:
        yield base


class Kb(httpx.Client):
    """A client of the run's kb-service, with the files-service it reads its files from and, when started, the
    documents-service that reads what is in them."""

    files_url: str = ""
    documents_url: str = ""


@contextmanager
def kb(
    files_dir: Path,
    *,
    models_url: str | None = None,
    platform_url: str | None = None,
    document_types: bool = False,
    agents_url: str | None = None,
) -> Generator[Kb]:
    """kb-service on the use-case database, its own migration chain applied, reading its files from a files-service
    (dev auth, scanning off) keeping objects under `files_dir`. Yields a client; its base URL is what agents() takes as
    `kb_url`, and `files_url` is where a seed puts the files it adds to a source. With `models_url` or `document_types`
    a documents-service starts beside them (c-256), its extractions calling the model at `models_url` and reading the
    workspace floor at `platform_url`; `document_types` seeds the demo's document types the levy workflows name. With
    `agents_url` files-service delivers its service events (file.deleted) there."""
    # The agents chain creates the run's database; files-service and kb-service migrate into it after.
    migrate = ["uv", "run", "python", "scripts/scripted_server.py", "--port", "0", "--db", DB, "--migrate-only"]
    subprocess.run(migrate, cwd=AGENTS_DIR, env=_env(), check=True, capture_output=True)
    with ExitStack() as stack:
        store = stack.enter_context(files(files_dir, scanning="off", platform_auth=False, agents_url=agents_url))
        files_url = str(store.base_url).rstrip("/")
        documents_url = ""
        if models_url or document_types:
            reader = stack.enter_context(
                documents(files_url, models_url=models_url, platform_url=platform_url, agents_url=agents_url)
            )
            documents_url = str(reader.base_url).rstrip("/")
        if document_types:
            # The demo's document types (levy_notice v1 and its samples), which the seeded levy workflows name.
            subprocess.run(
                [
                    "uv", "run", "python", "scripts/seed_document_types.py",
                    "--documents", documents_url, "--files", files_url, "--dev",
                ],
                cwd=ROOT / "services" / "documents-service",
                env=_env(),
                check=True,
                capture_output=True,
            )  # fmt: skip
        env = _env()
        pg = os.environ.get("OPS_PG_PORT", "5477")
        env["OPS_DATABASE_URL"] = f"postgresql+asyncpg://ops:ops@localhost:{pg}/{DB}"
        env["OPS_KB_PORT"] = str(KB_PORT)
        env["OPS_FILES_URL"] = files_url
        # A knowledge base's "used by" comes from agents-service (c-072 T007), on this run's port rather than the
        # shared stack's.
        env["OPS_AGENTS_URL"] = f"http://127.0.0.1:{AGENTS_PORT}"
        kb_dir = ROOT / "services" / "kb-service"
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"], cwd=kb_dir, env=env, check=True, capture_output=True
        )
        argv = ["uv", "run", "python", "-m", "ops_kb"]
        with _serve("kb", argv, KB_PORT, env, cwd=kb_dir) as base, Kb(base_url=base, timeout=60) as c:
            c.files_url = files_url
            c.documents_url = documents_url
            yield c


@contextmanager
def files(
    files_dir: Path, *, scanning: str = "hook", platform_auth: bool = True, agents_url: str | None = None
) -> Generator[httpx.Client]:
    """files-service on the use-case database, its own chain applied, objects under `files_dir` on the local backend.
    With `platform_auth` it verifies platform-service tokens (start `platform()` first); `scanning` "hook" leaves files
    pending until a scanner posts a verdict."""
    port = FILES_PORT or free_port()
    env = _env()
    pg = os.environ.get("OPS_PG_PORT", "5477")
    env["OPS_DATABASE_URL"] = f"postgresql+asyncpg://ops:ops@localhost:{pg}/{DB}"
    env["OPS_FILES_PORT"] = str(port)
    env["OPS_FILES_DIR"] = str(files_dir)
    env["OPS_FILES_SCANNING"] = scanning
    if agents_url:
        env["OPS_AGENTS_URL"] = agents_url
    if platform_auth:
        env["OPS_AUTH_MODE"] = "platform"
        env["OPS_PLATFORM_URL"] = f"http://127.0.0.1:{PLATFORM_PORT}"
        env["OPS_PLATFORM_INTERNAL_PORT"] = str(PLATFORM_INTERNAL_PORT)
    files_dir_svc = ROOT / "services" / "files-service"
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"], cwd=files_dir_svc, env=env, check=True, capture_output=True
    )
    argv = ["uv", "run", "python", "-m", "ops_files"]
    with _serve("files", argv, port, env, cwd=files_dir_svc) as base, httpx.Client(base_url=base, timeout=30) as c:
        yield c


@contextmanager
def documents(
    files_url: str, *, models_url: str | None = None, platform_url: str | None = None, agents_url: str | None = None
) -> Generator[httpx.Client]:
    """documents-service on the use-case database (c-256), its own chain applied after files', reading bytes from
    `files_url` (dev auth). With `models_url` its extractions call that models-service with its own dev key, and with
    `platform_url` they read the workspace floor there."""
    port = free_port()
    env = _env()
    pg = os.environ.get("OPS_PG_PORT", "5477")
    env["OPS_DATABASE_URL"] = f"postgresql+asyncpg://ops:ops@localhost:{pg}/{DB}"
    env["OPS_DOCUMENTS_PORT"] = str(port)
    env["OPS_FILES_URL"] = files_url
    if models_url:
        env["OPS_MODELS_URL"] = models_url
        env["OPS_MODELS_KEY"] = "mk_dev_extract"
    if platform_url:
        env["OPS_PLATFORM_URL"] = platform_url
    if agents_url:
        # Its service events (extraction.corrected) are delivered there.
        env["OPS_AGENTS_URL"] = agents_url
    svc = ROOT / "services" / "documents-service"
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=svc, env=env, check=True, capture_output=True)
    argv = ["uv", "run", "python", "-m", "ops_documents"]
    with _serve("documents", argv, port, env, cwd=svc) as base, httpx.Client(base_url=base, timeout=30) as c:
        yield c


def put_in_files(files_url: str, name: str, body: bytes, *, mime: str = "application/pdf", headers: Any = None) -> str:
    """The console's upload to files-service (a ticket, the bytes, complete) as the dev user unless `headers` say
    otherwise; returns the file id, which a knowledge source then adds."""
    with httpx.Client(base_url=files_url, headers=headers or {}, timeout=60) as f:
        meta = {"name": name, "size": len(body), "mime": mime, "purpose": "knowledge_source"}
        ticket = data(f.post("/v1/files/uploads", json={**meta, "digest": hashlib.sha256(body).hexdigest()}))
        put = f.put(ticket["uploadUrl"], headers=ticket.get("headers") or {}, content=body)
        if put.status_code >= 300:
            raise SystemExit(f"FAIL put {name} in Files: {put.status_code} {put.text[:300]}")
        return str(data(f.post(f"/v1/files/uploads/{ticket['fileId']}/complete"))["file"]["id"])


def seed_fixture_knowledge(kb_url: str, files_url: str, platform_url: str | None = None) -> None:
    """The agents fixtures' knowledge bases and passages, put into kb-service through its API
    (seed_fixture_knowledge.py)."""
    script = str(Path(__file__).with_name("seed_fixture_knowledge.py"))
    argv = ["uv", "run", "python", script, "--kb", kb_url, "--files", files_url]
    argv += ["--platform", platform_url] if platform_url else []
    subprocess.run(argv, cwd=ROOT, env=_env(), check=True, capture_output=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def fake_openai(folder: Path) -> Generator[str]:
    """The fake OpenAI chat API (services/models-service/scripts/fake_openai) on a free port, reading
    `<folder>/script.json`. Yields its `/v1` base URL, the value OPS_MODELS_FAKE_OPENAI_URL takes."""
    port = free_port()
    env = _env()
    env["FAKE_OPENAI_PORT"] = str(port)
    argv = ["uv", "run", "--project", "..", "python", "-m", "fake_openai", str(folder)]
    cwd = ROOT / "services" / "models-service" / "scripts"
    with _serve("fake-openai", argv, port, env, cwd=cwd) as base:
        yield f"{base}/v1"


@contextmanager
def tools(settings: dict[str, str] | None = None) -> Generator[httpx.Client]:
    """The tools service (tool gateway) on the use-case database, deciding with an OPA of its own: the compose OPA's
    key and policy are rewritten by every other tools-service that starts."""
    migrate = ["uv", "run", "python", "scripts/scripted_server.py", "--port", "0", "--db", DB, "--migrate-only"]
    subprocess.run(migrate, cwd=AGENTS_DIR, env=_env(), check=True, capture_output=True)
    env = _env()
    pg = os.environ.get("OPS_PG_PORT", "5477")
    env["OPS_DATABASE_URL"] = f"postgresql+asyncpg://ops:ops@localhost:{pg}/{DB}"
    env["OPS_GATEWAY_PORT"] = str(TOOLS_PORT)
    # A tool module review opens in agents-service's Reviews (c-163); a stack that publishes modules runs agents too.
    env.setdefault("OPS_AGENTS_URL", f"http://127.0.0.1:{AGENTS_PORT}")
    # send_reply sends through the provider settings pick and fails with none (c-187): the dev fake writes each mail
    # to a folder of this run's.
    env.setdefault("OPS_MAIL_PROVIDER", "fake")
    env.setdefault("OPS_MAIL_FROM", "ops@northfield.example")
    env.setdefault("OPS_MAIL_FAKE_OUT_DIR", tempfile.mkdtemp(prefix="usecase-mail-out-"))
    # `settings` adds OPS_* values a use case needs, e.g. a CA file and dev name overrides for a local fake upstream.
    env.update(settings or {})
    # tools-service's own chain: the registry's tables, which its dev seed fills at start.
    tools_dir = ROOT / "services" / "tools-service"
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=tools_dir, env=env, check=True, capture_output=True)
    argv = ["uv", "run", "python", "-m", "ops_tools"]
    with opa_server() as opa_url:
        env["OPS_OPA_URL"] = opa_url
        with _serve("tools", argv, TOOLS_PORT, env) as base, httpx.Client(base_url=base, timeout=30) as c:
            yield c


@contextmanager
def platform(
    *, token_ttl_s: int | None = None, env: dict[str, str] | None = None
) -> Generator[tuple[httpx.Client, httpx.Client]]:
    """platform-service on the use-case database, in dev: its own migration chain, the dev seed (team_ops with Priya
    Shah admin, James Richardson builder, Maya Okafor approver; password `northfield-demo`), the public app and the
    internal one. Yields a client for each; the internal one answers only service tokens. `env` adds settings."""
    migrate = ["uv", "run", "python", "scripts/scripted_server.py", "--port", "0", "--db", DB, "--migrate-only"]
    subprocess.run(migrate, cwd=AGENTS_DIR, env=_env(), check=True, capture_output=True)
    settings = _env()
    pg = os.environ.get("OPS_PG_PORT", "5477")
    settings["OPS_DATABASE_URL"] = f"postgresql+asyncpg://ops:ops@localhost:{pg}/{DB}"
    settings["OPS_PLATFORM_PORT"] = str(PLATFORM_PORT)
    settings["OPS_PLATFORM_INTERNAL_PORT"] = str(PLATFORM_INTERNAL_PORT)
    # The seed's own roles: use cases check what a builder or viewer may not do, so nobody is made Admin everywhere.
    settings["OPS_SEED_EVERYONE_ADMIN"] = "false"
    if token_ttl_s is not None:
        settings["OPS_PLATFORM_TOKEN_TTL_SECONDS"] = str(token_ttl_s)
    settings |= env or {}
    platform_dir = ROOT / "services" / "platform-service"
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"], cwd=platform_dir, env=settings, check=True, capture_output=True
    )
    argv = ["uv", "run", "python", "-m", "ops_platform"]
    internal = f"http://127.0.0.1:{PLATFORM_INTERNAL_PORT}"
    with (
        _serve("platform", argv, PLATFORM_PORT, settings, health="/v1/health", cwd=platform_dir) as base,
        httpx.Client(base_url=base, timeout=30) as public,
        httpx.Client(base_url=internal, timeout=30) as inner,
    ):
        yield public, inner


@contextmanager
def fake_idp() -> Generator[str]:
    """The local OIDC and SAML identity provider (`packages/ops_signin`, `python -m ops_signin.fake_idp`) on the
    use-case IdP port, with its fake DNS on the same port over UDP. Yields its base URL; providers are named in the
    path (`/oidc/<name>`, `/saml/<name>`)."""
    port = str(IDP_PORT)
    argv = ["uv", "run", "python", "-m", "ops_signin.fake_idp", "--port", port, "--dns-port", port]
    with _serve("fake-idp", argv, IDP_PORT, _env(), health="/health", cwd=ROOT) as base:
        yield base


# The OIDC client secret name the sign-in use cases configure, and its value on their platform-service.
SIGNIN_SECRET = "uc-oidc"
# The SAML service provider key pair the sign-in stack's platform-service holds (c-197); a script gives the certificate
# to the fake identity provider so it can check signed requests and encrypt assertions.
SAML_SP_KEY, SAML_SP_CERT = self_signed("uc-sp")


@contextmanager
def signin_stack() -> Generator[tuple[httpx.Client, httpx.Client, Path]]:
    """platform-service ready for sign-in providers (c-188): its public and console URLs, one OIDC client secret named
    `uc-oidc`, reset mail written to a folder; and the fake identity provider beside it. Yields the platform client,
    a client for the identity provider and the mail folder."""
    mail = Path(tempfile.mkdtemp(prefix="uc-mail-"))
    env = {
        "OPS_PLATFORM_PUBLIC_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
        "OPS_CONSOLE_URL": f"http://localhost:{CONSOLE_PORT}",
        "OPS_SIGNIN_SECRETS": json.dumps({SIGNIN_SECRET: "uc-oidc-secret"}),
        # Domains are proven against the fake identity provider's DNS (c-195).
        "OPS_SIGNIN_DNS_SERVERS": json.dumps([f"127.0.0.1:{IDP_PORT}"]),
        "OPS_SAML_SP_KEY": SAML_SP_KEY,
        "OPS_SAML_SP_CERTIFICATE": SAML_SP_CERT,
        "OPS_MAIL_PROVIDER": "fake",
        "OPS_MAIL_FROM": "ops@northfieldbank.com",
        "OPS_MAIL_FAKE_OUT_DIR": str(mail),
    }
    with fake_idp() as idp_base, platform(env=env) as (api, _), httpx.Client(base_url=idp_base, timeout=30) as idp:
        yield api, idp, mail


def set_provider(
    api: httpx.Client, idp: httpx.Client, provider_id: str, body: dict[str, Any], headers: dict[str, str]
) -> httpx.Response:
    """Saves a sign-in provider and proves each of its new domains as a bank would (c-195): publishes the claim's TXT
    record at the fake DNS and asks platform-service to verify it, checking each step. Returns the save's response."""
    r = api.put(f"/v1/settings/sign-in/providers/{provider_id}", json=body, headers=headers)
    for c in data(r).get("verification", []) if r.status_code == 200 else []:
        if c["verifiedAt"] is None:
            idp.put(f"/dns/txt/{c['domain']}", json={"values": [c["record"]["value"]]}).raise_for_status()
            v = api.post(f"/v1/settings/sign-in/domains/{c['domain']}/verify", headers=headers)
            check(f"{c['domain']} is verified by its TXT record (200)", v.status_code == 200, v.text[:200])
    return r


def signed_in(api: httpx.Client, email: str, password: str = "northfield-demo") -> dict[str, Any]:
    """Signs a seeded person in and returns the session (token, refresh token, principal); checks the status."""
    r = api.post("/v1/auth/sign-in", json={"email": email, "password": password})
    check(f"{email} signs in (200)", r.status_code == 200, r.text[:200])
    return data(r) if r.status_code == 200 else {}


def bearer(session: dict[str, Any], team: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {session.get('token', '')}"}
    return headers | ({"X-Team-Id": team} if team else {})


# The password every person a use case invites sets when accepting (c-218).
INVITED_PASSWORD = "an invited person's password"


def invited(api: httpx.Client, admin: dict[str, str], email: str, role: str, *, name: str = "") -> dict[str, Any]:
    """A person made the way a bank makes one (c-218): `admin` (headers acting in the team) invites `email` with
    `role`, the person accepts the link with a name and a password, and the session that accept opens is returned.
    Each step is checked."""
    r = api.post("/v1/settings/members/invite", json={"emails": [email], "role": role}, headers=admin)
    invites = data(r).get("invites", []) if r.status_code == 200 else []
    check(f"{email} is invited as {role}", bool(invites and invites[0].get("token")), r.text[:200])
    token = invites[0]["token"] if invites else "inv_missing0"
    r = api.post(
        f"/v1/invites/{token}/accept",
        json={"name": name or email.split("@", maxsplit=1)[0].replace(".", " ").title(), "password": INVITED_PASSWORD},
    )
    check(f"{email} accepts the invitation with a password", r.status_code == 200, r.text[:200])
    return data(r) if r.status_code == 200 else {}


@contextmanager
def people_stack(*, agents_env: dict[str, str] | None = None) -> Generator[tuple[httpx.Client, httpx.Client]]:
    """platform-service with the dev seed's own roles, and agents-service verifying its tokens, as the console runs
    them. Yields the platform client and the agents client; every agents call carries a person's token."""
    auth = {
        "OPS_AUTH_MODE": "platform",
        "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
        "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
    }
    with platform() as (api, _), agents(env=auth | (agents_env or {})) as agents_client:
        yield api, agents_client


def security_admin_on_ops(api: httpx.Client) -> dict[str, str]:
    """Sam Adeyemi, the dev seed's Security admin, made an admin of team_ops too (Priya invites him, he accepts as
    himself), so a sign-in provider he sets may send new people there. Returns his headers acting in team_security."""
    sam_email, priya_email = "s.adeyemi@northfieldbank.com", "p.shah@northfieldbank.com"
    priya = signed_in(api, priya_email)
    sam = signed_in(api, sam_email)
    r = api.post(
        "/v1/settings/members/invite", json={"emails": [sam_email], "role": "admin"}, headers=bearer(priya, "team_ops")
    )
    invites = data(r)["invites"] if r.status_code == 200 else []
    check("Priya invites Sam to team_ops as admin", bool(invites and invites[0].get("token")), r.text[:200])
    token = invites[0]["token"] if invites else "inv_missing0"
    r = api.post(f"/v1/invites/{token}/accept", json={"name": "Sam Adeyemi"}, headers=bearer(sam))
    check("Sam accepts the invitation as himself", r.status_code == 200, r.text[:200])
    sam = signed_in(api, sam_email)
    return bearer(sam, "team_security")


def sso_round_trip(
    api: httpx.Client,
    idp: httpx.Client,
    email: str,
    *,
    user: str | None = None,
    stale: bool = False,
    groups: tuple[str, ...] = (),
) -> dict[str, Any]:
    """A browser's SSO sign-in, without the browser: start for `email`, log `user` (default `email`) in at the identity
    provider, hand its answer to platform-service, and complete with the flow key when it sent back a code. Returns
    `location` (the console URL platform-service redirected to), `query`, `flowKey` and `completed` (the response)."""
    start = api.post("/v1/auth/sso/start", json={"email": email})
    if start.status_code != 200:
        return {"start": start, "location": "", "query": {}, "flowKey": "", "completed": None}
    started = data(start)
    url = httpx.URL(started["redirectUrl"])
    params = dict(url.params) | {"user": user or email} | ({"stale": "1"} if stale else {})
    if groups:
        # The groups the fake identity provider says the person is in.
        params["groups"] = ",".join(groups)
    at_idp = idp.get(url.path, params=params)
    if at_idp.status_code == 302:
        back = httpx.URL(at_idp.headers["location"])
        answered = api.get(back.path, params=dict(back.params))
    else:
        form = {k: html.unescape(v) for k, v in re.findall(r'name="(\w+)" value="([^"]*)"', at_idp.text)}
        answered = api.post(
            "/v1/auth/saml/acs", content=str(httpx.QueryParams(form)),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )  # fmt: skip
    location = answered.headers.get("location", "")
    query = dict(httpx.URL(location).params) if location else {}
    completed = None
    if "code" in query:
        completed = api.post("/v1/auth/sso/complete", json={"code": query["code"], "flowKey": started["flowKey"]})
    return {"start": start, "location": location, "query": query, "flowKey": started["flowKey"], "completed": completed}


def approve_tool_review(gw: httpx.Client, module_id: str, headers: dict[str, str]) -> dict[str, Any]:
    """Approves the module's open review in agents-service's Reviews as `headers` (a Security approver), as Human Tasks
    would (c-163); Reviews applies it in tools-service. Returns the module's detail afterwards."""
    module = data(gw.get(f"/v1/tool-modules/{module_id}", headers=headers))
    waiting = next(v for v in module["versions"] if v["status"] == "in_review")
    with httpx.Client(base_url=f"http://127.0.0.1:{AGENTS_PORT}", timeout=30) as reviews:
        data(
            reviews.post(
                f"/v1/publish-requests/{waiting['reviewId']}/decision", json={"decision": "approved"}, headers=headers
            )
        )
    return data(gw.get(f"/v1/tool-modules/{module_id}", headers=headers))


def data(res: httpx.Response) -> Any:
    body = res.json()
    return body.get("data") if isinstance(body, dict) else None


# The four thread calls (POST /v1/threads, POST .../runs/stream, GET .../state, GET /v1/threads).
SEED = AGENTS_DIR / "tests" / "fixtures" / "seed"
EMAILS: list[dict[str, Any]] = json.loads((SEED / "dispute_emails.json").read_text())


def new_thread(api: httpx.Client, graph: str) -> str:
    res = api.post("/v1/threads", json={"graph": graph, "metadata": {"usecase": True}}, headers=TEAM)
    check(f"{graph} thread created (201)", res.status_code == 201, res.text[:200])
    return str(data(res)["threadId"])


def run(api: httpx.Client, tid: str, body: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    res = api.post(f"/v1/threads/{tid}/runs/stream", json=body, headers=TEAM)
    return res.status_code, sse(res.text) if res.status_code == 200 else []


def state(api: httpx.Client, tid: str) -> dict[str, Any]:
    return data(api.get(f"/v1/threads/{tid}/state", headers=TEAM))


def nodes(events: list[dict[str, Any]]) -> list[str]:
    return [e["node"] for e in events if e.get("event") == "node_start"]


# ── The banker demo's stack (c-058), as withUiStack's `demo` option builds it, under dev auth ──

DEMO_JAMES, DEMO_NADIA, DEMO_MAYA = (
    "j.richardson@northfieldbank.com",
    "n.petrov@northfieldbank.com",
    "m.okafor@northfieldbank.com",
)


@contextmanager
def core_bank() -> Generator[dict[str, Any]]:
    """The core-banking fake (services/tools-service/scripts/fake_bank: customers, accounts, holds, notes) on https
    as api.bank.test, through fake_bank_serve.py: what tools-service needs to reach it, and the range to list."""
    env = _env()
    env["OPS_FAKE_BANK_APP"] = "core"
    env["PYTHONPATH"] = os.pathsep.join([str(Path(__file__).parent), env.get("PYTHONPATH", "")])
    argv = ["uv", "run", "--quiet", "python", str(Path(__file__).with_name("fake_bank_serve.py"))]
    proc = subprocess.Popen(argv, cwd=AGENTS_DIR, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline()
        if not line:
            raise SystemExit("FAIL the core bank did not start")
        yield json.loads(line)
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def publish_bank_module(gw: httpx.Client, host: str) -> str:
    """The core bank's document imported as a published module, as reimport_bank_module.py leaves it, decided under
    dev auth: every operation, reads from GET, place_hold approved by one person of team_ops with a step-up."""
    security = {"X-Dev-User": "Nadia Petrov"}
    source = {"kind": "openapi", "specUrl": f"https://{host}/openapi.json"}
    found = data(gw.post("/v1/tool-modules/discover", json=source))
    ops = [
        {**o, "access": "read" if (o.get("method") or "GET").upper() == "GET" else "write"} for o in found["operations"]
    ]
    made = data(
        gw.post(
            "/v1/tool-modules",
            json={
                "name": "northfield-core-banking",
                "displayName": "Northfield Core Banking",
                "system": found["system"],
                "type": "openapi",
                "endpoint": found["endpoint"],
                "operations": ops,
                "source": source,
            },
        )
    )
    hold = next(o for o in made["operations"] if o["name"] == "place_hold")
    policy = {"approvers": 1, "approverTeam": "team_ops", "stepUp": True}
    data(gw.patch(f"/v1/tool-modules/{made['id']}/operations/{hold['id']}", json=policy))
    # The levy demo's webhook runs at once, as reimport_bank_module.py sets it.
    if hook := next((o for o in made["operations"] if o["name"] == "notify_webhook"), None):
        data(gw.patch(f"/v1/tool-modules/{made['id']}/operations/{hook['id']}", json={"requiresApproval": False}))
    data(gw.post(f"/v1/tool-modules/{made['id']}/reviews", json={"note": "demo stack"}))
    approve_tool_review(gw, made["id"], security)
    return str(made["id"])


def seed_demo_knowledge(kb_url: str, files_url: str, *, agents_url: str | None = None, fees: str = "v1") -> str:
    """services/kb-service/scripts/seed_demo_knowledge.py under dev auth: the two bases (reused on a second run), the
    K12 scores it prints, and with `agents_url` the demo agents wired to their bases and reads."""
    argv = ["uv", "run", "python", "scripts/seed_demo_knowledge.py", "--kb", kb_url, "--files", files_url, "--dev"]
    argv += ["--fees", fees]
    argv += ["--agents", agents_url] if agents_url else []
    done = subprocess.run(
        argv, cwd=ROOT / "services" / "kb-service", env=_env(), capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise SystemExit(f"FAIL seed_demo_knowledge: {done.stdout[-800:]} {done.stderr[-800:]}")
    return done.stdout


class Demo:
    def __init__(
        self,
        api: httpx.Client,
        gw: httpx.Client,
        kb_url: str,
        files_url: str,
        agents_url: str,
        *,
        stop_provider: Callable[[], None],
    ) -> None:
        self.api, self.gw, self.kb_url, self.files_url, self.agents_url = api, gw, kb_url, files_url, agents_url
        # Stops the fake OpenAI behind models-service, so every model call fails as in a provider outage.
        self.stop_provider = stop_provider


@contextmanager
def demo() -> Generator[Demo]:
    """The banker demo on the run's own stack, as withUiStack's `demo` option builds it (dev auth here): turns run
    through models-service on the fake OpenAI with the committed demo rules, agents call the core bank through
    tools-service, and kb-service holds the demo knowledge with ag_advisor and ag_policy wired to it."""
    migrate = ["uv", "run", "python", "scripts/scripted_server.py", "--port", "0", "--db", DB, "--migrate-only"]
    subprocess.run(migrate, cwd=AGENTS_DIR, env=_env(), check=True, capture_output=True)
    with ExitStack() as stack:
        provider = ExitStack()
        stack.callback(provider.close)
        fake = provider.enter_context(fake_openai(DEMO_RULES))
        models_url = stack.enter_context(models({"OPS_MODELS_FAKE_OPENAI_URL": fake}))
        bank = stack.enter_context(core_bank())
        agents_url = f"http://127.0.0.1:{AGENTS_PORT}"
        gw = stack.enter_context(tools({**bank["settings"], "OPS_AGENTS_URL": agents_url}))
        files = stack.enter_context(tempfile.TemporaryDirectory(prefix="usecase-kb-"))
        kb_client = stack.enter_context(kb(Path(files)))
        kb_url = str(kb_client.base_url).rstrip("/")
        seed_fixture_knowledge(kb_url, kb_client.files_url)
        api = stack.enter_context(
            agents(
                gateway_url=f"http://127.0.0.1:{TOOLS_PORT}",
                models_url=models_url,
                models_key="mk_dev_agents",
                kb_url=kb_url,
                env={"OPS_AGENTS_SEED_FILE": "seed/chat_agents.json"},
            )
        )
        gw.post("/v1/egress/hosts", json={"value": bank["host"], "note": "demo stack"})
        gw.post("/v1/egress/ranges", json={"value": bank["range"], "note": "demo stack"})
        gw.post("/v1/secrets", json={"name": "BANK_API_KEY", "value": "dev-bank-key"})
        publish_bank_module(gw, bank["host"])
        seed_demo_knowledge(kb_url, kb_client.files_url, agents_url=agents_url)
        yield Demo(api, gw, kb_url, kb_client.files_url, agents_url, stop_provider=provider.close)


def chat(
    api: httpx.Client, agent_id: str, question: str, *, thread: str | None = None
) -> tuple[str, list[dict[str, Any]]]:
    """One turn with `agent_id` (a new conversation unless `thread` is given): the thread id and the stream's events."""
    team = {"X-Team-Id": "team_ops", "X-Dev-User": DEMO_MAYA}
    tid = thread or data(api.post("/chat/threads", json={"agentId": agent_id, "kbIds": []}, headers=team))["id"]
    res = api.post(
        f"/chat/threads/{tid}/messages",
        json={"content": question},
        headers={**team, "Accept": "text/event-stream"},
        timeout=120,
    )
    if res.status_code != 200:
        raise SystemExit(f"FAIL chat {agent_id}: {res.status_code} {res.text[:300]}")
    return tid, sse(res.text)


def turn_text(events: list[dict[str, Any]]) -> str:
    return "".join(str(e.get("delta", "")) for e in events if e.get("type") == "text")


def turn_parts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e["part"] for e in events if e.get("type") == "part"]


def turn_citations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for e in events if e.get("type") == "citations" for c in e.get("citations") or []]
