"""Single-tenant and multi-tenant installs differ only by `tenancy_mode` (c-418), by failure mode: a single-tenant
install that creates a second tenant; a multi-tenant install that refuses one; the install's tenant taken from anything
but the settings; and a code path that reads the mode anywhere but where tenants are created, which would make one mode
behave differently from the other."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from ops_platform.seed import seed
from ops_platform.tenants import SINGLE_TENANT, install_tenant
from ops_service_kit.errors import Conflict
from ops_service_kit.settings import Settings

PEOPLE = Path(__file__).parents[1] / "seed" / "people.json"
ROOT = Path(__file__).resolve().parents[3]


def _moved(tmp_path: Path, tenant: str) -> Path:
    """The seed file as another tenant's, its team and person ids renamed so nothing else conflicts."""
    data = json.loads(PEOPLE.read_text())
    data["tenant"]["id"] = tenant
    for t in data["teams"]:
        t["id"] = f"{t['id']}_{tenant}"
    for p in data["people"]:
        p["id"], p["email"] = f"{p['id']}_{tenant}", f"{tenant}.{p['email']}"
        p["teams"] = {f"{k}_{tenant}": v for k, v in p["teams"].items()}
    path = tmp_path / "people.json"
    path.write_text(json.dumps(data))
    return path


async def test_a_single_tenant_install_seeds_its_own_tenant_and_refuses_another(
    database_url: str, tmp_path: Path
) -> None:
    only = install_tenant(Settings(tenancy_mode="single"))
    assert only == "local"
    await seed(database_url, PEOPLE, only_tenant=only)
    with pytest.raises(Conflict) as refused:
        await seed(database_url, _moved(tmp_path, "ten_second"), only_tenant=only)
    assert (refused.value.status, refused.value.code) == (409, SINGLE_TENANT)


async def test_a_multi_tenant_install_seeds_a_second_tenant(database_url: str, tmp_path: Path) -> None:
    assert install_tenant(Settings(tenancy_mode="multi")) is None
    await seed(database_url, _moved(tmp_path, "ten_multi"), only_tenant=None)


def test_the_install_s_tenant_is_the_bootstrap_tenant_when_one_is_set() -> None:
    assert install_tenant(Settings(tenancy_mode="single", bootstrap_tenant_id="ten_bank")) == "ten_bank"


def test_only_tenant_creation_reads_the_mode() -> None:
    readers: set[str] = set()
    for src in (*ROOT.glob("packages/*/src"), *ROOT.glob("services/*/src")):
        for path in src.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Attribute) and node.attr == "tenancy_mode":
                    readers.add(path.relative_to(ROOT).as_posix())
    assert readers == {"services/platform-service/src/ops_platform/tenants.py"}
