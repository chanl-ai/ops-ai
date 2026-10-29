"""A private OPA for one test session or use-case run, never the compose OPA on :8181.

Every tools-service that starts writes its review key and gateway policy into the OPA it is given. With one shared
OPA, a dev stack, another session's use case, or a working tree with a different policy rewrote them under a running
suite, and approval tokens the suite had signed were refused ("approval token is not signed by the review service").
Each caller here gets its own container on a free port, serving the same policy directory compose mounts (the
policy and its `data.json`); the gateway under test then writes its own key and policy into it.
Used by scripts and tests only, never by a running service.
"""

from __future__ import annotations

import atexit
import subprocess
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import httpx

from ops_service_kit.settings import Settings

# The directory compose mounts at /policy: gateway.rego and data.json (the registered identities).
POLICY_DIR = Path(__file__).resolve().parents[4] / "services" / "tools-service" / "policy"
IMAGE = "openpolicyagent/opa:1.21.1"


def start() -> tuple[str, str]:
    """Starts a container and returns (its id, its base URL) once OPA answers its health check. In the devcontainer
    (OPS_INFRA=external) there is no docker to start one, so it returns the compose project's own OPA side container
    with no id: that project is one person's, not shared across sessions."""
    settings = Settings()
    if settings.infra == "external":
        return "", settings.opa_url
    # OPA 1.x listens on localhost inside the container by default, which a published port cannot reach.
    run = [
        *("docker", "run", "-d", "--rm", "-p", "127.0.0.1::8181", "-v", f"{POLICY_DIR}:/policy:ro", IMAGE),
        *("run", "--server", "--addr", "0.0.0.0:8181", "--log-level", "error", "/policy"),
    ]
    cid = subprocess.run(run, capture_output=True, text=True, check=True).stdout.strip()
    try:
        bound = subprocess.run(["docker", "port", cid, "8181/tcp"], capture_output=True, text=True, check=True).stdout
        url = f"http://127.0.0.1:{bound.splitlines()[0].rsplit(':', 1)[1]}"
        for _ in range(100):
            try:
                if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                    return cid, url
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError(f"OPA container {cid[:12]} did not become healthy")
    except BaseException:
        stop(cid)
        raise


def stop(cid: str) -> None:
    if not cid:
        return
    subprocess.run(["docker", "rm", "-f", cid], capture_output=True, check=False)


_session: str | None = None


def session_url() -> str:
    """One OPA for this test process, started on first use and removed when the process exits."""
    global _session
    if _session is None:
        cid, _session = start()
        atexit.register(stop, cid)
    return _session


@contextmanager
def opa_server() -> Generator[str]:
    cid, url = start()
    try:
        yield url
    finally:
        stop(cid)
