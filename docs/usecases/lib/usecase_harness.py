"""What every Python use case script shares: checks that print PASS or FAIL, and services started on the scripted
model on the use-case ports.

The runner (packages/usecase-runner) puts this folder on PYTHONPATH and reads the output: one `PASS <name>` or
`FAIL <name>: <detail>` line per check. A script that prints no check line fails, so a script that silently skips
its assertions cannot pass. Services are started fresh per script and stopped when it ends; a port already in use is
refused rather than reused, so a script never reads another session's state.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

from ops_service_kit.opa_server import opa_server

ROOT = Path(__file__).resolve().parents[3]
AGENTS_DIR = ROOT / "services" / "agents-service"
AGENTS_PORT = int(os.environ.get("OPS_USECASE_AGENTS_PORT", "8790"))
TOOLS_PORT = int(os.environ.get("OPS_USECASE_TOOLS_PORT", "8791"))
MODELS_PORT = int(os.environ.get("OPS_USECASE_MODELS_PORT", "8792"))
CONSOLE_PORT = int(os.environ.get("OPS_USECASE_CONSOLE_PORT", "3018"))
PLATFORM_PORT = int(os.environ.get("OPS_USECASE_PLATFORM_PORT", "8810"))
PLATFORM_INTERNAL_PORT = int(os.environ.get("OPS_USECASE_PLATFORM_INTERNAL_PORT", "8811"))
DB = os.environ.get("OPS_USECASE_DB", "ops_usecase")
LOG_DIR = Path(os.environ.get("OPS_LOG_DIR", ROOT / ".logs")) / "usecase"
TEAM = {"X-Team-Id": "team_all"}

_failed = 0
_checked = 0


def check(name: str, ok: bool, detail: Any = "") -> bool:
    global _failed, _checked
    _checked += 1
    if ok:
        print(f"PASS {name}", flush=True)
    else:
        _failed += 1
        print(f"FAIL {name}: {detail}", flush=True)
    return ok


def service_headers(audience: str, *, tenant: str = "local", service: str = "agents") -> dict[str, str]:
    """A calling service's Ed25519 token for `audience`'s internal routes (the dev key, dev only), naming the tenant
    it acts for. The callee takes the caller from it, never from the body."""
    from ops_identity import dev_service_signer, mint_service_token  # noqa: PLC0415

    token = mint_service_token(dev_service_signer(), service=service, audience=audience, tenant_id=tenant, ttl_s=600)
    return {"Authorization": f"Bearer {token}"}


def finish() -> None:
    if _checked == 0:
        print("FAIL no checks ran", flush=True)
        sys.exit(1)
    sys.exit(1 if _failed else 0)


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
    env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")}
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
) -> Generator[httpx.Client]:
    """The agents service on the scripted model, with its own migrated database. With `models_url` it asks that
    models-service which model aliases an agent may name; with `models_key` too, its turns run there, on the scripted
    provider, spending from that key. `model_alias` is the runtime's alias for agents that name none."""
    argv = ["uv", "run", "python", "scripts/scripted_server.py", "--port", str(AGENTS_PORT), "--db", DB]
    for origin in cors or []:
        argv += ["--cors", origin]
    if gateway_url:
        argv += ["--gateway-url", gateway_url]
    env = _env()
    if models_url:
        env["OPS_MODELS_URL"] = models_url
    if models_key:
        env["OPS_MODELS_KEY"] = models_key
    if model_alias:
        env["OPS_MODEL_ALIAS"] = model_alias
    with _serve("agents", argv, AGENTS_PORT, env) as base, httpx.Client(base_url=base, timeout=60) as c:
        yield c


@contextmanager
def models() -> Generator[str]:
    """models-service on the use-case database, seeded with its scripted aliases (bank-standard, bank-reasoning,
    bank-embed). Yields its base URL."""
    migrate = ["uv", "run", "python", "scripts/scripted_server.py", "--port", "0", "--db", DB, "--migrate-only"]
    subprocess.run(migrate, cwd=AGENTS_DIR, env=_env(), check=True, capture_output=True)
    env = _env()
    pg = os.environ.get("OPS_PG_PORT", "5477")
    env["OPS_DATABASE_URL"] = f"postgresql+asyncpg://ops:ops@localhost:{pg}/{DB}"
    env["OPS_MODELS_PORT"] = str(MODELS_PORT)
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=ROOT / "services" / "models-service",
        env=env,
        check=True,
        capture_output=True,
    )
    with _serve("models", ["uv", "run", "python", "-m", "ops_models"], MODELS_PORT, env) as base:
        yield base


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
def platform(*, token_ttl_s: int | None = None) -> Generator[tuple[httpx.Client, httpx.Client]]:
    """platform-service on the use-case database, in dev: its own migration chain, the dev seed (team_ops with Priya
    Shah admin, James Richardson builder, Maya Okafor approver; password `northfield-demo`), the public app and the
    internal one. Yields a client for each; the internal one answers only service tokens."""
    migrate = ["uv", "run", "python", "scripts/scripted_server.py", "--port", "0", "--db", DB, "--migrate-only"]
    subprocess.run(migrate, cwd=AGENTS_DIR, env=_env(), check=True, capture_output=True)
    env = _env()
    pg = os.environ.get("OPS_PG_PORT", "5477")
    env["OPS_DATABASE_URL"] = f"postgresql+asyncpg://ops:ops@localhost:{pg}/{DB}"
    env["OPS_PLATFORM_PORT"] = str(PLATFORM_PORT)
    env["OPS_PLATFORM_INTERNAL_PORT"] = str(PLATFORM_INTERNAL_PORT)
    if token_ttl_s is not None:
        env["OPS_PLATFORM_TOKEN_TTL_SECONDS"] = str(token_ttl_s)
    platform_dir = ROOT / "services" / "platform-service"
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"], cwd=platform_dir, env=env, check=True, capture_output=True
    )
    argv = ["uv", "run", "python", "-m", "ops_platform"]
    internal = f"http://127.0.0.1:{PLATFORM_INTERNAL_PORT}"
    with (
        _serve("platform", argv, PLATFORM_PORT, env, health="/v1/health", cwd=platform_dir) as base,
        httpx.Client(base_url=base, timeout=30) as public,
        httpx.Client(base_url=internal, timeout=30) as inner,
    ):
        yield public, inner


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
