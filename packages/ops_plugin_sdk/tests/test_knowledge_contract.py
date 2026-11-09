"""The knowledge-source contract, by failure mode: a plugin that fetches an item again though its version tag still
matches, one whose changes miss an edit, a source's call reaching a host its settings never named, and a manifest
whose source tools cannot be sent the source's settings."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_validate import problems

from ops_plugin_sdk import EgressDenied, Plugin
from ops_plugin_sdk.testing import Fake, call, knowledge_contract

MANIFEST = """
schema: ops-ai/plugin@2
id: demo.pages
title: Pages
version: 0.1.0
sdk: "1"
connection:
  kinds: [none]
  sign_in: [team]
egress: ["https://api.pages.test"]
endpoint: "https://api.pages.test"
tools:
  - { name: list_pages, access: read, knowledge: list_items, function: demo_pages.kb:list_pages,
      input: { source: { type: object }, since: { type: string, required: false },
               cursor: { type: string, required: false } } }
  - { name: get_page, access: read, knowledge: get_item, function: demo_pages.kb:get_page,
      input: { source: { type: object }, id: { type: string }, tag: { type: string, required: false } } }
  - { name: changed_pages, access: read, knowledge: list_changes, function: demo_pages.kb:changed_pages,
      input: { source: { type: object }, cursor: { type: string, required: false } } }
knowledge_sources:
  - name: site
    title: A website
    list: list_pages
    get: get_page
    changes: changed_pages
    egress_from: start
    inputs: { start: { type: string } }
"""

KB = """
from ops_plugin_sdk import tool

@tool(access="read")
def list_pages(ctx, source, since=None, cursor=None):
    rows = ctx.http.get(source["start"] + "/index.json").json()
    return {"items": [r for r in rows if not since or r["updated_at"] > since],
            "watermark": max((r["updated_at"] for r in rows), default=None)}

@tool(access="read")
def get_page(ctx, source, id, tag=None):
    r = ctx.http.get(source["start"] + "/" + id)
    if TAGS and tag and tag == r.headers.get("etag"):
        return {"unchanged": True}
    return {"id": id, "content": r.text, "mime": "text/html", "marker": r.headers.get("etag")}

@tool(access="read")
def changed_pages(ctx, source, cursor=None):
    rows = ctx.http.get(source["start"] + "/index.json").json()
    return {"items": [r for r in rows if not cursor or r["updated_at"] > cursor],
            "cursor": max((r["updated_at"] for r in rows), default=None)}

TAGS = True
"""


class Site:
    """A website as the fake system: pages by id, each with its text, its time and an ETag that follows its text."""

    def __init__(self) -> None:
        self.pages = {
            "claims": ("<h1>Claims</h1>", "2026-11-01T00:00:00Z"),
            "fees": ("<h1>Fees</h1>", "2026-11-02T00:00:00Z"),
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        page = request.url.path.strip("/")
        if page == "index.json":
            rows = [{"id": k, "title": k, "updated_at": t} for k, (_, t) in self.pages.items()]
            return httpx.Response(200, text=json.dumps(rows))
        text, _ = self.pages[page]
        return httpx.Response(200, text=text, headers={"etag": f'"{abs(hash(text))}"'})

    def change(self) -> str:
        self.pages["fees"] = ("<h1>Fees</h1><p>New charges</p>", "2026-11-09T00:00:00Z")
        return "fees"

    def delete(self) -> str:
        del self.pages["claims"]
        return "claims"


def pages_plugin(tmp_path: Path, manifest: str = MANIFEST, kb: str = KB) -> Plugin:
    root = tmp_path / "demo_pages"
    root.mkdir(parents=True)
    (root / "plugin.yaml").write_text(textwrap.dedent(manifest))
    (root / "__init__.py").write_text("from ops_plugin_sdk import Plugin\nplugin = Plugin.beside(__file__)\n")
    (root / "kb.py").write_text(textwrap.dedent(kb))
    sys.modules.pop("demo_pages", None)
    sys.modules.pop("demo_pages.kb", None)
    # The tools are imported as demo_pages.kb, from the folder holding the plugin.
    sys.path.insert(0, str(tmp_path))
    return Plugin.beside(str(root / "__init__.py"))


def fake(site: Site) -> Fake:
    return Fake(httpx.Client(transport=httpx.MockTransport(site.handle)), "t")


VALUES: dict[str, Any] = {"start": "https://help.northbank.test"}


def test_a_plugin_that_keeps_the_contract_passes(tmp_path: Path) -> None:
    site = Site()
    found = knowledge_contract(
        pages_plugin(tmp_path), "site", fake(site), settings={}, values=VALUES, change=site.change, delete=site.delete
    )
    assert found == [], found


def test_a_fetch_that_ignores_a_matching_tag_is_named(tmp_path: Path) -> None:
    site = Site()
    plugin = pages_plugin(tmp_path, kb=KB.replace("TAGS = True", "TAGS = False"))
    found = knowledge_contract(
        plugin, "site", fake(site), settings={}, values=VALUES, change=site.change, delete=site.delete
    )
    assert any("fetched claims again though its tag" in p for p in found), found


def test_a_source_reaches_only_the_hosts_its_settings_name(tmp_path: Path) -> None:
    site = Site()
    assert call(pages_plugin(tmp_path), "list_pages", {"source": VALUES}, {}, fake(site))["items"]
    plain = pages_plugin(tmp_path / "plain", MANIFEST.replace("    egress_from: start\n", ""))
    with pytest.raises(EgressDenied):
        call(plain, "list_pages", {"source": VALUES}, {}, fake(site))


def test_source_tools_without_a_source_input_or_an_unknown_egress_input_are_refused(tmp_path: Path) -> None:
    root = tmp_path / "check"
    root.mkdir()
    bad = MANIFEST.replace("egress_from: start", "egress_from: start_urls").replace(
        "input: { source: { type: object }, cursor: { type: string, required: false } } }",
        "input: { cursor: { type: string, required: false } } }",
    )
    plugin = pages_plugin(root, bad)
    del plugin
    found = problems(root / "demo_pages")
    assert any("egress_from names start_urls" in p for p in found), found
    assert any("changed_pages takes no source input" in p for p in found), found
