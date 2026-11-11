# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-678 a team takes in SharePoint libraries and Confluence spaces, api layer:
docs/usecases/kb-service/sharepoint-and-confluence-sources.md. The SharePoint and Confluence plugins (from the
ops-ai-plugins checkout beside this one, or OPS_PLUGINS_REPO) run in tools-service against their own fakes, served on
https under graph.microsoft.com and the Confluence site's name (docs/usecases/lib/fake_sharepoint_confluence.py). The
team signs SharePoint in through a fake Microsoft sign-in with a client secret made for the run, and Confluence with an
API token made for the run. kb-service reads both through tools-service. No model is called."""

from __future__ import annotations

import io
import tempfile
import time
from pathlib import Path
from typing import Any

from docx import Document
from fake_sharepoint_confluence import FAILING_QUERY, connect, stack
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate
from usecase_harness import KB_PORT, agents, check, data, finish, sse

RUN = int(time.time())
OWNER = "maya@harborpine.example"
OPS = {"X-Team-Id": "team_ops"}
SECURITY = {"X-Dev-User": "Nadia Petrov", "X-Team-Id": "team_security"}
SHAREPOINT, CONFLUENCE = "opsai.sharepoint", "opsai.confluence"


def pdf(title: str, text: str) -> bytes:
    styles = getSampleStyleSheet()
    out = io.BytesIO()
    SimpleDocTemplate(out, pagesize=A4, title=title).build(
        [Paragraph(title, styles["Title"]), Paragraph(text, styles["BodyText"])]
    )
    return out.getvalue()


def docx(title: str, text: str) -> bytes:
    made = Document()
    made.add_heading(title, level=1)
    made.add_paragraph(text)
    out = io.BytesIO()
    made.save(out)
    return out.getvalue()


def items(k: Any, source_id: str) -> dict[str, dict[str, Any]]:
    return {i["path"]: i for i in data(k.get(f"/v1/sources/{source_id}/items", params={"pageSize": 100}))["data"]}


def search(k: Any, kb_id: str, question: str) -> list[dict[str, Any]]:
    return list(data(k.post("/v1/knowledge-bases/search", json={"kbIds": [kb_id], "question": question}))["passages"])


def scopes(k: Any, plugin: str, source: str, **asked: str) -> Any:
    return k.post("/v1/sources/scopes", json={"plugin": plugin, "source": source, **asked})


def source(k: Any, kb_id: str, plugin: str, name: str, values: dict[str, Any]) -> dict[str, Any]:
    body = {"type": "tool", "name": f"{name} {RUN}", "kbIds": [kb_id],
            "config": {"plugin": plugin, "source": name, "values": values}}  # fmt: skip
    made = k.post("/v1/sources", json=body)
    if made.status_code != 201:
        raise SystemExit(f"FAIL the {plugin} source was not made: {made.status_code} {made.text[:400]}")
    return data(made)


def agent(api: Any, collections: list[str]) -> str:
    made = data(
        api.post("/v1/agents", json={"name": f"Policy desk {RUN}", "role": "Answers policy questions"}, headers=OPS)
    )
    saved = data(api.patch(f"/v1/agents/{made['id']}", json={"collections": collections}, headers=OPS))
    api.post(
        f"/v1/agents/{made['id']}/publish-requests", json={"version": saved["version"], "note": "uc-678"}, headers=OPS
    )
    return str(made["id"])


def cited(api: Any, agent_id: str, kb_id: str, question: str) -> list[dict[str, Any]]:
    thread = data(api.post("/chat/threads", json={"agentId": agent_id, "kbIds": [kb_id]}, headers=OPS))
    res = api.post(
        f"/chat/threads/{thread['id']}/messages",
        json={"content": question},
        headers={**OPS, "Accept": "text/event-stream"},
    )
    return next((e["citations"] for e in sse(res.text) if e.get("type") == "citations"), [])


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uc-678-") as tmp, stack(Path(tmp)) as (k, gw, systems):
        graph, wiki, ids = systems.graph, systems.confluence, systems.graph_ids

        # Set-up as a team does it: Security allows the hosts and range, a team admin signs each app in.
        done = connect(gw, systems, OPS, SECURITY)
        kinds = {
            (d.get("plugin"), d.get("source")): d
            for d in data(k.get("/v1/knowledge/source-kinds"))
            if d.get("type") == "tool"
        }
        sp, cf = kinds.get((SHAREPOINT, "files"), {}), kinds.get((CONFLUENCE, "spaces"), {})
        check(
            "0 the team signs SharePoint in through Microsoft with its own app and Confluence with an API token, and "
            "Add source offers both as connected, with pickers",
            all(s in (200, 201, 409) for s in done["allowed"])
            and done["sharepoint"]["done"] == 200
            and done["sharepoint"]["opened"] == "login.microsoftonline.com/organizations/oauth2/v2.0/authorize"
            and (done["confluence"]["health"] or {}).get("status") == "ok"
            and sp.get("connected") is True and sp.get("pickers") is True
            and cf.get("connected") is True and cf.get("pickers") is True
            and systems.refused == [],
            {"connect": done, "kinds": {"sp": sp.get("connected"), "cf": cf.get("connected")}, "refused": systems.refused},
        )  # fmt: skip

        # Steps 1-2: the pickers, through kb-service to the plugin's scopes tool as the team's connection.
        sites = scopes(k, SHAREPOINT, "files", query="human")
        found = [(s["id"], s["title"], s["kind"]) for s in (data(sites) or {}).get("scopes", [])]
        check(
            "1 the sites picker searched for 'human' lists Human Resources, from Graph's site search",
            sites.status_code == 200 and found == [(ids.SITE_HR, "Human Resources", "site")],
            {"status": sites.status_code, "found": found or sites.text[:300]},
        )
        libraries = scopes(k, SHAREPOINT, "files", parent=ids.SITE_HR)
        libs = {s["id"]: s for s in (data(libraries) or {}).get("scopes", [])}
        check(
            "2 the libraries picker lists the site's two document libraries, each under the site",
            libraries.status_code == 200
            and set(libs) == {ids.LIB_POLICIES, ids.LIB_HANDBOOK}
            and all(s["kind"] == "library" and s.get("parent") == ids.SITE_HR for s in libs.values()),
            {"status": libraries.status_code, "libraries": list(libs.values()) or libraries.text[:300]},
        )
        # Add source asks each picker for what every value picked in another holds, so a library is asked too.
        held = scopes(k, SHAREPOINT, "files", parent=ids.LIB_POLICIES)
        check(
            "2a a picked library asked for what it holds answers nothing, so the sites picker beside it stays usable",
            held.status_code == 200 and data(held)["scopes"] == [],
            held.text[:300],
        )
        empty = scopes(k, SHAREPOINT, "files", query="zebra")
        failed = scopes(k, SHAREPOINT, "files", query=FAILING_QUERY)
        check(
            "2b a search nothing matches answers no sites, and Graph's failure answers 503 with the plugin's reason",
            empty.status_code == 200 and data(empty)["scopes"] == []
            and failed.status_code == 503 and failed.json()["error"]["code"] == "scopes_failed"
            and "503" in failed.json()["error"]["message"],
            {"empty": empty.text[:200], "failed": failed.text[:300]},
        )  # fmt: skip

        # Step 3: the first sync takes in what was picked. The library's PDF and Word file are real documents, and two
        # files carry who may read them as Graph lists permissions.
        policies, handbook = graph.drives[ids.LIB_POLICIES], graph.drives[ids.LIB_HANDBOOK]
        policies["p3"].content = pdf("Travel", "Book rail for any trip under four hours.")
        handbook["h1"].content = docx("Welcome", "Your first week starts with a visit to the King Street branch.")
        policies["p1"].permissions = [
            {"id": "a", "grantedToV2": {"user": {"id": "u-dana", "displayName": "Dana Ortiz"}}},
            {"id": "b", "grantedToIdentitiesV2": [{"group": {"id": "g-hr", "displayName": "HR"}}]},
        ]
        policies["p2"].permissions = [{"id": "c", "grantedToV2": {"group": {"id": "g-finance"}}}]
        base = data(k.post("/v1/knowledge-bases", json={"name": f"Policies and runbooks {RUN}", "owner": OWNER}))
        files = source(k, base["id"], SHAREPOINT, "files", {"sites": [ids.SITE_HR], "libraries": list(libs)})
        first = data(k.post(f"/v1/sources/{files['id']}/sync"))
        taken = items(k, files["id"])
        # Who may read each file is kept on its version, shown on the item's own page.
        allowed = {
            p.split(":")[-1]: [v.get("allowed") for v in data(k.get(f"/v1/items/{r['id']}"))["detail"]["versions"]]
            for p, r in taken.items()
        }
        check(
            "3 the first sync takes in every file of the picked libraries, Markdown, text, PDF and Word, each indexed "
            "as a snapshot file with who may read it",
            first["status"] == "success"
            and {p.split(":")[-1] for p in taken} == {"p1", "p2", "p3", "h1"}
            and all(r["status"] == "indexed" and r.get("fileId") for r in taken.values())
            and allowed.get("p1") == [["u-dana", "g-hr"]] and allowed.get("p2") == [["g-finance"]]
            and systems.refused == [],
            {"run": first["counts"], "errors": first.get("errors", [])[:3],
             "items": {p: (r["status"], bool(r.get("fileId")), allowed.get(p.split(":")[-1]), r.get("error"))
                       for p, r in taken.items()}},
        )  # fmt: skip
        leave_hits = search(k, base["id"], "leave days a year")
        rail = search(k, base["id"], "book rail trip under four hours")
        check(
            "3b search cites the SharePoint file by its address in the library, and finds the PDF's text",
            any("Twenty days" in p["text"] and "leave.md" in str(p.get("url") or p.get("title")) for p in leave_hits)
            and any("four hours" in p["text"] for p in rail),
            {"leave": [(p.get("title"), p.get("url"), p["text"][:60]) for p in leave_hits[:3]],
             "rail": [(p.get("title"), p["text"][:60]) for p in rail[:2]]},
        )  # fmt: skip

        # Step 4: one file changed and one deleted at Graph; the delta query names both, and only the changed one is
        # fetched again.
        before = len(graph.downloads())
        graph.edit(ids.LIB_POLICIES, "p2", b"Claim expenses within 14 days of the trip.\n")
        graph.remove(ids.LIB_POLICIES, "p1")
        second = data(k.post(f"/v1/sources/{files['id']}/sync"))
        fetched = [p.split("/")[-2] for p in graph.downloads()[before:]]
        check(
            "4 the second sync fetches only the changed file, and indexes its new text",
            fetched == ["p2"] and second["counts"].get("upserted") == 1,
            {"fetched": fetched, "counts": second["counts"]},
        )
        gone = search(k, base["id"], "leave days a year")
        claim = search(k, base["id"], "claim expenses within days")
        check(
            "4b the deleted file leaves the source and search, and search quotes the changed file's new text",
            not any(p.endswith(":p1") for p in items(k, files["id"]))
            and not any("Twenty days" in p["text"] for p in gone)
            and any("14 days" in p["text"] for p in claim),
            {"counts": second["counts"], "gone": [p["text"][:40] for p in gone[:3]], "claim": [p["text"][:40] for p in claim[:3]]},
        )  # fmt: skip

        # Steps 5-6: Confluence, picked by space, then an edited page is the only page fetched again.
        spaces = scopes(k, CONFLUENCE, "spaces", query="eng")
        offered = [(s["id"], s["title"], s["kind"]) for s in (data(spaces) or {}).get("scopes", [])]
        check(
            "5 the spaces picker searched for 'eng' lists the Engineering space only",
            spaces.status_code == 200 and offered == [("ENG", "Engineering", "space")],
            offered or spaces.text[:300],
        )
        pages = source(k, base["id"], CONFLUENCE, "spaces", {"spaces": ["ENG"]})
        wiki_first = data(k.post(f"/v1/sources/{pages['id']}/sync"))
        held = items(k, pages["id"])
        deploy = search(k, base["id"], "deploy pipeline")
        check(
            "5b the space's three pages are indexed, and search cites the Deploys page",
            set(held) == {"101", "102", "103"}
            and all(r["status"] == "indexed" for r in held.values())
            and any("pipeline" in p["text"] for p in deploy),
            {"run": wiki_first["counts"], "items": {p: r["status"] for p, r in held.items()},
             "deploy": [(p.get("title"), p["text"][:40]) for p in deploy[:3]]},
        )  # fmt: skip
        before = len(wiki.bodies())
        wiki.edit("101", "<p>Deploy with the release train on Tuesdays.</p>")
        wiki_second = data(k.post(f"/v1/sources/{pages['id']}/sync"))
        bodies = [r.url.path.rsplit("/", 1)[-1] for r in wiki.bodies()[before:]]
        train = search(k, base["id"], "deploy release train")
        check(
            "6 the second Confluence sync fetches only the edited page, and search quotes its new text",
            bodies == ["101"] and wiki_second["counts"].get("upserted") == 1
            and any("release train" in p["text"] for p in train),
            {"bodies": bodies, "counts": wiki_second["counts"], "train": [p["text"][:40] for p in train[:3]]},
        )  # fmt: skip

        # Step 7: an agent given the base cites both systems.
        with agents(kb_url=f"http://127.0.0.1:{KB_PORT}") as api:
            desk = agent(api, [base["id"]])
            claim_cites = cited(api, desk, base["id"], "Within how many days must I claim expenses?")
            deploy_cites = cited(api, desk, base["id"], "How do we deploy with the release train?")
            named = [str(c.get("title") or c.get("url")) for c in claim_cites + deploy_cites]
            check(
                "7 an agent given the base cites the SharePoint file and the Confluence page",
                any("expenses.txt" in str(c.get("url") or "") + str(c.get("title") or "") for c in claim_cites)
                and any("Deploys" in str(c.get("title") or "") for c in deploy_cites),
                named,
            )
    finish()


if __name__ == "__main__":
    main()
