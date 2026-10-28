"""Writes an overlay's secret env files (git-ignored), one per service plus the migrate Job's, which the overlay's
secretGenerator turns into Secrets. Each holds only that service's database login, its own signing key, the public
keys and the keys it uses (deploy/images/service_keys.py); the migrate Job alone holds the migrator's login and the
first admin's values. Values are never printed. Runbook: docs/deploy/kubernetes.md.

    uv run python deploy/k8s/write_secrets.py --overlay deploy/k8s/overlays/<env> --db-host postgres --db-name ops \\
        --logins <ROLE=password lines> --admin <OPS_BOOTSTRAP_* lines> [--models <OPS_MODELS_KEY_* lines>]

Keys are generated on the first run and kept in <overlay>/keys.env (mode 600, git-ignored); later runs reuse them.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
SERVICES = ("platform", "agents", "tools", "models", "kb", "files", "documents", "runner")
# Services with no tables, so no database login.
NO_DATABASE = {"runner"}
MODELS_KEYS = {"agents": "OPS_MODELS_KEY_AGENTS", "documents": "OPS_MODELS_KEY_DOCUMENTS"}


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _pairs(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _write(path: Path, values: dict[str, str]) -> None:
    path.touch(mode=0o600)
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--overlay", type=Path, required=True)
    ap.add_argument("--db-host", required=True, help="host:port the pods reach the database on, e.g. postgres:5432")
    ap.add_argument("--db-name", required=True)
    ap.add_argument("--logins", type=Path, required=True, help="ops_migrator= and ops_<service>_runtime= lines")
    ap.add_argument("--admin", type=Path, required=True, help="OPS_BOOTSTRAP_* lines for the first admin")
    ap.add_argument("--models", type=Path, help="OPS_MODELS_KEY_AGENTS and OPS_MODELS_KEY_DOCUMENTS lines")
    a = ap.parse_args()
    uses = cast(dict[str, tuple[str, ...]], _load(HERE.parent / "images" / "service_keys.py", "service_keys").USES)
    kept = a.overlay / "keys.env"
    keys = _pairs(kept)
    # A service added since the keys were made has no key in them, and the public keys must name every service, so
    # the whole set is made again; every Secret below is rewritten from it.
    if not all(f"OPS_SVC_KEY_{svc.upper()}" in keys for svc in SERVICES):
        keys = cast(dict[str, str], _load(HERE.parent / "fly" / "generate_keys.py", "generate_keys").generate())
        _write(kept, keys)
    logins, admin, models = _pairs(a.logins), _pairs(a.admin), _pairs(a.models)

    def dsn(role: str) -> str:
        # Percent-encoded: a password holding @, :, / or # would otherwise end the login early.
        return f"postgresql+asyncpg://{role}:{quote(logins[role], safe='')}@{a.db_host}/{a.db_name}"

    for svc in SERVICES:
        values = {
            **({} if svc in NO_DATABASE else {"OPS_DATABASE_URL": dsn(f"ops_{svc}_runtime")}),
            "OPS_SERVICE_SIGNING_KEY": keys[f"OPS_SVC_KEY_{svc.upper()}"],
            "OPS_SERVICE_PUBLIC_KEYS": keys["OPS_SERVICE_PUBLIC_KEYS"],
            **{k: keys[k] for k in uses[svc]},
        }
        if svc in MODELS_KEYS and models.get(MODELS_KEYS[svc]):
            values["OPS_MODELS_KEY"] = models[MODELS_KEYS[svc]]
        _write(a.overlay / f"{svc}.env", values)
    migrate = {
        "OPS_DATABASE_URL": dsn("ops_migrator"),
        **{k: v for k, v in admin.items() if k.startswith("OPS_BOOTSTRAP_")},
    }
    _write(a.overlay / "migrate.env", migrate)
    print(f"secrets: {len(SERVICES) + 1} env files in {a.overlay} (values not shown)")


if __name__ == "__main__":
    main()
