import type { Chunk, Item, ItemDetail } from "@/lib/types/knowledge"

import { splitDocument } from "./ingest"
import type { IndexSnapshot } from "./retrieve"
import { docByKey, FEATURED } from "./seed-documents"
import { seeded } from "./time"

/** Body text for documents without a seeded body; search reads one of these per document. */
export const GENERIC_PARAGRAPHS = [
  "This document applies to all employees, contractors and directors of the bank. Where local regulation sets a higher standard, the higher standard applies.",
  "Cases are opened in the case system within one business day of the alert. Analysts record the decision and the evidence relied on before closing the case.",
  "A customer qualifies when the identity checks are complete and the risk rating is current. Ratings are refreshed at the interval set by the customer's risk tier.",
  "Amounts are assessed on the transaction value at the time of the request and are not adjusted for later changes. Fees and charges are excluded.",
  "Exceptions require written approval from the head of the function and are recorded in the exceptions register with the reason and an expiry date.",
  "This document supersedes the previous version in full. Earlier versions are retained for audit only and must not be used for new decisions.",
  "Questions about interpretation go to the document owner named in the header. Disagreements follow the escalation procedure.",
  "The document is reviewed annually, or earlier when regulation changes. The review-by date is shown in the document properties.",
]

const headings = ["1. Purpose", "2. Scope", "3. Applicability", "4. Requirements", "5. Procedure", "6. Exceptions", "7. Related documents", "8. Review"]

/** Content, chunks and revisions; chunks come from the settings the source was last indexed with. */
export function itemDetail(item: Item, snap?: IndexSnapshot): Omit<ItemDetail, "versions"> {
  const rnd = seeded(item.id.split("").reduce((n, c) => n + c.charCodeAt(0), 0))
  const docKey = FEATURED[item.id]
  const doc = docKey ? docByKey(docKey) : undefined
  let chunks: Chunk[]
  let content: string
  const header = `Owner: ${item.owner} · Version ${item.version} · Effective ${item.effectiveDate}${item.supersedes ? ` · Supersedes ${item.supersedes}` : ""}`
  if (doc && snap) {
    const res = splitDocument(doc, snap.ingest, snap.parsing, {}, snap.aiAllowed)
    chunks = res.chunks.map((c) => ({
      index: c.index,
      tokens: c.tokens,
      location: c.sectionPath.join(" › "),
      kind: c.kind === "row" ? "row" : "content",
      text: [c.text, ...(c.questions?.length ? [`Indexed questions: ${c.questions.join(" · ")}`] : []), ...(c.children?.length ? [`Indexed as ${c.children.length} child chunks`] : [])].join("\n"),
    }))
    const table = doc.table ? `\n\n| ${doc.table.columns.join(" | ")} |\n${doc.table.rows.map((r) => `| ${r.join(" | ")} |`).join("\n")}` : ""
    content = `# ${item.title}\n\n${header}\n\n${doc.sections.map((s) => `## ${s.heading}\n\n${s.body}`).join("\n\n")}${table}`
  } else {
    const isTable = item.mimeType.includes("spreadsheet") || item.mimeType === "text/csv"
    const n = Math.max(item.chunkCount, 1)
    chunks = []
    const sections: string[] = []
    for (let i = 0; i < n; i++) {
      const h = headings[i % headings.length]
      const text = isTable
        ? `Product: ${["Small business term loan", "Personal loan", "Line of credit", "Mortgage"][i % 4]} | Band: ${["<= $250k", "> $250k", "any"][i % 3]} | Rate: ${(3 + rnd() * 6).toFixed(2)}% | Fee: ${(rnd() * 2).toFixed(2)}% | Min: $${Math.round(rnd() * 2000)}`
        : `${GENERIC_PARAGRAPHS[i % GENERIC_PARAGRAPHS.length]} ${GENERIC_PARAGRAPHS[(i + 3) % GENERIC_PARAGRAPHS.length]}`
      chunks.push({
        index: i,
        tokens: Math.floor(180 + rnd() * 330),
        location: isTable ? `Sheet 1 · row ${i + 2}` : item.pageCount ? `p.${1 + Math.floor((i / n) * item.pageCount)} · ${h}` : `${h} · lines ${i * 14 + 1}–${i * 14 + 13}`,
        kind: isTable ? "row" : "content",
        text,
      })
      if (!isTable && i < headings.length) sections.push(`## ${h}\n\n${text}`)
    }
    content = isTable
      ? `# ${item.title}\n\n| Product | Band | Rate | Fee | Min |\n|---|---|---|---|---|\n${chunks.slice(0, 12).map((c) => "| " + c.text.split(" | ").map((kv) => kv.split(": ")[1]).join(" | ") + " |").join("\n")}`
      : `# ${item.title}\n\n${header}\n\n${sections.join("\n\n")}`
  }
  // Held items are not indexed, so they have no chunks to show.
  if (item.status === "held") chunks = []
  const revCount = 1 + Math.floor(rnd() * 4)
  const synced = /sharepoint|confluence|github|crawl|notion/.test(item.sourceId)
  const revisions = Array.from({ length: revCount }, (_, i) => ({
    n: revCount - i,
    author: i === 0 && !synced ? item.owner : "sync",
    date: new Date(new Date(item.modifiedAt).getTime() - i * 40 * 86400_000).toISOString(),
    sizeDelta: i === revCount - 1 ? item.sizeBytes : Math.floor((rnd() - 0.4) * 20000),
    note: i === 0 ? "Latest" : undefined,
  }))
  return { content, chunks, revisions }
}
