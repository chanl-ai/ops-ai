import type { ErrorClass, Item, Source, SyncRun } from "@/lib/types/knowledge"
import type { IngestSettings, IngestStrategy, TableColumn } from "@/lib/types/knowledge-ingest"
import { DEFAULT_INGEST_MODEL, digestOf, docText, familyOf } from "./ingest"
import { docByKey, FEATURED } from "./seed-documents"
import { ago, daysAgo, inHours, inDays, seeded } from "./time"

const defaultParsing = { ocr: false, tables: true, vision: false }

const RATE_COLUMNS: TableColumn[] = [
  { name: "Product", role: "searchable", key: true },
  { name: "Band", role: "searchable" },
  { name: "Origination fee", role: "metadata" },
  { name: "Minimum", role: "metadata" },
  { name: "Maximum", role: "metadata" },
  { name: "Secured", role: "searchable" },
  { name: "Effective", role: "metadata" },
  { name: "Notes", role: "ignored" },
]

/** Ingestion settings; AI steps listed in `approved` start approved by the knowledge owner. */
const ingest = (preset: IngestSettings["preset"], strategies: IngestStrategy[], extra: Partial<IngestSettings> = {}, approved: string[] = []): IngestSettings => ({
  preset,
  strategies,
  size: 512,
  overlap: 50,
  childSize: 40,
  questionsPerSection: 2,
  columns: [],
  model: DEFAULT_INGEST_MODEL,
  approval: { status: approved.length ? "approved" : "not_needed", approvedSteps: approved, decidedBy: approved.length ? "Knowledge owner" : undefined, decidedAt: approved.length ? daysAgo(20) : undefined },
  ...extra,
})

