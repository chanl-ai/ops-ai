"""Test tokens outlive the suite (ops_identity.testing): a module that mints its people's tokens at import, or in a
helper it calls at import, with a five-minute lifetime turns every request after minute five into a 401 that says
nothing about the code under test. By failure mode: a short-lived token minted against the wall clock coming back in
a test, and a scan that finds nothing because it reads nothing (first run on a file that breaks it)."""

from __future__ import annotations

import ast
from pathlib import Path

from ops_identity.testing import TEST_TOKEN_TTL_S

ROOT = Path(__file__).resolve().parents[2]
TESTS = [*sorted((ROOT / "services").glob("*/tests")), *sorted((ROOT / "packages").glob("*/tests"))]
MINTS = {"mint", "mint_service_token"}
# Review approval tokens (tools-service) are minted inside the test that sends them, and their lifetime is the
# behaviour under test.
APPROVAL_KEYS = {"REVIEW_KEY"}


def offences(root: Path) -> list[str]:
    """Each mint outside a test function (at import, or in a helper a module may call at import) whose literal
    lifetime is shorter than TEST_TOKEN_TTL_S and that does not fix the clock with `now`. A token minted inside the test
    that sends it is used at once."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        inside_tests = {
            id(n)
            for f in ast.walk(tree)
            if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef) and f.name.startswith("test_")
            for n in ast.walk(f)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or id(node) in inside_tests:
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            if name not in MINTS:
                continue
            if any(isinstance(a, ast.Name) and a.id in APPROVAL_KEYS for a in node.args):
                continue
            kw = {k.arg: k.value for k in node.keywords}
            ttl = kw.get("ttl_s")
            if "now" in kw or not isinstance(ttl, ast.Constant) or not isinstance(ttl.value, int):
                continue
            if ttl.value < TEST_TOKEN_TTL_S:
                where = path.relative_to(ROOT if path.is_relative_to(ROOT) else root.parent)
                found.append(f"{where}:{node.lineno}: ttl_s={ttl.value}")
    return found


def test_the_scan_finds_a_short_lived_token_on_the_wall_clock(tmp_path: Path) -> None:
    (tmp_path / "test_x.py").write_text(
        "HEADERS = mint(claims, PLATFORM, ttl_s=300)\n"
        "EXPIRED = mint(claims, PLATFORM, ttl_s=30, now=0)\n"
        "LONG = mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)\n"
        "def test_forged():\n    mint(claims, OTHER, ttl_s=60)\n"
    )
    assert offences(tmp_path) == [f"{tmp_path.name}/test_x.py:1: ttl_s=300"]


def test_no_test_mints_a_short_lived_token_on_the_wall_clock() -> None:
    assert len(TESTS) >= 6, f"the scan reads too few test folders: {TESTS}"
    found = [o for t in TESTS for o in offences(t)]
    assert found == [], "\n".join(found)
