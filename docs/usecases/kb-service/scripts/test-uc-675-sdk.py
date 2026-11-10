# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-675 a website source keeps a knowledge base current, sdk layer: docs/usecases/kb-service/a-website-source-keeps-
a-knowledge.md, story S7. A developer drives the knowledge routes this release added through the Python SDK in
sdk/python and the TypeScript SDK in sdk/typescript: the kinds a source can be, a source's schedule, the AI steps'
estimate and approval, FAQ drafts decided in the Changes queue, and a search that says which lanes ran. Own kb-service,
files-service and documents-service, models-service on its scripted aliases and a fake OpenAI; no provider is called."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate
from usecase_harness import ROOT, check, data, fake_openai, finish, kb, models, put_in_files, until

sys.path.insert(0, str(ROOT / "sdk" / "python" / "src"))
from ops_ai import OpsAI

OWNER = "maya@harborpine.example"
RULES = {
    "rules": [
        {
            "when": r"question-and-answer pairs[\s\S]*Section: (?P<section>[^\n]+)[\s\S]*Section text:\n(?P<first>[^.\n]+\.)",
            "text": '{{"pairs": [{{"question": "quokka {section}?", "answer": "{first}", "quote": "{first}"}}]}}',
        }
    ]
}
TS_CHECK = """
import { OpsAI } from '%(sdk)s';
const ops = new OpsAI({ baseUrl: 'http://127.0.0.1', services: { kb: '%(kb)s' }, team: 'team_ops' });
const kinds = await ops.raw.kb.sources_source_kinds({});
const found = await ops.raw.kb.knowledge_bases_query_knowledge_base({ path: { kb_id: '%(base)s' }, body: { question: 'payment holiday' } });
const drafts = await ops.raw.kb.changes_list_changes({ query: { view: 'resolved' } });
console.log(JSON.stringify({ kinds: kinds.map((k) => k.kind), lanes: found.lanes, decided: drafts.data.map((d) => d.status) }));
"""


def pdf(title: str, sections: list[tuple[str, str]]) -> bytes:
    styles = getSampleStyleSheet()
    out = io.BytesIO()
    story: list[Flowable] = [Paragraph(title, styles["Title"])]
    for n, (heading, body) in enumerate(sections):
        story += [PageBreak()] if n else []
        story += [Paragraph(heading, styles["Heading1"]), Paragraph(body, styles["BodyText"])]
    SimpleDocTemplate(out, pagesize=A4, title=title).build(story)
    return out.getvalue()


HELP = pdf(
    "Loan help",
    [
        (
            "Payment holidays",
            "A payment holiday pauses your loan payments for up to three months. Interest still builds.",
        ),
        ("Early repayment", "You can repay all or part of your loan at any time. A charge may apply."),
    ],
)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uc-675-sdk-") as tmp:
        rules = Path(tmp) / "fake-openai"
        rules.mkdir()
        (rules / "script.json").write_text(json.dumps(RULES))
        with (
            fake_openai(rules) as fake,
            models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
            kb(Path(tmp) / "files", env={"OPS_MODELS_URL": models_url, "OPS_MODELS_KEY": "mk_dev_kb"}) as k,
        ):
            ops = OpsAI(base_url="http://127.0.0.1", services={"kb": str(k.base_url).rstrip("/")}, team="team_ops")
            kb_api: Any = ops.raw.kb
            kinds = kb_api.sources_source_kinds()
            check(
                "15 the Python SDK lists the kinds a source can be, each with the defaults a new one starts with",
                kinds[0]["kind"] == "file" and kinds[0]["defaults"]["schedule"] == {"kind": "manual"},
                kinds,
            )
            base = data(k.post("/v1/knowledge-bases", json={"name": "Loans", "owner": OWNER}))
            fid = put_in_files(k.files_url, "help.pdf", HELP)
            body = {"type": "file", "name": "Loan help", "fileIds": [fid], "kbIds": [base["id"]]}
            src = data(k.post("/v1/sources", json=body))
            data(k.post(f"/v1/sources/{src['id']}/sync"))
            saved = kb_api.sources_update_source(
                src["id"],
                {
                    "schedule": {"kind": "weekly", "day": "mon", "time": "03:00", "tz": "Europe/London"},
                    "ingest": {"strategies": ["structure", "context_headers", "faq_pairs"], "model": "default"},
                },
            )
            estimate = kb_api.sources_estimate_ai_steps(src["id"])
            check(
                "16 the SDK saves a weekly schedule and an AI step, and reads its estimate with its basis",
                saved["schedule"]["kind"] == "weekly"
                and saved.get("nextSyncAt")
                and estimate["calls"] > 0
                and estimate["basis"],
                {"schedule": saved["schedule"], "estimate": estimate},
            )
            kb_api.sources_decide_ai_steps(src["id"], {"decision": "approve"})
            drafts = (
                until(
                    lambda: [
                        d for d in kb_api.changes_list_changes(view="open")["data"] if d["origin"] == "generated_faq"
                    ],
                    timeout=90,
                )
                or []
            )
            edited = (
                kb_api.changes_edit_change(
                    drafts[0]["id"],
                    {"question": "quokka how long is a payment holiday?", "answer": drafts[0]["faq"]["answer"]},
                )
                if drafts
                else {}
            )
            decided = kb_api.changes_decide_changes({"ids": [d["id"] for d in drafts], "decision": "approve"})
            check(
                "17 the SDK approves the AI steps, edits a draft and approves the drafts in one call",
                bool(drafts) and edited.get("status") == "pending" and {d["status"] for d in decided} == {"approved"},
                {"drafts": len(drafts), "decided": [d["status"] for d in decided]},
            )
            found = kb_api.knowledge_bases_query_knowledge_base(
                base["id"], {"question": "quokka how long is a payment holiday"}
            )
            check(
                "18 the SDK's search says which lanes ran and returns the approved pair's passage",
                found["lanes"]["ran"] == ["keyword", "meaning"]
                and any(p["matched"] == "faq" for p in found["passages"]),
                {"lanes": found["lanes"], "matched": [p["matched"] for p in found["passages"]]},
            )
            check("19 the SDK lists a source's tombstones", kb_api.sources_list_tombstones(src["id"]) == [], "")

            sdk = ROOT / "sdk" / "typescript"
            subprocess.run(["npx", "tsc", "-p", "tsconfig.json"], cwd=sdk, check=True, capture_output=True)
            script = TS_CHECK % {
                "sdk": (sdk / "dist" / "index.js").as_posix(),
                "kb": str(k.base_url).rstrip("/"),
                "base": base["id"],
            }
            ran = subprocess.run(
                ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=False
            )
            seen = json.loads(ran.stdout or "{}") if ran.returncode == 0 else {}
            check(
                "20 the TypeScript SDK reads the source kinds, a search's lanes and the decided drafts",
                seen.get("kinds", [None])[0] == "file"
                and (seen.get("lanes") or {}).get("ran") == ["keyword", "meaning"]
                and "approved" in seen.get("decided", []),
                seen or ran.stderr[-600:],
            )
    finish()


main()