export const sources: Source[] = [
  {
    id: "src_hr_sharepoint",
    type: "sharepoint",
    name: "AML & KYC procedures",
    connectionId: "int_sharepoint",
    connectionLabel: "northfield.sharepoint.com (app-only)",
    scopeSummary: "Site: Financial Crime Operations · Documents/Policies, Documents/Forms",
    config: { site: "Financial Crime Operations", libraries: ["Documents/Policies", "Documents/Forms"], includeOffice: true, includePdf: true, auth: "app-only" },
    parsing: { ...defaultParsing, ocr: true },
    ingest: ingest("policy_manual", ["structure", "context_headers", "parent_child"]),
    rules: [{ id: "r1", kind: "exclude", field: "path", value: "**/Archive/**" }],
    metadataMapping: [
      { key: "department", from: "field:Dept" },
      { key: "locale", from: "static:en" },
      { key: "policy_owner", from: "field:Owner" },
    ],
    tags: ["procedure", "aml"],
    titleFrom: "source",
    permissions: { mode: "inherit" },
    schedule: { kind: "daily", time: "02:00" },
    deletedAtSource: "remove",
    staleAfterDays: 90,
    notifyOnFailure: true,
    sensitivity: "internal",
    collection: "Fraud",
    owner: "Financial Crime Ops",
    status: "active",
    itemsIndexed: 787,
    itemsFailed: 3,
    itemsPending: 0,
    lastSyncAt: ago(0.2),
    lastRunStatus: "partial",
    lastRunDurationSec: 412,
    nextSyncAt: inHours(12),
    cursor: "delta:MzslMjM7MTsz",
    usedByKbIds: ["kb_people", "kb_all"],
    createdAt: daysAgo(180),
  },
  {
    id: "src_eng_confluence",
    type: "confluence",
    name: "Wire fraud playbook",
    connectionId: "int_confluence",
    connectionLabel: "northfield.atlassian.net",
    scopeSummary: "Spaces: FRAUD, PAY, OPS · attachments included",
    config: { site: "northfield.atlassian.net", spaces: ["FRAUD", "PAY", "OPS"], includeAttachments: true },
    parsing: defaultParsing,
    ingest: ingest("custom", ["structure", "context_headers"]),
    rules: [{ id: "r2", kind: "exclude", field: "title", value: "Meeting notes" }],
    metadataMapping: [
      { key: "space", from: "field:Space" },
      { key: "team", from: "field:Label" },
    ],
    tags: ["fraud", "playbook"],
    titleFrom: "source",
    permissions: { mode: "inherit" },
    schedule: { kind: "weekly", day: "Mon", time: "03:00" },
    deletedAtSource: "remove",
    staleAfterDays: 120,
    notifyOnFailure: true,
    sensitivity: "internal",
    collection: "Compliance",
    owner: "Fraud Strategy",
    status: "revoked",
    itemsIndexed: 380,
    itemsFailed: 0,
    itemsPending: 0,
    lastSyncAt: ago(9),
    lastRunStatus: "failed",
    lastRunDurationSec: 4,
    nextSyncAt: inDays(4),
    cursor: "modified-since:2026-09-22T03:00:00Z",
    usedByKbIds: ["kb_eng", "kb_all"],
    createdAt: daysAgo(150),
  },
  {
    id: "src_github_docs",
    type: "github",
    name: "Model risk documentation",
    connectionId: "int_github",
    connectionLabel: "GitHub app · northfield-bank",
    scopeSummary: "northfield-bank/model-risk-docs · main · docs/**, **/*.md",
    config: { installation: "northfield-bank", repos: ["northfield-bank/model-risk-docs"], branch: "main", globs: ["docs/**", "**/*.md"] },
    parsing: defaultParsing,
    ingest: ingest("custom", ["structure"]),
    rules: [{ id: "r3", kind: "exclude", field: "path", value: "docs/archive/**" }],
    metadataMapping: [
      { key: "area", from: "field:Path segment 2" },
      { key: "repo", from: "static:model-risk-docs" },
    ],
    tags: ["docs", "models"],
    titleFrom: "heading",
    permissions: { mode: "workspace" },
    schedule: { kind: "webhook", safetyNetDaily: true },
    deletedAtSource: "remove",
    staleAfterDays: 180,
    notifyOnFailure: true,
    sensitivity: "internal",
    collection: "Compliance",
    owner: "Model Risk",
    status: "active",
    itemsIndexed: 214,
    itemsFailed: 0,
    itemsPending: 0,
    lastSyncAt: ago(3),
    lastRunStatus: "success",
    lastRunDurationSec: 38,
    nextSyncAt: inHours(21),
    cursor: "sha:9f3c1e2",
    usedByKbIds: ["kb_eng", "kb_all"],
    createdAt: daysAgo(140),
  },
  {
    id: "src_contracts",
    type: "file",
    name: "Dispute rights guides",
    scopeSummary: "12 files from Files/Cards/Disputes",
    config: { folderId: "f_contracts" },
    parsing: { ...defaultParsing, ocr: true },
    ingest: ingest("policy_manual", ["structure", "context_headers", "parent_child"]),
    rules: [],
    metadataMapping: [
      { key: "guide", from: "field:Filename prefix" },
      { key: "product", from: "field:Product line" },
    ],
    tags: ["dispute", "cards"],
    titleFrom: "filename",
    permissions: { mode: "selected", principals: ["group:Card Services", "group:Compliance"] },
    schedule: { kind: "manual" },
    deletedAtSource: "remove",
    staleAfterDays: 365,
    notifyOnFailure: false,
    sensitivity: "restricted",
    collection: "Cards",
    owner: "Card Services",
    status: "active",
    itemsIndexed: 11,
    itemsFailed: 1,
    itemsPending: 0,
    lastSyncAt: daysAgo(3),
    lastRunStatus: "partial",
    lastRunDurationSec: 96,
    usedByKbIds: ["kb_legal"],
    createdAt: daysAgo(60),
  },
  {
    id: "src_pricing_crawl",
    type: "crawl",
    name: "Pricing site",
    scopeSummary: "https://www.northfieldbank.com/sitemap-pricing.xml · depth 3 · 200 pages max",
    config: { startUrl: "https://www.northfieldbank.com/sitemap-pricing.xml", depth: 3, maxPages: 200, sameDomain: true, include: ["/pricing/**", "/fees/**"], exclude: ["/pricing/archive/**"], respectRobots: true },
    parsing: { ...defaultParsing, tables: true },
    ingest: ingest("custom", ["clean", "structure"], { size: 400 }),
    rules: [],
    metadataMapping: [
      { key: "product", from: "field:URL path segment 2" },
      { key: "locale", from: "static:en-CA" },
    ],
    tags: ["pricing", "public"],
    titleFrom: "source",
    permissions: { mode: "workspace" },
    schedule: { kind: "daily", time: "05:00" },
    deletedAtSource: "keep_stale",
    staleAfterDays: 30,
    notifyOnFailure: true,
    sensitivity: "internal",
    collection: "Product",
    owner: "Retail Product",
    status: "active",
    itemsIndexed: 96,
    itemsFailed: 0,
    itemsPending: 0,
    lastSyncAt: ago(2),
    lastRunStatus: "success",
    lastRunDurationSec: 61,
    nextSyncAt: inHours(15),
    cursor: "etag-set:96",
    usedByKbIds: ["kb_support", "kb_all"],
    createdAt: daysAgo(90),
  },
  {
    id: "src_lending_policies",
    type: "file",
    name: "Lending policies and fee schedules",
    scopeSummary: "9 files from Files/Lending",
    config: { folderId: "f_lending" },
    parsing: { ...defaultParsing, tables: true },
    ingest: ingest("custom", ["structure", "context_headers", "table_rows"], { columns: RATE_COLUMNS }),
    rules: [],
    metadataMapping: [
      { key: "policy_area", from: "field:Filename prefix" },
      { key: "effective", from: "field:Effective date" },
      { key: "jurisdiction", from: "field:Jurisdiction" },
    ],
    tags: ["policy", "lending", "fees"],
    titleFrom: "filename",
    permissions: { mode: "selected", principals: ["group:Lending", "group:Legal"] },
    schedule: { kind: "manual" },
    deletedAtSource: "remove",
    staleAfterDays: 90,
    notifyOnFailure: true,
    sensitivity: "confidential",
    collection: "Lending",
    owner: "Lending Ops",
    status: "active",
    itemsIndexed: 9,
    itemsFailed: 0,
    itemsPending: 0,
    lastSyncAt: daysAgo(1),
    lastRunStatus: "success",
    lastRunDurationSec: 44,
    usedByKbIds: ["kb_lending", "kb_all"],
    createdAt: daysAgo(75),
  },
  {
    id: "src_branch_faq",
    type: "text",
    name: "Branch FAQ",
    scopeSummary: "Pasted Markdown · 1 document · 2,140 words",
    config: { format: "markdown" },
    parsing: defaultParsing,
    ingest: ingest("help_centre", ["structure", "faq"], {}, ["faq"]),
    rules: [],
    metadataMapping: [{ key: "audience", from: "static:branch-staff" }],
    tags: ["faq"],
    titleFrom: "heading",
    permissions: { mode: "workspace" },
    schedule: { kind: "manual" },
    deletedAtSource: "remove",
    staleAfterDays: 60,
    notifyOnFailure: false,
    sensitivity: "internal",
    collection: "Support",
    owner: "Branch Network",
    status: "active",
    itemsIndexed: 1,
    itemsFailed: 0,
    itemsPending: 0,
    lastSyncAt: daysAgo(6),
    lastRunStatus: "success",
    lastRunDurationSec: 9,
    usedByKbIds: ["kb_support"],
    createdAt: daysAgo(30),
  },
  {
    id: "src_zendesk_draft",
    type: "zendesk",
    name: "Help centre articles",
    connectionId: "int_zendesk",
    connectionLabel: "northfield.zendesk.com",
    scopeSummary: "Categories: Accounts, Cards · en-ca · published only",
    config: { subdomain: "northfield", categories: ["Accounts", "Cards"], locales: ["en-ca"], publishedOnly: true },
    parsing: defaultParsing,
    ingest: { ...ingest("help_centre", ["clean", "structure", "faq"]), approval: { status: "pending", approvedSteps: [], requestedBy: "Customer Care" } },
    rules: [],
    metadataMapping: [{ key: "product", from: "ai:product" }],
    tags: ["help-centre"],
    titleFrom: "source",
    permissions: { mode: "workspace" },
    schedule: { kind: "daily", time: "04:00" },
    deletedAtSource: "remove",
    staleAfterDays: 90,
    notifyOnFailure: true,
    sensitivity: "internal",
    collection: "Support",
    owner: "Customer Care",
    status: "draft",
    itemsIndexed: 0,
    itemsFailed: 0,
    itemsPending: 46,
    usedByKbIds: [],
    createdAt: daysAgo(1),
  },
  {
    id: "src_notion_product",
    type: "notion",
    name: "Product wiki",
    connectionId: "int_notion",
    connectionLabel: "Northfield Product (Notion)",
    scopeSummary: "Pages: Product wiki, Roadmap · child pages included",
    config: { pages: ["Product wiki", "Roadmap"], includeChildren: true },
    parsing: defaultParsing,
    ingest: ingest("custom", ["topic"], {}, ["topic"]),
    rules: [],
    metadataMapping: [{ key: "space", from: "static:product" }],
    tags: ["product"],
    titleFrom: "source",
    permissions: { mode: "workspace" },
    schedule: { kind: "daily", time: "06:00" },
    deletedAtSource: "keep_stale",
    staleAfterDays: 60,
    notifyOnFailure: false,
    sensitivity: "internal",
    collection: "Product",
    owner: "Retail Product",
    status: "paused",
    itemsIndexed: 142,
    itemsFailed: 0,
    itemsPending: 0,
    lastSyncAt: daysAgo(14),
    lastRunStatus: "success",
    lastRunDurationSec: 122,
    cursor: "last-edited:2026-09-15T06:00:00Z",
    usedByKbIds: ["kb_all"],
    createdAt: daysAgo(100),
  },
]

