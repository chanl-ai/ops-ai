"""Rule 6b of check_standards, by failure mode: a second log setup (basicConfig, uvicorn's own handlers) prints lines
a collector cannot parse, and a value in an event name makes every line a different event."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_standards  # pyright: ignore[reportMissingImports]

standards: Any = check_standards
ROOT: Path = standards.ROOT
SERVICE_FILE = ROOT / "services" / "x-service" / "src" / "ops_x" / "__main__.py"


def findings(source: str, path: Path = SERVICE_FILE) -> list[str]:
    out: list[str] = []
    standards.check_logging(path, ast.parse(source), out)
    return out


@pytest.mark.parametrize(
    "source",
    [
        "import logging\nlogging.basicConfig(level=logging.INFO)",
        "import uvicorn\nuvicorn.run(app, port=1, log_level='info')",
        "import uvicorn\nuvicorn.run(app, port=1)",
        "import uvicorn\nuvicorn.Config(app, log_config=None)",
        "log.info(f'saved {name}')",
        "log.warning('saved %s', name)",
        "log.info(EVENT)",
    ],
)
def test_each_breach_is_a_finding(source: str) -> None:
    assert any("rule 6b" in f for f in findings(source)), source


def test_the_kits_forms_pass() -> None:
    ok = (
        "import uvicorn\nconfigure_logging(service='x-service')\n"
        "uvicorn.run(app, port=1, log_config=None, access_log=False)\n"
        "log.info('x.saved', name=name)\n(log.debug if quiet else log.info)('x.widen', reason=r)"
    )
    assert findings(ok) == []


def test_a_dev_fake_outside_services_may_set_its_own_uvicorn_level() -> None:
    fake = ROOT / "packages" / "ops_signin" / "src" / "ops_signin" / "fake_idp" / "__main__.py"
    assert findings("import uvicorn\nuvicorn.run(app, port=1, log_level='warning')", fake) == []
