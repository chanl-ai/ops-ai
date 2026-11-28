"""The code rules every service holds, by failure mode: an environment read outside the settings module, a route with
no sign-in, a print or a logger of its own, and a log event built from a value are each found, and clean code is not;
a route check that sees no route fails instead of passing."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi import Depends, FastAPI

from ops_service_kit import standards


def signed_in() -> str:
    return "caller"


def things() -> dict[str, str]:
    return {}


def health() -> dict[str, str]:
    return {}


def _app(*, guarded: bool = True) -> FastAPI:
    app = FastAPI()
    dependencies = [Depends(signed_in)] if guarded else []
    app.get("/v1/things", dependencies=dependencies)(things)
    app.get("/health")(health)
    return app


def _check(tmp_path: Path, source: str, app: FastAPI | None = None, public: tuple[str, ...] = ()) -> list[str]:
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "mod.py").write_text(source)
    return standards.check(
        app or _app(),
        settings_module="ops_service_kit.settings",
        authenticated={signed_in},
        public=public,
        roots=[src],
    )


def test_clean_source_and_a_guarded_route_pass(tmp_path: Path) -> None:
    clean = (
        'from ops_service_kit.logging import get_logger\nlog = get_logger(__name__)\nlog.info("thing.saved", id=1)\n'
    )
    assert _check(tmp_path, clean) == []


def test_each_breach_is_named_by_rule(tmp_path: Path) -> None:
    source = (
        "import os\nimport logging\n"
        "key = os.environ['A']\n"
        "print('x')\n"
        "logger = logging.getLogger('x')\n"
        "log.info(f'saved {key}')\n"
    )
    found = _check(tmp_path, source)
    for rule in ("rule 4", "rule 6: print", "rule 6: logging.getLogger", "rule 6b: a log call's event"):
        assert any(rule in line for line in found), (rule, found)


def test_an_environment_read_or_a_logger_imported_by_name_or_under_another_name_is_found(tmp_path: Path) -> None:
    source = (
        "from os import environ, getenv as get\nimport os as o\nfrom logging import getLogger\nkey = o.environ['A']\n"
    )
    found = _check(tmp_path, source)
    assert sorted(line.split(" rule ", 1)[1].split(":")[0] for line in found if " rule " in line) == [
        "4",
        "4",
        "6",
    ], found


def test_a_route_with_no_sign_in_is_found_unless_it_is_listed_public(tmp_path: Path) -> None:
    found = _check(tmp_path, "x = 1\n", _app(guarded=False))
    assert any("/v1/things" in line and "rule 5" in line for line in found), found
    assert _check(tmp_path, "x = 1\n", _app(guarded=False), public=("/v1/things",)) == [
        "rule 5: no authenticated routes were found to check"
    ]


def test_the_settings_module_alone_may_read_the_environment() -> None:
    kit = Path(standards.__file__).parent
    found = standards.check(_app(), settings_module="ops_service_kit.settings", authenticated={signed_in}, roots=[kit])
    assert [line for line in found if "rule 4" in line] == [], found


def test_a_request_models_bare_str_name_is_found_and_a_name_type_is_not() -> None:
    tree = ast.parse(
        "class A(In):\n    name: str\n    title: str | None = None\n"
        "class B(In):\n    name: Name\n    label: str = Field(pattern='^[a-z]+$')\n"
        "class C(Out):\n    name: str\n"
    )
    found = standards.check_names(Path("x.py"), tree, set())
    assert [f.split(" names: ")[1].split(" is")[0] for f in found] == ["A.name", "A.title"]
    assert standards.check_names(Path("x.py"), tree, {"x.py:A.name", "x.py:A.title"}) == []


def test_a_model_call_posted_outside_the_one_client_is_found_and_the_workspace_has_none(tmp_path: Path) -> None:
    own = (
        'async def ask(http):\n    return await http.post("/v1/models/chat/completions", json={})\n'
        'async def built(http, base):\n    return await http.post(base + "/chat/completions", json={})\n'
        'def client(base):\n    return f"{base}/v1/models"\n'
    )
    found = _check(tmp_path, own)
    assert [f.split(" ", 1)[1] for f in found] == ["rule SC1: a model call outside ops_service_kit.model_calls"] * 3
    assert standards.model_call_breaches(standards.source_roots()) == []
