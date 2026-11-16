"""A use case run against a deployed host (OPS_USECASE_BASE_URL), by failure mode: any origin was accepted, a name that
looks like production was reachable, seeding wrote through the API, a ui script or a script that deletes was run, and
a use case nobody marked safe was run. Each refusal is driven through the harness a script imports."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "docs/usecases/lib"
STAGING = "https://acme-web.fly.dev"

# The script a use case runs: named for its use case and layer, as the runner names them. `act` picks what it calls.
SCRIPT = """
import sys
sys.path.insert(0, {lib!r})
import usecase_harness as h
h.USECASES = h.Path({case_dir!r})
h.HOSTS_FILE = h.Path({hosts!r})
import subprocess
calls = []
subprocess.run = lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("ran " + repr(a)))
h.httpx.get = lambda *a, **k: type("R", (), {{"status_code": 200}})()
act = sys.argv[1]
if act == "serve":
    with h._serve("agents", ["false"], 1, {{}}) as base:
        print("base", base)
elif act == "seed":
    h.seed_demo_knowledge("http://k", "http://f")
    print("SEED-RAN")
"""


def _run(
    tmp: Path, base: str, act: str, *, uc: str = "uc-901", layer: str = "api", safe: bool = True
) -> tuple[int, str]:
    case = tmp / "usecases"
    case.mkdir(exist_ok=True)
    mark = "safe" if safe else ""
    (case / "README.md").write_text(
        "| Id | Service | Title | Layers | Status | Deployed |\n|---|---|---|---|---|---|\n"
        f"| {uc} | agents-service | t | api, ui | passing | {mark} |\n"
        "| uc-902 | agents-service | t | api | passing | |\n"
    )
    hosts = ROOT / "deploy/fly/usecase-hosts.txt"
    script = tmp / f"test-{uc}-{layer}.py"
    script.write_text(textwrap.dedent(SCRIPT).format(lib=str(LIB), case_dir=str(case), hosts=str(hosts)))
    done = subprocess.run(
        [sys.executable, str(script), act],
        capture_output=True,
        text=True,
        env={"OPS_USECASE_BASE_URL": base, "PATH": ""},
        check=False,
    )
    return done.returncode, done.stdout + done.stderr


def test_a_staging_host_on_the_list_is_called(tmp_path: Path) -> None:
    code, out = _run(tmp_path, STAGING, "serve")
    assert code == 0 and f"base {STAGING}" in out, out


@pytest.mark.parametrize(
    "host",
    [
        "https://example.com",
        "https://acme-web.fly.dev.evil.example",
        "https://evil.example/acme-web.fly.dev",
        "http://acme-web.fly.dev",
        "https://acme-web.fly.dev/api",
        "https://user@acme-web.fly.dev",
        "https://prod-web.fly.dev",
        "https://acme-production-web.fly.dev",
    ],
)
def test_any_other_host_and_any_production_name_is_refused(tmp_path: Path, host: str) -> None:
    code, out = _run(tmp_path, host, "serve")
    assert code != 0 and "deployed-host guard" in out and "base " not in out, out


def test_seeding_is_refused_on_a_deployed_host(tmp_path: Path) -> None:
    code, out = _run(tmp_path, STAGING, "seed")
    assert code != 0 and "deployed-host guard" in out and "SEED-RAN" not in out, out


def test_only_the_api_layer_runs_on_a_deployed_host(tmp_path: Path) -> None:
    code, out = _run(tmp_path, STAGING, "serve", layer="sdk")
    assert code != 0 and "deployed-host guard" in out and "base " not in out, out


def test_a_use_case_not_marked_safe_is_refused(tmp_path: Path) -> None:
    code, out = _run(tmp_path, STAGING, "serve", safe=False)
    assert code != 0 and "deployed-host guard" in out and "base " not in out, out
    code, out = _run(tmp_path, STAGING, "serve", uc="uc-902", safe=False)
    assert code != 0 and "deployed-host guard" in out, out
