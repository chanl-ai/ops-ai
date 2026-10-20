"""One API for people and services (c-168): no service serves or calls a `/v1/internal` route, and no HTTP route fires
a timer. By failure mode: an internal route or client call coming back in a service or package, and a scan that finds
nothing because it reads nothing (each check is first run on a file that breaks it)."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [*sorted((ROOT / "services").glob("*/src")), *sorted((ROOT / "packages").glob("*/src"))]


def offences(root: Path) -> list[str]:
    """Every string literal in Python source under `root` that names a `/v1/internal` path or a timer `fire` route."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            text = node.value
            if "/v1/internal" in text or ("/timers/" in text and text.rstrip("/").endswith("/fire")):
                found.append(f"{path.relative_to(root)}:{node.lineno}: {text[:80]}")
    return found


def test_the_scan_finds_an_internal_route_and_a_fire_route(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        'router = APIRouter(prefix="/v1/internal/files")\n'
        '@router.post("/v1/threads/{thread_id}/timers/{timer_id}/fire")\n'
        "def fire(): ...\n"
    )
    assert len(offences(tmp_path)) == 2


def test_no_service_or_package_serves_or_calls_an_internal_route() -> None:
    assert len(SOURCES) >= 6, f"the scan reads too few source folders: {SOURCES}"
    found = [o for src in SOURCES for o in offences(src)]
    assert found == [], "\n".join(found)