// ---- Items ----------------------------------------------------------------

const hrPolicies = [
  "Customer due diligence standard", "Enhanced due diligence procedure", "Sanctions screening procedure", "Suspicious transaction reporting",
  "Politically exposed persons guidance", "Beneficial ownership verification", "Transaction monitoring alert handling", "Know your customer refresh cycle",
  "Source of funds and wealth checks", "Cash transaction reporting", "Travel rule for wire transfers", "Risk rating methodology",
  "Record keeping and retention", "Adverse media screening", "Account opening identity checks", "Account closure and exit procedure",
  "Whistleblower and tipping-off policy", "Correspondent banking due diligence", "Sanctions list update procedure", "High-risk jurisdictions list",
  "Remote identity verification", "Third-party introducer checks", "Trade finance AML controls", "Prepaid and virtual card controls",
  "Money service business customers", "Charity and non-profit customers", "Compliance training requirements", "Regulatory reporting calendar",
  "Independent AML testing", "Escalation to the chief AML officer",
]
const hrSuffixes = ["", " — Ontario addendum", " — Quebec addendum", " — BC addendum", " — Alberta addendum", " — FAQ", " — manager guide", " — form", " — summary", " — appendix A", " — appendix B", " — training deck", " — checklist"]
const hrVariants = ["", " (2025)", " (2024)"].flatMap((y) => hrSuffixes.map((sfx) => `${sfx}${y}`))

const engPages = [
  "Wire Fraud Playbook §4.2 New-payee wires", "Wire release and escalation authority", "Fraud alert triage runbook", "Account takeover response", "Business email compromise indicators",
  "Payment recall and SWIFT gpi tracer", "Mule account detection", "Authorised push payment scam scripts", "Customer callback verification", "Hold and release SLAs",
  "Fraud loss reporting", "Velocity and limit rules", "Device and session risk signals", "Interac e-Transfer fraud rules", "Card-not-present fraud rules",
  "Cheque fraud and counterfeit checks", "Insider fraud referral", "Law enforcement requests", "Fraud case documentation standard", "Fraud rule change control",
]
const engSpaces = ["FRAUD", "PAY", "OPS"]

const ghDocs = [
  "docs/models/fraud-score-v4.md", "docs/models/model-inventory.md", "docs/models/validation-standard.md", "docs/models/wire-risk-score-thresholds.md", "docs/models/aml-alert-scoring.md",
  "docs/governance/model-risk-policy.md", "docs/governance/change-approval.md", "docs/governance/ongoing-monitoring.md", "docs/guides/model-card-template.md", "docs/guides/backtesting-method.md",
  "docs/guides/challenger-models.md", "docs/reference/performance-metrics.md", "docs/reference/data-lineage.md", "docs/reference/fairness-testing.md",
  "docs/reference/explainability.md", "docs/changelog/2026-09.md", "docs/changelog/2026-08.md", "docs/changelog/2026-07.md",
  "README.md", "CONTRIBUTING.md", "docs/reference/credit-decision-models.md", "docs/reference/dispute-triage-model.md", "docs/guides/kyc-risk-scoring.md", "docs/guides/override-and-limits.md",
]

