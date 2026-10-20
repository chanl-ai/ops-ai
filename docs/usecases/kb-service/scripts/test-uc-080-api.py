"""uc-080 a banker asks an agent and gets an answer cited by page and section from uploaded PDFs, api layer:
docs/usecases/kb-service/knowledge-cited-answers.md. kb-service and agents-service run on the use case's own ports and
database; agents-service runs the scripted model, so no provider is called."""

from __future__ import annotations

import io
import tempfile
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate
from usecase_harness import KB_PORT, TEAM, agents, check, data, finish, kb, put_in_files, sse

RUN = int(time.time())
OWNER = "maya@northfieldbank.com"
QUESTION = "How many mortgage payments can a borrower who lost their job defer?"


def pdf(title: str, sections: list[tuple[str, str]]) -> bytes:
    styles = getSampleStyleSheet()
    out = io.BytesIO()
    story: list[Flowable] = [Paragraph(title, styles["Title"])]
    for n, (heading, body) in enumerate(sections):
        story += [PageBreak()] if n else []
        story += [Paragraph(heading, styles["Heading1"]), Paragraph(body, styles["BodyText"])]
    SimpleDocTemplate(out, pagesize=A4, title=title).build(story)
    return out.getvalue()


def scanned() -> bytes:
    image = Image.new("RGB", (620, 877), "white")
    ImageDraw.Draw(image).text((50, 100), "LATE PAYMENT FEE 25 DOLLARS", fill="black")
    out = io.BytesIO()
    image.save(out, "PDF", resolution=75.0)
    return out.getvalue()


HARDSHIP = pdf(
    "Mortgage Hardship Policy",
    [
        ("1 Eligibility", "A borrower who lost their job may defer up to three mortgage payments in a year."),
        ("2 Interest", "Deferred interest is capitalised into the loan balance at the end of the deferral."),
    ],
)
RATES = pdf(
    "Rate Sheet", [("1 Fixed rates", "The five-year fixed mortgage rate is 4.89 percent for insured borrowers.")]
)
RATES_V2 = pdf("Rate Sheet", [("1 Fixed rates", "The five-year fixed mortgage rate is now 5.19 percent.")])


def upload(k: Any, source_id: str, name: str, body: bytes) -> dict[str, Any]:
    """Into Files first, then added to the source by id, as the console does."""
    file_id = put_in_files(k.files_url, name, body)
    return data(k.post(f"/v1/sources/{source_id}/files", json={"fileIds": [file_id]}))[0]


def ask(k: Any, kb_id: str, question: str) -> dict[str, Any]:
    return data(k.post(f"/v1/knowledge-bases/{kb_id}/query", json={"question": question}))


def agent(api: Any, name: str, collections: list[str]) -> str:
    made = data(
        api.post("/v1/agents", json={"name": f"{name} {RUN}", "role": "Answers lending questions"}, headers=TEAM)
    )
    saved = data(api.patch(f"/v1/agents/{made['id']}", json={"collections": collections}, headers=TEAM))
    body = {"version": saved["version"], "note": "uc-080"}
    api.post(f"/v1/agents/{made['id']}/publish-requests", json=body, headers=TEAM)
    return str(made["id"])


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uc-080-") as files, kb(Path(files)) as k:
        refused = k.post("/v1/knowledge-bases", json={"name": f"Lending {RUN}"})
        check(
            "a knowledge base without an owner is refused (collection_without_owner)",
            refused.status_code == 400 and refused.json()["error"]["code"] == "collection_without_owner",
            refused.text[:200],
        )
        made = data(k.post("/v1/knowledge-bases", json={"name": f"Lending {RUN}", "owner": OWNER}))
        kb_id = made["id"]
        src = data(
            k.post(
                "/v1/sources",
                json={"type": "file", "name": f"Lending PDFs {RUN}", "collection": "Lending", "kbIds": [kb_id]},
            )
        )
        for name, body in (("hardship.pdf", HARDSHIP), ("rates.pdf", RATES), ("scan.pdf", scanned())):
            upload(k, src["id"], name, body)
        run = data(k.post(f"/v1/sources/{src['id']}/sync"))
        items = {i["path"]: i for i in data(k.get(f"/v1/sources/{src['id']}/items"))["data"]}
        check(
            "sync indexes the two text PDFs with their pages",
            items["hardship.pdf"]["status"] == "indexed"
            and items["hardship.pdf"]["pageCount"] == 2
            and items["rates.pdf"]["status"] == "indexed",
            {k2: (v["status"], v.get("pageCount")) for k2, v in items.items()},
        )
        check(
            "the PDF with no text layer fails with its reason and the rest index",
            run["status"] == "partial" and str(items["scan.pdf"].get("error", "")).startswith("no_text_layer"),
            {"run": run["status"], "scan": items["scan.pdf"].get("error")},
        )

        answer = ask(k, kb_id, QUESTION)
        top = answer["citations"][0] if answer["citations"] else {}
        check(
            "a question cites the hardship policy by page and section",
            top.get("title") == "Mortgage Hardship Policy"
            and top.get("page") == 1
            and "Eligibility" in top.get("section", ""),
            top,
        )
        nothing = ask(k, kb_id, "What will the weather be in Lisbon tomorrow?")
        check(
            "a question nothing answers returns no passage",
            nothing["citations"] == [] and nothing.get("noAnswer"),
            nothing,
        )

        upload(k, src["id"], "rates.pdf", RATES_V2)
        data(k.post(f"/v1/sources/{src['id']}/sync"))
        rates = ask(k, kb_id, "five-year fixed mortgage rate")
        texts = " ".join(c["snippet"] for c in rates["citations"])
        check(
            "after v2 of the rate sheet, only v2 is cited and the old rate is gone",
            {c["version"] for c in rates["citations"]} == {"v2"} and "5.19" in texts and "4.89" not in texts,
            rates["citations"],
        )
        changes = data(k.get("/v1/knowledge-changes", params={"view": "resolved", "kbId": kb_id}))["data"]
        check(
            "the Changes feed shows who replaced the rate sheet, from v1 to v2",
            len(changes) == 1 and (changes[0]["fromVersion"], changes[0]["toVersion"]) == ("v1", "v2"),
            changes,
        )

        with agents(kb_url=f"http://127.0.0.1:{KB_PORT}") as api:
            granted = agent(api, "Lending Helper", [kb_id])
            ungranted = agent(api, "Card Helper", [])
            thread = data(api.post("/chat/threads", json={"agentId": granted, "kbIds": [kb_id]}, headers=TEAM))
            res = api.post(
                f"/chat/threads/{thread['id']}/messages",
                json={"content": QUESTION},
                headers={**TEAM, "Accept": "text/event-stream"},
            )
            events = sse(res.text)
            cited = next((e["citations"] for e in events if e.get("type") == "citations"), [])
            check(
                "the granted agent's chat reply cites the policy with page and section",
                bool(cited) and cited[0].get("page") == 1 and "Eligibility" in cited[0].get("section", ""),
                {"types": [e.get("type") for e in events], "cited": cited},
            )
            check("the thread names the knowledge base", thread.get("kbNames") == [made["name"]], thread)
            other = api.post("/chat/threads", json={"agentId": ungranted, "kbIds": [kb_id]}, headers=TEAM)
            check(
                "an agent not granted the knowledge base cannot open a thread on it",
                other.status_code in (403, 422) and "cannot search" in other.text,
                other.text[:200],
            )
    finish()


if __name__ == "__main__":
    main()
