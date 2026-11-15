"""One boot test per service process, by failure mode: a process that starts without the address of a service it
cannot run without, and finds out at its first call. Each must exit at start naming the setting, before it opens a
database or a port."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SIGNED_IN = {"OPS_AUTH_MODE": "platform", "OPS_PLATFORM_URL": "http://platform.invalid:8710"}
DEV = {"OPS_AUTH_MODE": "dev"}
# Each process, the environment it starts in, and the addresses it must name when none is set.
PROCESSES: dict[str, tuple[dict[str, str], list[str]]] = {
    "ops_agents.api": (SIGNED_IN, ["OPS_PLATFORM_INTERNAL_URL"]),
    "ops_agents.api.worker": (SIGNED_IN, ["OPS_PLATFORM_INTERNAL_URL"]),
    "ops_documents": (SIGNED_IN, ["OPS_AGENTS_URL", "OPS_FILES_URL", "OPS_PLATFORM_INTERNAL_URL"]),
    "ops_files": (SIGNED_IN, ["OPS_PLATFORM_INTERNAL_URL"]),
    "ops_kb": (DEV, ["OPS_AGENTS_URL"]),
    "ops_models": (SIGNED_IN, ["OPS_PLATFORM_INTERNAL_URL"]),
    "ops_platform": (DEV, ["OPS_AGENTS_URL"]),
    "ops_runner": (SIGNED_IN, ["OPS_PLATFORM_INTERNAL_URL"]),
    "ops_tools": (DEV, ["OPS_AGENTS_URL", "OPS_DOCUMENTS_URL", "OPS_FILES_URL"]),
}


@pytest.mark.parametrize("module", sorted(PROCESSES))
def test_a_process_missing_a_required_address_exits_naming_it(module: str) -> None:
    given, named = PROCESSES[module]
    # Nothing of the caller's stack: no address, and a database nothing listens on, so a process that got past the
    # check would fail on something else and not name the setting.
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPS_")}
    env |= {"OPS_DATABASE_URL": "postgresql+asyncpg://nobody:nobody@127.0.0.1:1/none", **given}
    done = subprocess.run(
        [sys.executable, "-m", module], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120, check=False
    )
    assert done.returncode != 0, module
    last = done.stderr.strip().splitlines()[-1]
    assert all(name in last for name in named) and "must be set" in last, done.stderr[-600:]


def test_every_service_process_has_a_boot_test() -> None:
    mains = {
        ".".join(p.parent.relative_to(next(a for a in p.parents if a.name == "src")).parts)
        for p in ROOT.glob("services/*-service/src/**/__main__.py")
    }
    assert mains | {"ops_agents.api.worker"} == set(PROCESSES)