export const contracts = [
  "Dispute rights guide — debit cards.pdf", "Dispute rights guide — credit cards.pdf", "Dispute rights guide — wires and e-Transfers.pdf",
  "Chargeback reason codes — fraud.pdf", "Chargeback reason codes — processing errors.pdf", "Provisional credit policy.pdf",
  "Dispute time limits — schedule.pdf", "Merchant representment checklist.pdf", "Unauthorised transaction liability.pdf",
  "Fee waiver guidance — disputes.pdf", "Dispute letter templates.pdf", "Escalation to the ombudsman.pdf",
]

const pricingPages = [
  "/pricing", "/pricing/chequing", "/pricing/savings", "/pricing/business-chequing", "/pricing/credit-cards", "/pricing/credit-cards/rewards",
  "/pricing/credit-cards/low-rate", "/pricing/mortgages", "/pricing/mortgages/fixed", "/pricing/mortgages/variable", "/pricing/lines-of-credit",
  "/pricing/wire-transfers", "/pricing/foreign-exchange", "/fees/overdraft-protection", "/fees/nsf-and-overdraft", "/fees/atm", "/fees/paper-statements",
  "/fees/account-closure", "/fees/safe-deposit", "/fees/certified-cheques", "/pricing/student", "/pricing/seniors", "/pricing/newcomers", "/pricing/credit-cards/annual-fee",
]

export const lendingFiles = [
  "Lending policy v6 — personal loans.pdf", "Lending policy v6 — small business.pdf", "Fee schedule 2026 Q3.xlsx", "Eligibility bands — personal.xlsx",
  "Hardship program guidelines.pdf", "Collections escalation matrix.xlsx", "Rate card — September 2026.xlsx", "Mortgage underwriting guide v4.2.pdf", "Lending policy v5 — personal loans (superseded).pdf",
]

const owners: Record<string, string[]> = {
  src_hr_sharepoint: ["Financial Crime Ops", "Compliance", "Financial Crime Ops", "Financial Crime Ops"],
  src_eng_confluence: ["Fraud Strategy", "Fraud Operations", "Fraud Strategy"],
  src_github_docs: ["Model Risk", "Fraud Strategy"],
  src_contracts: ["Card Services"],
  src_pricing_crawl: ["Retail Product"],
  src_lending_policies: ["Lending Ops"],
  src_branch_faq: ["Branch Network"],
  src_notion_product: ["Retail Product"],
}

function mk(
  rnd: () => number,
  src: Source,
  i: number,
  title: string,
  path: string,
  mime: string,
  extra: Partial<Item> = {}
): Item {
  const modifiedDays = Math.floor(rnd() * 400)
  const own = owners[src.id]
  const version = `v${1 + Math.floor(rnd() * 6)}.${Math.floor(rnd() * 4)}`
  const stale = modifiedDays > src.staleAfterDays
  return {
    id: `${src.id}_it_${i}`,
    sourceId: src.id,
    externalId: `${src.type}:${i.toString(36)}${Math.floor(rnd() * 9999).toString(36)}`,
    title,
    mimeType: mime,
    path,
    url: src.type === "crawl" ? `https://www.northfieldbank.com${path}` : src.type === "github" ? `https://github.com/northfield-bank/model-risk-docs/blob/main/${path}` : undefined,
    modifiedAt: daysAgo(modifiedDays),
    processedAt: src.lastSyncAt ?? daysAgo(1),
    sizeBytes: Math.floor(20_000 + rnd() * 2_400_000),
    status: "indexed",
    chunkCount: 4 + Math.floor(rnd() * 40),
    tags: [...src.tags],
    metadata: {},
    acl: src.permissions.mode === "workspace" ? ["workspace:*"] : src.permissions.mode === "selected" ? src.permissions.principals : [`group:${src.collection}`, "group:All staff"],
    owner: own[i % own.length],
    version,
    effectiveDate: daysAgo(modifiedDays).slice(0, 10),
    supersedes: rnd() > 0.7 ? `${title.replace(/\s*\(20\d\d\)/, "")} (${2024 + Math.floor(rnd() * 2)})` : undefined,
    reviewBy: stale ? daysAgo(modifiedDays - src.staleAfterDays).slice(0, 10) : inDays(src.staleAfterDays - modifiedDays).slice(0, 10),
    sensitivity: src.sensitivity,
    collection: src.collection,
    verified: rnd() > 0.85,
    queries30d: Math.floor(rnd() * rnd() * 120),
    pageCount: mime === "application/pdf" ? 2 + Math.floor(rnd() * 40) : undefined,
    digest: "",
    // Repo paths and crawled pages are distinct documents even when titles repeat (copies per folder, translations).
    family: src.type === "github" || src.type === "crawl" ? path : familyOf(title),
    versionStatus: "current",
    ...extra,
  }
}

const docClassFor = (title: string, sourceId: string) => {
  const t = title.toLowerCase()
  if (/\bfaq\b/.test(t)) return "faq"
  if (/addendum/.test(t)) return "addendum"
  if (/\bform\b|template/.test(t)) return "form"
  if (/appendix|summary|checklist|training|deck|guide/.test(t)) return "guidance"
  if (sourceId === "src_eng_confluence") return "playbook"
  if (sourceId === "src_github_docs") return "model_doc"
  if (sourceId === "src_pricing_crawl") return "pricing"
  if (sourceId === "src_notion_product") return "wiki"
  if (/schedule|rate card|bands|matrix/.test(t)) return "schedule"
  return sourceId === "src_hr_sharepoint" ? "procedure" : "policy"
}

