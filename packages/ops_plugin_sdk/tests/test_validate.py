"""`ops plugin validate` and the loader, one test per way a plugin can be wrong and still look installable: an unknown
sign-in kind, a write used as a knowledge tool, a template that needs a tool the plugin lacks, a misspelt field, a
Python tool whose access disagrees with the manifest, and one broken package taking the others down at load."""

from __future__ import annotations

import sys
import textwrap
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from ops_plugin_sdk import Plugin
from ops_plugin_sdk.cli import main
from ops_plugin_sdk.loader import discover
from ops_plugin_sdk.validate import validate

MANIFEST = """
schema: ops-ai/plugin@2
id: demo.desk
title: Desk
version: 0.1.0
sdk: "1"
connection:
  kinds: [oauth2_auth_code]
  sign_in: [team]
  from_token: { instance_url: instance_url }
  token_hosts: [.my.desk.test]
settings:
  instance_url: { type: string, from_token: true }
  api_version: { type: string, default: "1", lockable: true }
egress: ["{instance_url}"]
endpoint: "{instance_url}/api/v{api_version}"
tools:
  - name: get_case
    access: read
    input: { id: { type: string } }
    request: { method: GET, path: "/cases/{id}" }
  - name: list_articles
    access: read
    knowledge: list_items
    function: demo_desk.kb:list_articles
    input:
      since: { type: string, required: false }
      cursor: { type: string, required: false }
  - name: get_article
    access: read
    knowledge: get_item
    input: { id: { type: string } }
    request: { method: GET, path: "/articles/{id}" }
knowledge_sources:
  - { name: articles, title: Articles, list: list_articles, get: get_article }
templates:
  - { kind: agent, id: helper, version: 1, path: templates/helper.yaml, requires: { tools: [get_case] } }
"""

KB = """
from ops_plugin_sdk import tool

@tool(access="read")
def list_articles(ctx, since=None, cursor=None):
    return {"items": []}
"""


def plugin(tmp_path: Path, manifest: str = MANIFEST, kb: str = KB) -> Path:
    root = tmp_path / "demo_desk"
    (root / "templates").mkdir(parents=True)
    (root / "plugin.yaml").write_text(textwrap.dedent(manifest))
    (root / "__init__.py").write_text("from ops_plugin_sdk import Plugin\nplugin = Plugin.beside(__file__)\n")
    (root / "kb.py").write_text(textwrap.dedent(kb))
    (root / "templates" / "helper.yaml").write_text("name: Helper\ninstructions: Help.\n")
    sys.modules.pop("demo_desk", None)
    sys.modules.pop("demo_desk.kb", None)
    return root


def problems(root: Path) -> list[str]:
    return [str(p) for p in validate(root)[1]]


def test_a_good_plugin_validates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = plugin(tmp_path)
    assert problems(root) == []
    assert main(["plugin", "validate", str(root)]) == 0
    assert "OK demo.desk 0.1.0: 3 tools, 1 knowledge sources, 1 templates" in capsys.readouterr().out


def test_an_unknown_sign_in_kind_is_refused(tmp_path: Path) -> None:
    root = plugin(tmp_path, MANIFEST.replace("kinds: [oauth2_auth_code]", "kinds: [saml_magic]"))
    assert any("unknown sign-in kind saml_magic" in p for p in problems(root))
    assert main(["plugin", "validate", str(root)]) == 1


def test_a_write_used_as_a_knowledge_tool_is_refused(tmp_path: Path) -> None:
    bad = MANIFEST.replace("  - name: get_article\n    access: read", "  - name: get_article\n    access: write")
    assert any("get_item tool must be a read" in p for p in problems(plugin(tmp_path, bad)))


def test_a_template_that_needs_a_missing_tool_is_refused(tmp_path: Path) -> None:
    bad = MANIFEST.replace("requires: { tools: [get_case] }", "requires: { tools: [close_case] }")
    assert any("requires the tool close_case" in p for p in problems(plugin(tmp_path, bad)))


def test_a_misspelt_field_is_refused_not_ignored(tmp_path: Path) -> None:
    bad = MANIFEST.replace('    request: { method: GET, path: "/cases/{id}" }', "    requets: { method: GET }")
    assert any(
        "Extra inputs are not permitted" in p or "exactly one of request" in p for p in problems(plugin(tmp_path, bad))
    )


def test_a_python_tool_whose_access_disagrees_is_refused(tmp_path: Path) -> None:
    root = plugin(tmp_path, kb=KB.replace('access="read"', 'access="write"'))
    assert any("@tool says write, the manifest says read" in p for p in problems(root))


def test_a_list_items_function_without_since_and_cursor_is_refused(tmp_path: Path) -> None:
    root = plugin(tmp_path, kb=KB.replace("def list_articles(ctx, since=None, cursor=None)", "def list_articles(ctx)"))
    assert any("takes since and cursor" in p for p in problems(root))


def test_a_python_tool_parameter_that_is_not_a_declared_input_is_refused(tmp_path: Path) -> None:
    # tools-service checks every call against the declared inputs, so an undeclared parameter could never be passed:
    # the listing's second page would be refused for its cursor.
    root = plugin(tmp_path, manifest=MANIFEST.replace("      cursor: { type: string, required: false }\n", ""))
    said = "cursor is a parameter of demo_desk.kb:list_articles but not a declared input"
    assert any(said in p for p in problems(root))
    required = MANIFEST.replace("since: { type: string, required: false }", "since: { type: string }")
    optional = plugin(tmp_path / "b", manifest=required)
    assert any("since and cursor are optional inputs" in p for p in problems(optional))


def test_one_broken_plugin_is_reported_and_the_others_load(tmp_path: Path) -> None:
    root = plugin(tmp_path)
    sys.path.insert(0, str(root.parent))
    try:
        broken = tmp_path / "broken_plugin.py"
        broken.write_text("raise RuntimeError('this package cannot import')\n")
        found = [
            EntryPoint("desk", "demo_desk:plugin", "ops_ai.plugins"),
            EntryPoint("broken", "broken_plugin:plugin", "ops_ai.plugins"),
        ]
        sys.path.insert(0, str(tmp_path))
        loaded = {item.name: item for item in discover(found)}
    finally:
        sys.path.remove(str(root.parent))
        sys.path.remove(str(tmp_path))
    assert loaded["desk"].ok and isinstance(loaded["desk"].plugin, Plugin)
    assert not loaded["broken"].ok and "cannot import" in str(loaded["broken"].error)


def test_a_plugin_in_its_own_repository_runs_its_tests_without_being_installed(tmp_path: Path) -> None:
    # A built-in plugin lives in its own repository (ops-ai-plugins), not in the workspace that installs the kit, so
    # its package is not importable until `ops plugin test` puts its src/ on the path.
    project = tmp_path / "salesforce"
    pkg = plugin(project / "src")
    (project / "pyproject.toml").write_text('[project]\nname = "demo-desk"\nversion = "0.1.0"\n')
    (project / "tests").mkdir()
    (project / "tests" / "test_it.py").write_text(
        "from demo_desk import plugin\n\n\ndef test_it_loads() -> None:\n    assert plugin.manifest.id == 'demo.desk'\n"
    )
    assert pkg.parent.name == "src"
    assert main(["plugin", "test", str(project)]) == 0
