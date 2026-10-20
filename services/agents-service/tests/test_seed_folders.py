"""Services seed from their own seed/ folders, never test fixtures (c-067 T001), by failure mode: a dev service still
reading tests/ (so a test change changes what the product shows), production starting with the demo seed, a named
seed directory being dropped outside dev, and rule 3b missing a tests/ path in source code or flagging a name that
is not one."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from pydantic import SecretStr

from ops_agents.activities.catalog import load_catalog
from ops_service_kit.settings import Settings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_standards  # pyright: ignore[reportMissingImports]

SERVICE = Path(__file__).resolve().parents[1]


def production(**kw: object) -> Settings:
    return Settings(
        environment="production",
        auth_mode="platform",
        review_key=SecretStr("r" * 40),
        secrets_key=SecretStr("ab" * 32),
        **kw,  # pyright: ignore[reportArgumentType]
    )


def test_dev_services_read_their_seed_folders_not_tests() -> None:
    dev = Settings()
    assert dev.seed_dir is not None and dev.seed_dir == SERVICE / "seed"
    assert dev.platform_seed_file == SERVICE.parent / "platform-service" / "seed" / "people.json"
    assert dev.platform_seed_file.is_file()
    for p in (dev.seed_dir, dev.platform_seed_file, dev.tools_seed_file):
        assert "tests" not in p.parts, p


def test_production_starts_with_no_seed_unless_one_is_named(tmp_path: Path) -> None:
    assert production().seed_dir is None
    empty = load_catalog(None)
    assert (empty.agents, empty.tools, empty.knowledge_bases) == ([], [], [])
    assert production(seed_dir=tmp_path).seed_dir == tmp_path


def findings(source: str) -> list[str]:
    out: list[str] = []
    root = Path(str(check_standards.ROOT))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    path = root / "services" / "x-service" / "src" / "ops_x" / "m.py"
    check_standards.check_tests_paths(path, ast.parse(source), out)  # pyright: ignore[reportUnknownMemberType]
    return out


def test_rule_3b_finds_a_tests_path_in_source_code() -> None:
    assert findings('SEED = ROOT / "services" / "agents-service" / "tests" / "fixtures" / "seed"\n')
    assert findings('SEED = Path("services/agents-service/tests/fixtures/seed")\n')
    assert findings('PEOPLE = ROOT / "tests/fixtures/people.json"\n')


def test_rule_3b_leaves_names_and_docstrings_alone() -> None:
    assert findings('"""Seeded like tests/fixtures/seed is."""\nBODY = {"tests": [], "runs": []}\n') == []


def test_rule_5_counts_a_route_a_person_or_any_service_of_the_tenant_calls_as_authenticated() -> None:
    """Knowledge usage and workflow refs authenticate through current_tenant_caller (c-222); rule 5 read them as
    open."""
    out: list[str] = []
    checked = check_standards.check_routes(out)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    assert checked and not [o for o in out if "rule 5" in o], out