/** Digest from the full body where there is one, else from what identifies the file, so duplicates share it. */
function finish(it: Item) {
  const key = FEATURED[it.id]
  const doc = key ? docByKey(key) : undefined
  it.digest = digestOf(doc ? docText(doc) : `${it.sourceId}|${it.path}|${it.sizeBytes}`)
  it.metadata = { doc_class: doc?.docClass ?? docClassFor(it.title, it.sourceId), ...it.metadata, ...(doc?.metadata ?? {}) }
  return it
}

export function buildItems(): Item[] {
  const rnd = seeded(42)
  const out: Item[] = []
  const bySrc = Object.fromEntries(sources.map((s) => [s.id, s])) as Record<string, Source>

  // HR SharePoint: 790 items (3 failed)
  {
    const src = bySrc.src_hr_sharepoint
    let i = 0
    for (const v of hrVariants) {
      for (const p of hrPolicies) {
        if (i >= 790) break
        const title = `${p}${v}`
        const isForm = v === " — form"
        const mime = isForm ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document" : i % 3 === 0 ? "application/pdf" : "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        const it = mk(rnd, src, i, title, `Documents/${isForm ? "Forms" : "Policies"}/${p.replace(/\s+/g, "-")}${v ? "/" + v.trim().replace(/[—()]/g, "").trim().replace(/\s+/g, "-") : ""}.${isForm ? "docx" : mime.includes("pdf") ? "pdf" : "docx"}`, mime)
        it.metadata = { department: "Financial crime", locale: "en", policy_owner: it.owner, jurisdiction: /Ontario/.test(v) ? "ON" : /Quebec/.test(v) ? "QC" : /BC/.test(v) ? "BC" : /Alberta/.test(v) ? "AB" : "CA" }
        // Year-marked copies are earlier versions of the same document.
        if (v.includes("(2025)")) it.effectiveDate = daysAgo(420 + (i % 60)).slice(0, 10)
        if (v.includes("(2024)")) it.effectiveDate = daysAgo(800 + (i % 60)).slice(0, 10)
        out.push(it)
        i++
      }
    }
    // three failures
    const fails: [number, ErrorClass, string][] = [
      [17, "parse", "PDF is encrypted; OCR cannot open the file"],
      [143, "parse", "DOCX is password protected"],
      [512, "too_large", "File is 72 MB; limit is 50 MB"],
    ]
    for (const [idx, cls, msg] of fails) {
      out[idx].status = "failed"
      out[idx].errorClass = cls
      out[idx].error = msg
      out[idx].chunkCount = 0
    }
    out.find((x) => x.id === "src_hr_sharepoint_it_12")!.effectiveDate = "2026-02-01"
    out.find((x) => x.id === "src_hr_sharepoint_it_402")!.effectiveDate = "2025-02-01"
    // Left in the library's Archive folder; the source's exclude rule keeps it out.
    const archived = mk(rnd, src, 790, "Sanctions screening procedure (2021 archive)", "Documents/Archive/Sanctions-screening-procedure-2021.pdf", "application/pdf")
    archived.metadata = { department: "Financial crime", locale: "en", policy_owner: archived.owner, jurisdiction: "CA" }
    out.push(archived)
  }

  // Confluence: 380 items
  {
    const src = bySrc.src_eng_confluence
    let i = 0
    const suffixes = ["", " — v2", " — checklist", " — examples", " — FAQ", " — diagrams", " — 2025 review", " — owners", " — SLAs", " — glossary", " — playbook", " — quick reference", " — onboarding", " — history", " — decisions", " — metrics", " — links", " — templates", " — runbook"]
    for (const s of suffixes) {
      for (const p of engPages) {
        if (i >= 380) break
        const space = engSpaces[i % 3]
        const it = mk(rnd, src, i, `${p}${s}`, `${space}/${p.replace(/\s+/g, "+")}${s ? "/" + s.replace(/[— ]+/g, "-") : ""}`, "text/html")
        it.metadata = { space, team: space === "OPS" ? "payments-ops" : "fraud-strategy" }
        out.push(it)
        i++
      }
    }
    Object.assign(out.find((x) => x.id === "src_eng_confluence_it_0")!, { version: "v5.0", effectiveDate: "2026-05-01" })
    Object.assign(out.find((x) => x.id === "src_eng_confluence_it_1")!, { version: "v3.4", effectiveDate: "2025-11-01" })
    // The same travel-rule procedure is copied into the payments space; it is indexed once.
    const copy = mk(rnd, src, 380, "Travel rule for wire transfers", "PAY/Travel+rule+for+wire+transfers", "text/html")
    copy.metadata = { space: "PAY", team: "payments-ops" }
    out.push(copy)
    const notes = mk(rnd, src, 381, "Meeting notes — fraud ops weekly 2026-09-22", "OPS/Meeting+notes/2026-09-22", "text/html")
    notes.metadata = { space: "OPS", team: "payments-ops" }
    out.push(notes)
  }

  // GitHub: 214 items
  {
    const src = bySrc.src_github_docs
    let i = 0
    const dirs = ["", "v2/", "v1/", "internal/", "audit/", "regulatory/", "retail/", "commercial/", "pilot/"]
    for (const d of dirs) {
      for (const p of ghDocs) {
        if (i >= 214) break
        const path = d ? p.replace("docs/", `docs/${d}`) : p
        const title = path.split("/").pop()!.replace(/\.md$/, "").replace(/-/g, " ").replace(/^\w/, (c) => c.toUpperCase())
        const it = mk(rnd, src, i, title, path, "text/markdown")
        it.metadata = { area: path.split("/")[1] ?? "root", repo: "model-risk-docs" }
        out.push(it)
        i++
      }
    }
  }

  // Contracts: 12 (1 failed)
  {
    const src = bySrc.src_contracts
    contracts.forEach((c, i) => {
      const it = mk(rnd, src, i, c.replace(/\.pdf$/, ""), `Cards/Disputes/${c}`, "application/pdf", {
        fileId: `file_dispute_guide_${i}`,
        effectiveDate: daysAgo(30 + i * 9).slice(0, 10),
        // The letter templates arrived without a product line, so Cards & disputes holds them.
        metadata: i === 10 ? { guide: c.split(" — ")[0] } : { guide: c.split(" — ")[0], product: "cards" },
      })
      if (i === 6) {
        it.status = "failed"
        it.errorClass = "parse"
        it.error = "PDF is encrypted (owner password); upload an unlocked copy"
        it.chunkCount = 0
      }
      out.push(it)
    })
  }

  // Pricing crawl: 96
  {
    const src = bySrc.src_pricing_crawl
    let i = 0
    const locales = ["", "/fr", "/en-us", "/print"]
    for (const l of locales) {
      for (const p of pricingPages) {
        if (i >= 96) break
        const path = `${p}${l}`
        const title = (p === "/pricing" ? "Pricing overview" : p.split("/").pop()!.replace(/-/g, " ").replace(/^\w/, (c) => c.toUpperCase()).replace(/^Nsf/, "NSF")) + (l ? ` (${l.slice(1)})` : "")
        const it = mk(rnd, src, i, title, path, "text/html")
        it.metadata = { product: p.split("/")[2] ?? "overview", locale: "en-CA" }
        it.modifiedAt = daysAgo(Math.floor(rnd() * 20))
        it.reviewBy = inDays(30 - Math.floor(rnd() * 20)).slice(0, 10)
        out.push(it)
        i++
      }
    }
  }

  // Lending: 9
  {
    const src = bySrc.src_lending_policies
    lendingFiles.forEach((f, i) => {
      const mime = f.endsWith(".xlsx") ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" : f.endsWith(".docx") ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document" : "application/pdf"
      const it = mk(rnd, src, i, f.replace(/\.(pdf|xlsx|docx)$/, ""), `Lending/${f}`, mime, {
        fileId: `file_lending_${i}`,
        // The collections matrix has no jurisdiction field at the source, so Lending policy holds it.
        metadata: { policy_area: f.split(" ")[0].toLowerCase(), effective: "2026-07-01", product: /small business/i.test(f) ? "small_business_loan" : /mortgage/i.test(f) ? "mortgage" : "personal_loan", ...(f.startsWith("Collections") ? {} : { jurisdiction: "CA" }) },
        version: f.includes("v6") ? "v6.0" : f.includes("v5") ? "v5.2" : f.includes("v4.2") ? "v4.2" : "v1.3",
        effectiveDate: "2026-07-01",
        reviewBy: "2026-12-31",
        verified: true,
      })
      if (f.includes("v6 — personal")) it.supersedes = "Lending policy v5 — personal loans"
      if (f.includes("v5")) {
        it.modifiedAt = daysAgo(240)
        it.effectiveDate = "2025-01-15"
        it.reviewBy = "2026-01-15"
      }
      out.push(it)
    })
    // Payment deferral policy: v1.0 was in force until v2.0 took effect on 1 March 2026.
    ;[
      { n: 9, version: "v1.0", effectiveDate: "2024-11-01", modified: 340 },
      { n: 10, version: "v2.0", effectiveDate: "2026-03-01", modified: 200 },
    ].forEach(({ n, version, effectiveDate, modified }) => {
      const it = mk(rnd, src, n, "Payment deferral policy", `Lending/Payment deferral policy ${version}.pdf`, "application/pdf", {
        fileId: `file_lending_${n}`,
        metadata: { policy_area: "payment", effective: effectiveDate, product: "personal_loan", jurisdiction: "CA" },
        version,
        effectiveDate,
        reviewBy: "2026-12-31",
        verified: true,
        supersedes: version === "v2.0" ? "Payment deferral policy v1.0" : undefined,
      })
      it.modifiedAt = daysAgo(modified)
      out.push(it)
    })
  }

  // Branch FAQ: 1
  {
    const src = bySrc.src_branch_faq
    const it = mk(rnd, src, 0, "Branch FAQ", "Branch FAQ.md", "text/markdown", { metadata: { audience: "branch-staff" }, chunkCount: 58 })
    it.modifiedAt = daysAgo(6)
    out.push(it)
  }

  // Notion: 142
  {
    const src = bySrc.src_notion_product
    const pages = ["Product wiki", "Roadmap 2026 H2", "Pricing experiments", "Mobile app release notes", "Card controls spec", "Open banking integration", "Savings product rules", "Customer research", "Rate benchmarks", "Contact centre scripts"]
    let i = 0
    for (let k = 0; k < 15; k++) {
      for (const p of pages) {
        if (i >= 142) break
        const it = mk(rnd, src, i, k === 0 ? p : `${p} — part ${k}`, `Product wiki/${p}${k ? "/part-" + k : ""}`, "text/html")
        it.metadata = { space: "product" }
        out.push(it)
        i++
      }
    }
  }

  return out.map(finish)
}

