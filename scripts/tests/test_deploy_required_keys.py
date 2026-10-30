"""Every key a service refuses to start without (`require_keys(settings, ...)` in its __main__) reaches that service's
process on Fly (deploy/fly/processes.toml). The account key store made models-service require secrets_key; Fly never
passed it, and staging's models process restarted in a loop until a deploy found it."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def required() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for main in ROOT.glob("services/*/src/*/**/__main__.py"):
        service = main.relative_to(ROOT).parts[1].removesuffix("-service")
        for call in re.findall(r"require_keys\(settings,([^)]*)\)", main.read_text()):
            out.setdefault(service, set()).update(f"OPS_{k.upper()}" for k in re.findall(r'"([a-z_]+)"', call))
    return out


def process_env(path: Path) -> dict[str, set[str]]:
    processes = tomllib.loads(path.read_text()).get("process", {})
    return {name: set((spec.get("env") or {}).keys()) for name, spec in processes.items()}


def missing(path: Path) -> list[str]:
    env = process_env(path)
    return [
        f"{svc}: {key}" for svc, keys in required().items() if svc in env for key in sorted(keys) if key not in env[svc]
    ]


def test_every_required_key_reaches_its_fly_process() -> None:
    assert required(), "no require_keys calls found; the scan is looking in the wrong place"
    assert missing(ROOT / "deploy/fly/processes.toml") == []
