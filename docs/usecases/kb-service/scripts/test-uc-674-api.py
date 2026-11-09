"""uc-674 a website source keeps a knowledge base current, and answers cite it, api layer:
docs/usecases/kb-service/a-website-source-keeps-a-knowledge.md. The website plugin (opsai.web, from the ops-ai-plugins
checkout beside this one, or OPS_PLUGINS_REPO) crawls a fake help centre served on https as help.northbank.test;
models-service runs its scripted aliases and a fake OpenAI with rules for the questions and FAQ steps, so no provider
is called. Every service runs on the use case's own ports and database."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fake_help_site import Proxied, help_site, page, proxied_site
from usecase_harness import (
    KB_PORT,
    ROOT,
    TOOLS_PORT,
    agents,
    check,
    data,
    fake_openai,
    finish,
    kb,
    models,
    sse,
    tools,
    until,
)

RUN = int(time.time())
OWNER = "maya@harborpine.example"
# kb-service's dev caller acts in team_ops; the plugin is turned on for that team.
OPS = {"X-Team-Id": "team_ops"}
SECURITY = {"X-Dev-User": "Nadia Petrov", "X-Team-Id": "team_security"}
PLUGINS_REPO = Path(os.environ.get("OPS_PLUGINS_REPO", str(ROOT.parent / "ops-ai-plugins")))
WEB_PLUGIN = PLUGINS_REPO / "plugins" / "web" / "src" / "ops_plugin_web"
PLUGINS = {"OPS_PLUGIN_PATHS": json.dumps([str(WEB_PLUGIN)])}
# The questions step and the FAQ drafts step, answered from the section the prompt names: each draft quotes the first
# sentence of its section, so its citation can be checked against the page.
RULES = {
    "rules": [
        {
            "when": r"question-and-answer pairs[\s\S]*Section: (?P<section>[^\n]+)[\s\S]*Section text:\n(?P<first>[^.\n]+\.)",
            "text": '{{"pairs": [{{"question": "quokka {section}?", "answer": "{first}", "quote": "{first}"}}]}}',
        },
        {
            "when": r"Write \d+ questions that a bank employee might ask[\s\S]*Section: (?P<section>[^\n]+)",
            "text": '{{"questions": ["What does the help centre say about {section}?"]}}',
        },
    ]
}


def items(k: Any, source_id: str) -> dict[str, dict[str, Any]]:
    return {i["path"]: i for i in data(k.get(f"/v1/sources/{source_id}/items", params={"pageSize": 100}))["data"]}


def ask(k: Any, kb_id: str, question: str) -> dict[str, Any]:
    return data(k.post(f"/v1/knowledge-bases/{kb_id}/query", json={"question": question}))


def agent(api: Any, name: str, collections: list[str]) -> str:
    made = data(api.post("/v1/agents", json={"name": f"{name} {RUN}", "role": "Answers help questions"}, headers=OPS))
    saved = data(api.patch(f"/v1/agents/{made['id']}", json={"collections": collections}, headers=OPS))
    api.post(
        f"/v1/agents/{made['id']}/publish-requests", json={"version": saved["version"], "note": "uc-674"}, headers=OPS
    )
    return str(made["id"])


def main() -> None:
    if not WEB_PLUGIN.is_dir():
        raise SystemExit(f"FAIL the website plugin is not at {WEB_PLUGIN}; set OPS_PLUGINS_REPO")
    with (
        tempfile.TemporaryDirectory(prefix="uc-674-") as tmp,
        help_site() as site,
        _docs_site() as docs,
        fake_openai(_rules(Path(tmp))) as fake,
        models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
        tools(settings={**_reach(Path(tmp), site, docs), **PLUGINS}) as gw,
        kb(
            Path(tmp) / "files",
            env={
                **PLUGINS,
                "OPS_TOOLS_URL": f"http://127.0.0.1:{TOOLS_PORT}",
                "OPS_MODELS_URL": models_url,
                "OPS_MODELS_KEY": "mk_dev_kb",
            },
        ) as k,
    ):
        data(gw.post("/v1/egress/ranges", json={"value": site.range, "note": "uc-674 help site"}, headers=SECURITY))
        if docs is not None and docs.range != site.range:
            data(gw.post("/v1/egress/ranges", json={"value": docs.range, "note": "uc-674 docs"}, headers=SECURITY))
        data(gw.put("/v1/apps/plugin:opsai.web/team", json={"enabled": True}, headers=OPS))
        start = {"start": [f"{site.base}/"], "include": ["/lending/**", "/cards/**"], "exclude": ["/archive/**"]}
        config = {"plugin": "opsai.web", "source": "site", "values": {**start, "rate": 20}}

        # Story 1: preview, nothing stored.
        before = data(k.get("/v1/sources"))["pagination"]["total"]
        asked = k.post("/v1/sources/preview", json={"type": "tool", "config": config})
        if asked.status_code != 200:
            raise SystemExit(f"FAIL 1 the preview answered {asked.status_code}: {asked.text[:600]}")
        preview = data(asked)
        outcomes = {p["id"].removeprefix(site.base): p["outcome"] for p in preview["pages"]}
        check(
            "1 the preview lists what will be fetched and why the rest is not, and stores nothing",
            outcomes.get("/lending/payment-holidays") == "Will fetch"
            and str(outcomes.get("/archive/2019-rates", "")).startswith("Excluded by rule")
            and data(k.get("/v1/sources"))["pagination"]["total"] == before,
            outcomes,
        )

        # Story 2: create, first sync, a re-sync fetches only what changed.
        base = data(k.post("/v1/knowledge-bases", json={"name": f"Help {RUN}", "owner": OWNER}))
        body = {"type": "tool", "name": f"Northbank help {RUN}", "config": config, "kbIds": [base["id"]]}
        src = data(k.post("/v1/sources", json=body))
        check(
            "2 the source is a website and says where it starts",
            (src["kind"], src["scopeSummary"]) == ("web", "help.northbank.test"),
            src.get("kind"),
        )
        site.hits.clear()
        first = data(k.post(f"/v1/sources/{src['id']}/sync"))
        taken = items(k, src["id"])
        check(
            "3 the first sync takes in the three allowed pages and never fetches the excluded or refused ones",
            first["counts"]["upserted"] == 3
            and all(
                taken[f"{site.base}{p}"]["status"] == "indexed"
                for p in ("/lending/early-repayment", "/lending/payment-holidays", "/cards/lost-card")
            )
            and "/archive/2019-rates" not in site.hits
            and "/admin/" not in site.hits,
            {"counts": first["counts"], "hits": sorted(set(site.hits))},
        )
        site.change(
            "/lending/payment-holidays",
            page(
                "Payment holidays",
                "A payment holiday pauses your loan payments for up to six months.",
                "Interest still builds up.",
            ),
            "2026-11-09",
        )
        site.hits.clear()
        second = data(k.post(f"/v1/sources/{src['id']}/sync"))
        fetched = [h for h in site.hits if h.startswith(("/lending/", "/cards/"))]
        check(
            "4 a re-sync fetches only the page that changed and indexes its new text",
            fetched == ["/lending/payment-holidays"] and second["counts"]["upserted"] == 1,
            {"fetched": fetched, "counts": second["counts"]},
        )
        six = ask(k, base["id"], "How long can a payment holiday last?")
        check(
            "5 search cites the page's new text",
            "six months" in " ".join(c["snippet"] for c in six["citations"]),
            six["citations"],
        )

        # Story 3: a page deleted at the site leaves search; one still listed but gone leaves after its second miss.
        site.remove("/cards/lost-card")
        dropped = data(k.post(f"/v1/sources/{src['id']}/sync"))
        lost = ask(k, base["id"], "freeze a lost card in the app")
        check(
            "6 a page deleted at the site, and from its sitemap, leaves search on the next sync",
            dropped["counts"]["deleted"] == 1
            and f"{site.base}/cards/lost-card" not in items(k, src["id"])
            and not any("lost card" in c["snippet"].lower() for c in lost["citations"]),
            {"counts": dropped["counts"], "cited": [c["title"] for c in lost["citations"]]},
        )
        early = "/lending/early-repayment"
        site.gone.add(early)
        site.lastmod[early] = "2026-11-09"
        once = data(k.post(f"/v1/sources/{src['id']}/sync"))
        still = f"{site.base}{early}" in items(k, src["id"])
        twice = data(k.post(f"/v1/sources/{src['id']}/sync"))
        stones = [t["id"] for t in data(k.get(f"/v1/sources/{src['id']}/tombstones"))]
        check(
            "7 a page the sitemap still lists but that answers 404 twice leaves search and is tombstoned",
            still and f"{site.base}{early}" not in items(k, src["id"]) and stones == [f"{site.base}{early}"],
            {"first": once["counts"], "second": twice["counts"], "tombstones": stones},
        )

        # Story 4: meaning and keyword lanes; an agent cites a crawled page; another base is not searchable.
        lanes = six.get("lanes") or {}
        check(
            "8 a search says which lanes ran: keyword and meaning",
            lanes.get("ran") == ["keyword", "meaning"] and lanes.get("skipped") == [],
            lanes,
        )
        with agents(kb_url=f"http://127.0.0.1:{KB_PORT}") as api:
            granted = agent(api, "Help desk", [base["id"]])
            other = agent(api, "Card desk", [])
            thread = data(api.post("/chat/threads", json={"agentId": granted, "kbIds": [base["id"]]}, headers=OPS))
            res = api.post(
                f"/chat/threads/{thread['id']}/messages",
                json={"content": "How long can a payment holiday last?"},
                headers={**OPS, "Accept": "text/event-stream"},
            )
            cited = next((e["citations"] for e in sse(res.text) if e.get("type") == "citations"), [])
            check(
                "9 the agent's answer cites the crawled page by its address",
                any(str(c.get("url", "")).endswith("/lending/payment-holidays") for c in cited)
                or any("Payment holidays" in str(c.get("title", "")) for c in cited),
                cited,
            )
            refused = api.post("/chat/threads", json={"agentId": other, "kbIds": [base["id"]]}, headers=OPS)
            check(
                "10 an agent not given the knowledge base cannot search it",
                refused.status_code in (403, 422) and "cannot search" in refused.text,
                refused.text[:200],
            )

        # Story 5: questions and FAQ drafts, approved, and a pair cited back to its passage.
        current = data(k.get(f"/v1/sources/{src['id']}"))
        strategies = [*current["ingest"]["strategies"], "faq", "faq_pairs"]
        data(k.patch(f"/v1/sources/{src['id']}", json={"ingest": {"strategies": strategies, "model": "default"}}))
        estimate = data(k.get(f"/v1/sources/{src['id']}/ai-estimate"))
        data(k.post(f"/v1/sources/{src['id']}/ai-approval", json={"decision": "approve"}))
        # The settings save started a rebuild; the approval's rebuild follows it when it ends.
        rebuild = until(
            lambda: next(
                (r for r in data(k.get(f"/v1/sources/{src['id']}/runs"))["data"]
                 if r["status"] != "running" and r["counts"].get("modelCalls")),
                None,
            ),
            timeout=120,
        )  # fmt: skip
        check(
            "11 the estimate counts calls without calling a model, and approving rebuilds with questions and drafts",
            estimate["calls"] > 0
            and rebuild is not None
            and rebuild["status"] == "success"
            and rebuild["counts"].get("modelCalls", 0) > 0,
            {"estimate": estimate, "rebuild": rebuild and rebuild["counts"]},
        )
        drafts = [
            d
            for d in data(k.get("/v1/knowledge-changes", params={"view": "open"}))["data"]
            if d["origin"] == "generated_faq"
        ]
        holiday = next((d for d in drafts if "Payment holidays" in d["faq"]["question"]), None)
        check(
            "12 FAQ drafts wait in the Changes queue with the passage they quote",
            holiday is not None and holiday["before"] == holiday["faq"]["quote"],
            drafts,
        )
        if holiday is not None:
            data(k.post("/v1/knowledge-changes/decide", json={"ids": [holiday["id"]], "decision": "approve"}))
            found = data(
                k.post(
                    "/v1/knowledge-bases/search", json={"kbIds": [base["id"]], "question": holiday["faq"]["question"]}
                )
            )["passages"]
            top = next((p for p in found if p["matched"] == "faq"), None)
            check(
                "13 the approved pair answers its question and cites the source passage on the page",
                top is not None
                and str(top.get("url", "")).endswith("/lending/payment-holidays")
                and holiday["faq"]["quote"] in top["text"],
                found[:2],
            )

        # Story 6, when the repo's docs site runs (OPS_DOCS_SITE_URL): a real site with no sitemap, crawled by links.
        if docs is not None:
            values = {"start": [f"{docs.base}/docs"], "follow_links": True, "depth": 2, "max_pages": 25, "rate": 20}
            body = {
                "type": "tool",
                "name": f"Ops AI docs {RUN}",
                "config": {"plugin": "opsai.web", "source": "site", "values": values},
                "kbIds": [base["id"]],
            }
            made = data(k.post("/v1/sources", json=body))
            crawled = data(k.post(f"/v1/sources/{made['id']}/sync"))
            pages = items(k, made["id"])
            answer = ask(k, base["id"], "agents and workflows for regulated operations teams")
            check(
                "14 the repo's docs site is crawled by its links and answers a question from it",
                crawled["counts"]["upserted"] >= 5
                and any(str(c.get("documentId", "")) in {i["id"] for i in pages.values()} for c in answer["citations"]),
                {
                    "counts": crawled["counts"],
                    "errors": crawled["errors"][:3],
                    "pages": len(pages),
                    "cited": [c["title"] for c in answer["citations"]],
                },
            )
    finish()


@contextmanager
def _docs_site() -> Generator[Proxied | None]:
    url = os.environ.get("OPS_DOCS_SITE_URL")
    if not url:
        yield None
        return
    with proxied_site(url) as docs:
        yield docs


def _reach(folder: Path, site: Any, docs: Proxied | None) -> dict[str, str]:
    """What tools-service needs to reach both sites: one CA bundle and one name map."""
    if docs is None:
        return dict(site.settings)
    bundle = folder / "sites-ca.pem"
    bundle.write_text(
        Path(site.settings["OPS_EGRESS_CA_FILE"]).read_text() + Path(docs.settings["OPS_EGRESS_CA_FILE"]).read_text()
    )
    names = {**json.loads(site.settings["OPS_EGRESS_RESOLVE"]), **json.loads(docs.settings["OPS_EGRESS_RESOLVE"])}
    return {"OPS_EGRESS_CA_FILE": str(bundle), "OPS_EGRESS_RESOLVE": json.dumps(names)}


def _rules(folder: Path) -> Path:
    rules = folder / "fake-openai"
    rules.mkdir(parents=True, exist_ok=True)
    (rules / "script.json").write_text(json.dumps(RULES))
    return rules


if __name__ == "__main__":
    main()
