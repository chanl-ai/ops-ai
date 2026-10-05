import type { Item, ItemDetail, Chunk } from "@/lib/types/knowledge"
import { seeded } from "./time"

const paragraphs = [
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

export function itemDetail(item: Item): ItemDetail {
  const rnd = seeded(item.id.split("").reduce((n, c) => n + c.charCodeAt(0), 0))
  const isTable = item.mimeType.includes("spreadsheet") || item.mimeType === "text/csv"
  const n = Math.max(item.chunkCount, 3)
  const chunks: Chunk[] = []
  const sections: string[] = []
  for (let i = 0; i < n; i++) {
    const h = headings[i % headings.length]
    const text = isTable
      ? `Product: ${["Small business term loan", "Personal loan", "Line of credit", "Mortgage"][i % 4]} | Band: ${["<= $250k", "> $250k", "any"][i % 3]} | Rate: ${(3 + rnd() * 6).toFixed(2)}% | Fee: ${(rnd() * 2).toFixed(2)}% | Min: $${Math.round(rnd() * 2000)}`
      : `${paragraphs[i % paragraphs.length]} ${paragraphs[(i + 3) % paragraphs.length]}`
    chunks.push({
      index: i,
      tokens: Math.floor(180 + rnd() * 400),
      location: isTable ? `Sheet 1 · row ${i + 2}` : item.pageCount ? `p.${1 + Math.floor((i / n) * item.pageCount)} · ${h}` : `${h} · lines ${i * 14 + 1}–${i * 14 + 13}`,
      kind: isTable ? "row" : item.sourceId === "src_branch_faq" ? (i % 2 === 0 ? "question" : "answer") : i === 0 ? "summary" : "content",
      text,
    })
    if (!isTable && i < headings.length) sections.push(`## ${h}\n\n${text}`)
  }
  const content = isTable
    ? `# ${item.title}\n\n| Product | Band | Rate | Fee | Min |\n|---|---|---|---|---|\n${chunks.slice(0, 12).map((c) => "| " + c.text.split(" | ").map((kv) => kv.split(": ")[1]).join(" | ") + " |").join("\n")}`
    : `# ${item.title}\n\nOwner: ${item.owner} · Version ${item.version} · Effective ${item.effectiveDate}${item.supersedes ? ` · Supersedes ${item.supersedes}` : ""}\n\n${sections.join("\n\n")}`
  const revCount = 1 + Math.floor(rnd() * 4)
  const revisions = Array.from({ length: revCount }, (_, i) => ({
    n: revCount - i,
    author: i === 0 ? (item.sourceId.includes("sharepoint") || item.sourceId.includes("confluence") || item.sourceId.includes("github") || item.sourceId.includes("crawl") || item.sourceId.includes("notion") ? "sync" : item.owner) : "sync",
    date: new Date(new Date(item.modifiedAt).getTime() - i * 40 * 86400_000).toISOString(),
    sizeDelta: i === revCount - 1 ? item.sizeBytes : Math.floor((rnd() - 0.4) * 20000),
    note: i === 0 ? "Latest" : undefined,
  }))
  return { content, chunks, revisions }
}
