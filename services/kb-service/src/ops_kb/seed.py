"""The banker demo's two knowledge bases, seeded when a dev kb-service starts (c-072 T006).

Retail products (owned by James, the builder) holds the retail product sheet; Branch operations (owned by Nadia,
Security's approver) holds the branch manual and the fee schedule. Each base has a stable id, which agents-service's
seed names in Advisor's Helper and Branch Policy (`seed/chat_agents.json`), so a rebuilt database has both FAQ agents
answering from their bases with no hand-run script. A base that exists is left as it is: people may have changed it.
Its demo files are uploaded again when the store cannot read them, as after kb-service moved from its own store to
files-service (c-094).
`scripts/seed_demo_knowledge.py` finds these bases by name and reuses them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ops_service_kit.logging import get_logger

from .files import FileMissing, FileNotScanned
from .service import KnowledgeService, Who, source_team

log = get_logger(__name__)
PDFS = Path(__file__).resolve().parents[2] / "seed" / "pdfs"
TENANT = "local"
JAMES, NADIA = "j.richardson@northfieldbank.com", "n.petrov@northfieldbank.com"


@dataclass(frozen=True)
class DemoBase:
    id: str
    name: str
    owner: str
    team: str
    collection: str
    description: str
    # Source name -> (file name, PDF under seed/pdfs).
    files: dict[str, tuple[str, str]]


DEMO = (
    DemoBase(
        "kb_retail_products",
        "Retail products",
        JAMES,
        "team_ops",
        "Retail",
        "Product sheets for the retail accounts advisors sell.",
        {"Retail product sheets": ("retail-product-sheet.pdf", "retail-product-sheet.pdf")},
    ),
    DemoBase(
        "kb_branch_operations",
        "Branch operations",
        NADIA,
        "team_security",
        "Operations",
        "The branch manual and the fee schedule tellers answer from.",
        {
            "Branch operations manual": ("branch-operations-manual.pdf", "branch-operations-manual.pdf"),
            "Fee schedule": ("fee-schedule.pdf", "fee-schedule-v1.pdf"),
        },
    ),
)


async def seed_demo(service: KnowledgeService, tenant: str = TENANT) -> list[str]:
    """Creates each demo base its id does not name yet, with its sources, uploads and a sync; returns the ids made."""
    made: list[str] = []
    for d in DEMO:
        if await service.store.base(tenant, d.id) is not None:
            if await _restore_files(service, tenant, d):
                made.append(d.id)
            continue
        # A demo base someone retired stays retired.
        if await service.store.retired(tenant, [d.id]):
            continue
        # A base of this name under another id was made by hand or by the script before the ids were stable; it is
        # left alone, and the agents naming the stable id find nothing until the database is rebuilt.
        if any(b["name"].lower() == d.name.lower() for b in await service.store.bases(tenant)):
            log.warning("demo_kb_name_taken_not_seeded", name=d.name, id=d.id)
            continue
        # A source of a demo source's name belongs to someone; the seed never uploads into it.
        taken = {s["name"].lower() for s in await service.store.sources(tenant)} & {n.lower() for n in d.files}
        if taken:
            log.warning("demo_kb_source_name_taken_not_seeded", name=d.name, id=d.id, sources=sorted(taken))
            continue
        who = Who(tenant_id=tenant, email=d.owner, team_id=d.team)
        source_ids: list[str] = []
        for source_name, (file_name, pdf) in d.files.items():
            source = await service.create_source(
                who, {"type": "file", "name": source_name, "collection": d.collection, "owner": d.owner}
            )
            await service.upload(
                who, str(source["id"]), (PDFS / pdf).read_bytes(), name=file_name, mime="application/pdf"
            )
            source_ids.append(str(source["id"]))
        await service.create_base(
            who,
            {"id": d.id, "name": d.name, "owner": d.owner, "description": d.description, "sourceIds": source_ids},
        )
        for source_id in source_ids:
            await service.sync(who, source_id)
        made.append(d.id)
    return made


async def _restore_files(service: KnowledgeService, tenant: str, d: DemoBase) -> bool:
    """Uploads a demo source's file again when the store cannot read the files the source holds, dropping the
    unreadable ids, then syncs; True when any source was restored. A source a person renamed is not found and left."""
    who = Who(tenant_id=tenant, email=d.owner, team_id=d.team)
    sources = {s["name"]: s for s in await service.store.sources(tenant)}
    restored = False
    for source_name, (file_name, pdf) in d.files.items():
        source = sources.get(source_name)
        if source is None or source["owner"] != d.owner:
            continue
        missing: set[str] = set()
        for file_id in source["file_ids"]:
            try:
                await service.files.read(tenant, source_team(source), file_id)
            except FileMissing:
                missing.add(file_id)
            except FileNotScanned:
                continue
        if not missing and source["file_ids"]:
            continue
        log.info("demo_kb_files_restored", base=d.id, source=source_name, unreadable=len(missing))
        await service.store.drop_files(tenant, str(source["id"]), missing)
        await service.upload(who, str(source["id"]), (PDFS / pdf).read_bytes(), name=file_name, mime="application/pdf")
        await service.sync(who, str(source["id"]))
        restored = True
    return restored