// ---- Runs -----------------------------------------------------------------

const doneP = (name: SyncRunPhaseName, ms: number) => ({ name, durationMs: ms, status: "done" as const })
type SyncRunPhaseName = "list" | "fetch" | "parse" | "chunk" | "embed" | "upsert"

export const runs: SyncRun[] = [
  {
    id: "run_hr_1",
    sourceId: "src_hr_sharepoint",
    trigger: "schedule",
    startedAt: ago(0.32),
    durationSec: 412,
    status: "partial",
    cursorBefore: "delta:MzslMjM7MTsy",
    cursorAfter: "delta:MzslMjM7MTsz",
    counts: { listed: 812, unchanged: 741, upserted: 46, deleted: 0, failed: 3, skipped: 22 },
    phases: [doneP("list", 2100), doneP("fetch", 88000), doneP("parse", 190000), doneP("chunk", 41000), doneP("embed", 79000), doneP("upsert", 12000)],
    errors: [
      { itemId: "src_hr_sharepoint_it_17", itemTitle: "Correspondent banking due diligence", phase: "parse", errorClass: "parse", message: "PDF is encrypted; OCR cannot open the file" },
      { itemId: "src_hr_sharepoint_it_143", itemTitle: "Prepaid and virtual card controls — Alberta addendum", phase: "parse", errorClass: "parse", message: "DOCX is password protected" },
      { itemId: "src_hr_sharepoint_it_512", itemTitle: "Sanctions screening procedure — Alberta addendum (2025)", phase: "fetch", errorClass: "too_large", message: "File is 72 MB; limit is 50 MB" },
    ],
    log: [
      "02:00:01 list: delta query from cursor delta:MzslMjM7MTsy",
      "02:00:03 list: 812 items, 46 changed, 22 skipped by rule **/Archive/**",
      "02:01:31 fetch: 46 files (61.2 MB)",
      "02:01:40 fetch: FAILED Sanctions screening procedure — Alberta addendum (2025) (72 MB > 50 MB)",
      "02:04:51 parse: 44 ok, 2 failed (encrypted)",
      "02:05:32 chunk: 1,893 chunks (structure aware, 512/50)",
      "02:06:51 embed: 1,893 vectors",
      "02:07:03 upsert: 46 documents, 3 failed",
      "02:07:03 done: partial",
    ],
  },
  {
    id: "run_hr_2",
    sourceId: "src_hr_sharepoint",
    trigger: "schedule",
    startedAt: daysAgo(1),
    durationSec: 388,
    status: "partial",
    counts: { listed: 809, unchanged: 780, upserted: 26, deleted: 1, failed: 3, skipped: 22 },
    phases: [doneP("list", 2000), doneP("fetch", 60000), doneP("parse", 180000), doneP("chunk", 39000), doneP("embed", 70000), doneP("upsert", 11000)],
    errors: [],
    log: ["done: partial (3 known failures)"],
  },
  {
    id: "run_hr_3",
    sourceId: "src_hr_sharepoint",
    trigger: "webhook",
    startedAt: daysAgo(2),
    durationSec: 41,
    status: "success",
    counts: { listed: 809, unchanged: 805, upserted: 4, deleted: 0, failed: 0, skipped: 22 },
    phases: [doneP("list", 1800), doneP("fetch", 8000), doneP("parse", 16000), doneP("chunk", 4000), doneP("embed", 9000), doneP("upsert", 2000)],
    errors: [],
    log: ["done: success"],
  },
  {
    id: "run_hr_4",
    sourceId: "src_hr_sharepoint",
    trigger: "full",
    startedAt: daysAgo(9),
    durationSec: 2410,
    status: "success",
    cursorRejected: true,
    counts: { listed: 806, unchanged: 0, upserted: 806, deleted: 4, failed: 0, skipped: 22 },
    phases: [doneP("list", 9000), doneP("fetch", 600000), doneP("parse", 1200000), doneP("chunk", 200000), doneP("embed", 380000), doneP("upsert", 21000)],
    errors: [],
    log: ["list: saved cursor rejected by SharePoint (410 Gone); full listing ran", "4 unseen items removed", "done: success"],
  },
  {
    id: "run_conf_1",
    sourceId: "src_eng_confluence",
    trigger: "schedule",
    startedAt: ago(9),
    durationSec: 4,
    status: "failed",
    cursorBefore: "modified-since:2026-09-22T03:00:00Z",
    counts: { listed: 0, unchanged: 0, upserted: 0, deleted: 0, failed: 0, skipped: 0 },
    phases: [{ name: "list", durationMs: 3900, status: "failed" }, { name: "fetch", durationMs: 0, status: "skipped" }, { name: "parse", durationMs: 0, status: "skipped" }, { name: "chunk", durationMs: 0, status: "skipped" }, { name: "embed", durationMs: 0, status: "skipped" }, { name: "upsert", durationMs: 0, status: "skipped" }],
    errors: [{ itemId: "", itemTitle: "(connection)", phase: "list", errorClass: "permission", message: "401 from Confluence: token expired" }],
    log: ["03:00:00 list: GET /wiki/rest/api/content/search?cql=lastModified>=2026-09-22", "03:00:04 list: HTTP 401 Unauthorized — token expired", "03:00:04 done: failed (connection)"],
  },
  {
    id: "run_conf_2",
    sourceId: "src_eng_confluence",
    trigger: "schedule",
    startedAt: daysAgo(7),
    durationSec: 301,
    status: "success",
    counts: { listed: 384, unchanged: 360, upserted: 20, deleted: 4, failed: 0, skipped: 9 },
    phases: [doneP("list", 4000), doneP("fetch", 60000), doneP("parse", 120000), doneP("chunk", 30000), doneP("embed", 80000), doneP("upsert", 7000)],
    errors: [],
    log: ["done: success"],
  },
  {
    id: "run_gh_1",
    sourceId: "src_github_docs",
    trigger: "webhook",
    startedAt: ago(3),
    durationSec: 38,
    status: "success",
    cursorBefore: "sha:1b77a09",
    cursorAfter: "sha:9f3c1e2",
    counts: { listed: 214, unchanged: 211, upserted: 3, deleted: 0, failed: 0, skipped: 6 },
    phases: [doneP("list", 900), doneP("fetch", 3000), doneP("parse", 6000), doneP("chunk", 4000), doneP("embed", 20000), doneP("upsert", 4000)],
    errors: [],
    log: ["push webhook: 3 files changed in docs/models", "done: success"],
  },
  {
    id: "run_gh_2",
    sourceId: "src_github_docs",
    trigger: "schedule",
    startedAt: daysAgo(1),
    durationSec: 22,
    status: "success",
    counts: { listed: 214, unchanged: 214, upserted: 0, deleted: 0, failed: 0, skipped: 6 },
    phases: [doneP("list", 900), doneP("fetch", 0), doneP("parse", 0), doneP("chunk", 0), doneP("embed", 0), doneP("upsert", 0)],
    errors: [],
    log: ["done: success (no changes)"],
  },
  {
    id: "run_contracts_1",
    sourceId: "src_contracts",
    trigger: "manual",
    startedAt: daysAgo(3),
    durationSec: 96,
    status: "partial",
    counts: { listed: 12, unchanged: 0, upserted: 11, deleted: 0, failed: 1, skipped: 0 },
    phases: [doneP("list", 300), doneP("fetch", 2000), doneP("parse", 70000), doneP("chunk", 9000), doneP("embed", 13000), doneP("upsert", 1700)],
    errors: [{ itemId: "src_contracts_it_6", itemTitle: "Dispute time limits — schedule", phase: "parse", errorClass: "parse", message: "PDF is encrypted (owner password); upload an unlocked copy" }],
    log: ["parse: OCR on 4 scanned pages", "parse: FAILED Dispute time limits — schedule (encrypted)", "done: partial"],
  },
  {
    id: "run_pricing_1",
    sourceId: "src_pricing_crawl",
    trigger: "schedule",
    startedAt: ago(2),
    durationSec: 61,
    status: "success",
    cursorAfter: "etag-set:96",
    counts: { listed: 96, unchanged: 90, upserted: 6, deleted: 0, failed: 0, skipped: 3 },
    phases: [doneP("list", 1500), doneP("fetch", 30000), doneP("parse", 9000), doneP("chunk", 5000), doneP("embed", 12000), doneP("upsert", 2500)],
    errors: [],
    log: ["sitemap: 99 URLs, 3 excluded by /pricing/archive/**", "6 pages changed (lastmod)", "done: success"],
  },
  {
    id: "run_pricing_2",
    sourceId: "src_pricing_crawl",
    trigger: "schedule",
    startedAt: daysAgo(1),
    durationSec: 240,
    status: "backing_off",
    counts: { listed: 96, unchanged: 60, upserted: 12, deleted: 0, failed: 0, skipped: 3 },
    phases: [doneP("list", 1500), { name: "fetch", durationMs: 200000, status: "failed" }, { name: "parse", durationMs: 0, status: "skipped" }, { name: "chunk", durationMs: 0, status: "skipped" }, { name: "embed", durationMs: 0, status: "skipped" }, { name: "upsert", durationMs: 0, status: "skipped" }],
    errors: [{ itemId: "", itemTitle: "(24 pages)", phase: "fetch", errorClass: "rate_limited", message: "429 from www.northfieldbank.com; Retry-After 900s" }],
    log: ["fetch: 429 after 72 pages; backing off 15 min", "resumed and completed in run at 05:00 next day"],
  },
  {
    id: "run_lending_1",
    sourceId: "src_lending_policies",
    trigger: "manual",
    startedAt: daysAgo(1),
    durationSec: 44,
    status: "success",
    counts: { listed: 9, unchanged: 7, upserted: 2, deleted: 0, failed: 0, skipped: 0 },
    phases: [doneP("list", 200), doneP("fetch", 1000), doneP("parse", 20000), doneP("chunk", 8000), doneP("embed", 12000), doneP("upsert", 2000)],
    errors: [],
    log: ["parse: 3 spreadsheets → 412 row chunks", "done: success"],
  },
  {
    id: "run_notion_1",
    sourceId: "src_notion_product",
    trigger: "schedule",
    startedAt: daysAgo(14),
    durationSec: 122,
    status: "success",
    counts: { listed: 142, unchanged: 130, upserted: 12, deleted: 0, failed: 0, skipped: 0 },
    phases: [doneP("list", 3000), doneP("fetch", 40000), doneP("parse", 20000), doneP("chunk", 30000), doneP("embed", 25000), doneP("upsert", 4000)],
    errors: [],
    log: ["done: success"],
  },
  {
    id: "run_faq_1",
    sourceId: "src_branch_faq",
    trigger: "manual",
    startedAt: daysAgo(6),
    durationSec: 9,
    status: "success",
    counts: { listed: 1, unchanged: 0, upserted: 1, deleted: 0, failed: 0, skipped: 0 },
    phases: [doneP("list", 10), doneP("fetch", 10), doneP("parse", 500), doneP("chunk", 6000), doneP("embed", 2000), doneP("upsert", 300)],
    errors: [],
    log: ["chunk: FAQ optimised → 58 question/answer chunks", "done: success"],
  },
]
