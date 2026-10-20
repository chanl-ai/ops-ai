"""Seeds the banker demo's knowledge (c-058 T001): renders the markdown under seed/ into text PDFs (one section per
page, so citations carry a page and a section), creates the two knowledge bases with their owners through kb-service's
API, puts the PDFs in Files (files-service), adds them to their sources by id and syncs, and runs the demo questions
through K12, printing each one's best score against the retrieval floor.

    uv run python scripts/seed_demo_knowledge.py --kb http://127.0.0.1:8740 --files http://127.0.0.1:8750 \
        --platform http://127.0.0.1:8710
    uv run python scripts/seed_demo_knowledge.py ... --agents http://127.0.0.1:8700   # also wires ag_advisor, ag_policy
    uv run python scripts/seed_demo_knowledge.py ... --as <email>                      # who wires them (default James)
    uv run python scripts/seed_demo_knowledge.py ... --fees v2                        # replaces the fee schedule
    uv run python scripts/seed_demo_knowledge.py --kb <url> --token <bearer>           # a harness's own stack

A harness imports `seed_from(kb_url, files_url, token=...)` (or `dev=True`) and gets the bases and the K12 scores back.

Retail products is owned by the builder (James), Branch operations by Security's approver (Nadia). Each base is
written by a builder or admin of its owning team, which kb-service requires (c-115): James for Retail products, and for
Branch operations Security's admin (Sam), since an approver may own a base but not change it. Rendering alone:
`--render-only`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate

SEED = Path(__file__).resolve().parents[1] / "seed"
PDFS = SEED / "pdfs"
JAMES, NADIA = "j.richardson@northfieldbank.com", "n.petrov@northfieldbank.com"
# Writes Nadia's base: an admin of team_security, the team that owns it.
SAM = "s.adeyemi@northfieldbank.com"
DOCUMENTS = {
    "retail-product-sheet": "Retail Product Sheet",
    "branch-operations-manual": "Branch Operations Manual",
    "fee-schedule-v1": "Fee Schedule",
    "fee-schedule-v2": "Fee Schedule",
}
# The demo questions, the base each is asked of, and whether the base covers it. The first is a bank question (the
# advisor's tools answer it), so no base covers it either.
QUESTIONS: list[tuple[str, str, bool]] = [
    ("What does Priya Natarajan have with us?", "retail", False),
    ("Compare Savings Plus and Money Market for her", "retail", True),
    # What a banker asks the advisor about the products in the demo: the rate, the minimum balance and the fee.
    ("What is the interest rate on Savings Plus, and how does it compare with Money Market?", "retail", True),
    ("What is the minimum balance to open Money Market?", "retail", True),
    ("What is the monthly fee on Everyday Chequing?", "retail", True),
    ("What is the fee for an outgoing wire transfer?", "branch", True),
    ("What is the daily ATM withdrawal limit?", "branch", True),
    ("How do I place a stop payment on a cheque?", "branch", True),
    ("What is the prepayment penalty on a fixed-rate mortgage?", "branch", False),
]
FLOOR = 0.5
# Puts a PDF in Files as the person `kb` is signed in as and returns its file id: (kb client, file name, bytes).
Store = Callable[[httpx.AsyncClient, str, bytes], Awaitable[str]]


def files_store(files_url: str) -> Store:
    """Files over HTTP, the upload the console makes: a ticket, the bytes, then complete. Sent with the kb client's
    headers, so the file belongs to the team the source is written in."""

    async def store(kb: httpx.AsyncClient, name: str, body: bytes) -> str:
        who = {k: v for k, v in kb.headers.items() if k.lower() in ("authorization", "x-dev-user", "x-team-id")}
        async with httpx.AsyncClient(base_url=files_url, headers=who, timeout=120) as files:
            ticket = data(
                await files.post(
                    "/v1/files/uploads",
                    json={
                        "name": name,
                        "size": len(body),
                        "mime": "application/pdf",
                        "purpose": "knowledge_source",
                        "digest": hashlib.sha256(body).hexdigest(),
                    },
                ),
                201,
            )
            put = await files.put(ticket["uploadUrl"], headers=ticket.get("headers") or {}, content=body)
            if put.status_code >= 300:
                raise SystemExit(f"PUT {name} -> {put.status_code} {put.text[:300]}")
            done = data(await files.post(f"/v1/files/uploads/{ticket['fileId']}/complete"))
            return str(done["file"]["id"])

    return store


def render(markdown: str, title: str) -> bytes:
    """`#` is the document title, each `##` starts a page with its heading, paragraphs are blank-line separated."""
    styles = getSampleStyleSheet()
    story: list[Flowable] = [Paragraph(title, styles["Title"])]
    sections = 0
    for block in markdown.split("\n\n"):
        text = " ".join(line.strip() for line in block.strip().splitlines())
        if not text or text.startswith("# "):
            continue
        if text.startswith("## "):
            if sections:
                story.append(PageBreak())
            sections += 1
            story.append(Paragraph(text[3:], styles["Heading1"]))
        else:
            story.append(Paragraph(text, styles["BodyText"]))
    out = io.BytesIO()
    # invariant: fixed creation date and object ids, so a re-render of unchanged markdown is byte-identical and the
    # committed PDFs do not show as modified after every seed run.
    SimpleDocTemplate(out, pagesize=A4, title=title, invariant=1).build(story)
    return out.getvalue()


def render_all() -> dict[str, Path]:
    PDFS.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for stem, title in DOCUMENTS.items():
        target = PDFS / f"{stem}.pdf"
        target.write_bytes(render((SEED / f"{stem}.md").read_text(), title))
        written[stem] = target
    return written


def data(r: httpx.Response, status: int | None = None) -> Any:
    body = r.json()
    if (status is not None and r.status_code != status) or not body.get("success"):
        raise SystemExit(f"{r.request.method} {r.request.url.path} -> {r.status_code} {r.text[:300]}")
    return body["data"]


@dataclass
class Seeded:
    retail_kb: str
    branch_kb: str
    retail_source: str
    branch_source: str
    fee_source: str


async def seed_base(
    kb: httpx.AsyncClient,
    store: Store,
    *,
    name: str,
    owner: str,
    collection: str,
    files: dict[str, dict[str, bytes]],
    description: str,
) -> tuple[str, list[str]]:
    """One file source per document set, the base over them, then the uploads and a sync of each source, so the
    base's last refresh is the sync. A base of this name and owner, and a source of each name, are reused, so a
    second run adds nothing (uploads deduplicate, the sync reports unchanged). Returns the base id and the source
    ids, in `files` order."""
    existing = {s["name"]: s for s in data(await kb.get("/v1/sources", params={"pageSize": 100}))["data"]}
    sources: list[dict[str, Any]] = []
    for source_name in files:
        src = existing.get(source_name) or data(
            await kb.post(
                "/v1/sources",
                json={"type": "file", "name": source_name, "collection": collection, "owner": owner},
            ),
            201,
        )
        sources.append(src)
    bases = data(await kb.get("/v1/knowledge-bases", params={"pageSize": 100, "search": name}))["data"]
    base = next((b for b in bases if b["name"] == name and b["owner"] == owner), None) or data(
        await kb.post(
            "/v1/knowledge-bases",
            json={
                "name": name,
                "owner": owner,
                "description": description,
                "sourceIds": [str(s["id"]) for s in sources],
            },
        ),
        201,
    )
    for src, (source_name, pdfs) in zip(sources, files.items(), strict=True):
        ids = [await store(kb, file_name, body) for file_name, body in pdfs.items()]
        data(await kb.post(f"/v1/sources/{src['id']}/files", json={"fileIds": ids}))
        run = data(await kb.post(f"/v1/sources/{src['id']}/sync"))
        if run["status"] not in ("success", "unchanged"):
            raise SystemExit(f"sync of {source_name} ended {run['status']}: {run.get('errors')}")
    return str(base["id"]), [str(s["id"]) for s in sources]


async def seed(kb_for: dict[str, httpx.AsyncClient], store: Store, pdfs: dict[str, Path]) -> Seeded:
    """`kb_for` maps each base owner's email to the kb-service client that writes that base: one signed in as a
    builder or admin of the owning team (James for his own base, Sam for Nadia's)."""
    retail, retail_sources = await seed_base(
        kb_for[JAMES],
        store,
        name="Retail products",
        owner=JAMES,
        collection="Retail",
        files={"Retail product sheets": {"retail-product-sheet.pdf": pdfs["retail-product-sheet"].read_bytes()}},
        description="Product sheets for the retail accounts advisors sell.",
    )
    branch, branch_sources = await seed_base(
        kb_for[NADIA],
        store,
        name="Branch operations",
        owner=NADIA,
        collection="Operations",
        files={
            "Branch operations manual": {"branch-operations-manual.pdf": pdfs["branch-operations-manual"].read_bytes()},
            "Fee schedule": {"fee-schedule.pdf": pdfs["fee-schedule-v1"].read_bytes()},
        },
        description="The branch manual and the fee schedule tellers answer from.",
    )
    return Seeded(retail, branch, retail_sources[0], branch_sources[0], branch_sources[1])


async def replace_fee_schedule(kb: httpx.AsyncClient, store: Store, seeded: Seeded, pdf: bytes) -> dict[str, Any]:
    """Version 2 of the fee schedule under the same file name: the sync replaces v1 and the Changes page shows it."""
    file_id = await store(kb, "fee-schedule.pdf", pdf)
    data(await kb.post(f"/v1/sources/{seeded.fee_source}/files", json={"fileIds": [file_id]}))
    return data(await kb.post(f"/v1/sources/{seeded.fee_source}/sync"))


async def ask(kb: httpx.AsyncClient, seeded: Seeded) -> list[dict[str, Any]]:
    """Every demo question through K12 on its base: the best passage's score (None when nothing passes the floor)."""
    out: list[dict[str, Any]] = []
    for question, base, covered in QUESTIONS:
        kb_id = seeded.retail_kb if base == "retail" else seeded.branch_kb
        answer = data(await kb.post(f"/v1/knowledge-bases/{kb_id}/query", json={"question": question}))
        chunks: list[dict[str, Any]] = list(answer.get("chunks") or [])
        best = max((float(c["score"]) for c in chunks), default=None)
        cite = answer["citations"][0] if answer.get("citations") else None
        out.append(
            {
                "question": question,
                "base": base,
                "covered": covered,
                "score": best,
                "cites": f"{cite['title']} p. {cite.get('page')}" if cite else None,
                "ok": (best is not None and best >= FLOOR) if covered else best is None,
            }
        )
    return out


async def wire_agents(agents: httpx.AsyncClient, seeded: Seeded) -> None:
    """The seeded agents name their bases by id: ag_advisor the Retail products base, ag_policy Branch operations."""
    # search_customers finds a customer an advisor names without an id ("What does Priya Natarajan have with us?").
    reads = ["search_customers", "get_customer", "list_accounts", "list_transactions"]
    # The seeded agents belong to the operations team (agent_registry.SEED_TEAM); the caller acts in it.
    team = {"X-Team-Id": "team_ops"}
    # The advisor may also start the seeded v2 customer summary workflow (c-062), found through search_tools.
    advisor = [*reads, "workflow:customer_summary"]
    for agent_id, kb_ids, tools in (("ag_advisor", [seeded.retail_kb], advisor), ("ag_policy", [seeded.branch_kb], [])):
        body: dict[str, Any] = {"collections": kb_ids, "toolIds": tools}
        r = await agents.patch(f"/v1/agents/{agent_id}", json=body, headers=team)
        patched = data(r)
        r = await agents.post(
            f"/v1/agents/{agent_id}/publish-requests",
            json={"version": patched["version"], "note": "c-058 knowledge bases"},
            headers=team,
        )
        print(f"{agent_id}: collections {kb_ids}, publish request {r.status_code}")


def owner_headers(*, token: str | None = None, dev: bool = False) -> dict[str, dict[str, str]]:
    """Headers per owner for a stack that is not signed in through platform-service: one bearer `token` for both
    (the bases then belong to that token's person), or dev's `X-Dev-User` naming each owner."""
    if token:
        return {who: {"Authorization": f"Bearer {token}"} for who in (JAMES, NADIA)}
    if dev:
        # Each base's team, as kb-service's dev-start seed makes it, so its files go into that team's Files.
        return {
            JAMES: {"X-Dev-User": JAMES, "X-Team-Id": "team_ops"},
            NADIA: {"X-Dev-User": NADIA, "X-Team-Id": "team_security"},
        }
    raise ValueError("owner_headers needs a token or dev=True")


async def seed_from(
    kb_url: str,
    files_url: str,
    *,
    headers: dict[str, dict[str, str]] | None = None,
    token: str | None = None,
    dev: bool = False,
) -> tuple[Seeded, list[dict[str, Any]]]:
    """For a harness: seeds the kb-service at `kb_url` and returns the bases with the K12 scores. `headers` is per
    owner (JAMES, NADIA); else `token` or `dev` builds them (owner_headers)."""
    pdfs = render_all()
    by_owner = headers or owner_headers(token=token, dev=dev)
    async with (
        httpx.AsyncClient(base_url=kb_url, headers=by_owner[JAMES], timeout=120) as james,
        httpx.AsyncClient(base_url=kb_url, headers=by_owner[NADIA], timeout=120) as nadia,
    ):
        seeded = await seed({JAMES: james, NADIA: nadia}, files_store(files_url), pdfs)
        return seeded, await ask(james, seeded)


def sign_in(platform: str, email: str, password: str) -> dict[str, str]:
    r = httpx.post(f"{platform}/v1/auth/sign-in", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"sign-in as {email} failed: {r.status_code} {r.text[:200]}")
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kb", default=f"http://127.0.0.1:{os.environ.get('OPS_KB_PORT', '8740')}")
    ap.add_argument("--files", default=f"http://127.0.0.1:{os.environ.get('OPS_FILES_PORT', '8750')}")
    ap.add_argument("--platform", default=f"http://127.0.0.1:{os.environ.get('OPS_PLATFORM_PORT', '8710')}")
    ap.add_argument("--agents", help="agents-service base URL; set to wire ag_advisor and ag_policy to the bases")
    ap.add_argument("--as", dest="email", default=JAMES, help="who wires the agents (platform sign-in); default James")
    ap.add_argument("--dev", action="store_true", help="dev auth: X-Dev-User headers instead of platform sign-in")
    ap.add_argument("--token", help="one platform token for both owners (a harness's), instead of signing in")
    ap.add_argument("--password", default=os.environ.get("OPS_PLATFORM_DEMO_PASSWORD", "northfield-demo"))
    ap.add_argument("--fees", choices=["v1", "v2"], default="v1", help="v2 replaces the fee schedule after seeding")
    ap.add_argument("--render-only", action="store_true")
    args = ap.parse_args()

    pdfs = render_all()
    print("rendered " + ", ".join(p.name for p in pdfs.values()))
    if args.render_only:
        return
    if args.token or args.dev:
        headers = owner_headers(token=args.token, dev=args.dev)
    else:
        # Each base's team, as the dev path names it: a seeded person belongs to every team, so kb-service asks which.
        writers = {JAMES: (JAMES, "team_ops"), NADIA: (SAM, "team_security")}
        headers = {
            owner: sign_in(args.platform, who, args.password) | {"X-Team-Id": team}
            for owner, (who, team) in writers.items()
        }
    asyncio.run(run(args, headers, pdfs))


async def run(args: argparse.Namespace, headers: dict[str, dict[str, str]], pdfs: dict[str, Path]) -> None:
    async with (
        httpx.AsyncClient(base_url=args.kb, headers=headers[JAMES], timeout=120) as james,
        httpx.AsyncClient(base_url=args.kb, headers=headers[NADIA], timeout=120) as nadia,
    ):
        store = files_store(args.files)
        seeded = await seed({JAMES: james, NADIA: nadia}, store, pdfs)
        print(
            f"Retail products {seeded.retail_kb} (owner {JAMES}); Branch operations {seeded.branch_kb} (owner {NADIA})"
        )
        if args.fees == "v2":
            synced = await replace_fee_schedule(nadia, store, seeded, pdfs["fee-schedule-v2"].read_bytes())
            print(f"fee schedule v2: sync {synced['status']} {synced['counts']}")
        for row in await ask(james, seeded):
            mark = "ok" if row["ok"] else "BELOW FLOOR" if row["covered"] else "UNEXPECTED PASSAGE"
            print(f"  {mark:>18}  score={row['score']}  cites={row['cites']}  {row['question']}")
        if args.agents:
            who = headers.get(args.email) or (
                {"X-Dev-User": args.email} if args.dev else sign_in(args.platform, args.email, args.password)
            )
            async with httpx.AsyncClient(base_url=args.agents, headers=who, timeout=60) as agents:
                await wire_agents(agents, seeded)


if __name__ == "__main__":
    main()
