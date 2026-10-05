import {
  AlertTriangle,
  Bot,
  BookOpen,
  CheckCircle,
  Clock,
  Code2,
  Database,
  FileText,
  GitBranch,
  Globe,
  Headset,
  Mail,
  MessageCircleQuestion,
  MessageSquare,
  Phone,
  Repeat,
  ScanText,
  Search,
  Send,
  Settings,
  Shield,
  ShieldCheck,
  Sparkles,
  Split,
  UserCheck,
  Workflow,
  Wrench,
  XCircle,
  Zap,
  Brain,
  type LucideIcon,
} from "lucide-react"

// ── Icons (string keys are what graphs store) ──

export const ICONS: Record<string, LucideIcon> = {
  phone: Phone, message: MessageSquare, search: Search, send: Send, shield: Shield, brain: Brain,
  database: Database, code: Code2, globe: Globe, branch: GitBranch, user: UserCheck, zap: Zap,
  book: BookOpen, clock: Clock, check: CheckCircle, x: XCircle, repeat: Repeat, wrench: Wrench,
  file: FileText, sparkles: Sparkles, alert: AlertTriangle, settings: Settings, bot: Bot, mail: Mail,
  scan: ScanText, workflow: Workflow, ask: MessageCircleQuestion, headset: Headset, split: Split,
  shieldcheck: ShieldCheck,
}

export const iconKey = (icon: LucideIcon) => Object.entries(ICONS).find(([, c]) => c === icon)?.[0] ?? "brain"

// ── Field specs: what the inspector shows for each node kind, and which fields the checks require ──

export type OptionSource = "agents" | "tools" | "collections" | "workflows" | "owners" | "reviewerGroups" | "sla" | "durations" | "schedules"

export interface FieldSpec {
  key: string
  label: string
  input: "text" | "textarea" | "select" | "branches"
  options?: OptionSource
  placeholder?: string
  hint?: string
  required?: boolean
  mono?: boolean
}

export interface NodeKind {
  id: string
  label: string
  description: string
  icon: LucideIcon
  group: GroupId
  /** ReactFlow node type that renders it. */
  type: "trigger" | "step" | "branch" | "review" | "end"
  fields: FieldSpec[]
  /** Starting branch labels for branch nodes. */
  branches?: string[]
  isNew?: boolean
}

export type GroupId = "trigger" | "ai" | "tool" | "human" | "logic" | "output"

const F = {
  agent: { key: "agentSlug", label: "Agent", input: "select", options: "agents", required: true, hint: "Its tools, knowledge and guardrails come with it." } as FieldSpec,
  tool: { key: "description", label: "Tool", input: "select", options: "tools", required: true, mono: true, hint: "Money-moving tools should sit behind an approval gate." } as FieldSpec,
}

export const NODE_KINDS: NodeKind[] = [
  // Trigger
  { id: "chat", label: "Chat message", description: "Widget or chat API conversation", icon: MessageSquare, group: "trigger", type: "trigger", fields: [] },
  { id: "api", label: "API call", description: "Authenticated request; returns the output", icon: Globe, group: "trigger", type: "trigger", isNew: true, fields: [{ key: "description", label: "Expected input", input: "textarea", placeholder: '{ "accountId": "…" }', mono: true }] },
  { id: "email", label: "Email received", description: "Mail to a routed address; keeps the thread", icon: Mail, group: "trigger", type: "trigger", isNew: true, fields: [{ key: "description", label: "Inbox", input: "text", placeholder: "disputes@northfieldbank.com", required: true }] },
  { id: "event", label: "Event / webhook", description: "A system event such as wire initiated", icon: Zap, group: "trigger", type: "trigger", fields: [{ key: "description", label: "Event", input: "text", placeholder: "Wire initiated ≥ $10,000", required: true }] },
  { id: "schedule", label: "Schedule", description: "Runs on a schedule", icon: Clock, group: "trigger", type: "trigger", fields: [{ key: "description", label: "Runs", input: "select", options: "schedules", required: true }] },
  { id: "batch", label: "Batch file", description: "One run per CSV row", icon: FileText, group: "trigger", type: "trigger", fields: [{ key: "description", label: "Columns", input: "text", placeholder: "accountId, amount, reason" }] },
  // AI
  { id: "agent", label: "Agent", description: "Runs an agent with its tools and knowledge", icon: Bot, group: "ai", type: "step", fields: [F.agent] },
  { id: "prompt", label: "Prompt", description: "One model call from a template, no tools", icon: Sparkles, group: "ai", type: "step", fields: [{ key: "description", label: "Prompt", input: "textarea", placeholder: "Summarise {{input}} in two sentences for a reviewer.", required: true }] },
  { id: "classify", label: "Classify and route", description: "Sends the run down one labelled path", icon: GitBranch, group: "ai", type: "branch", branches: ["Low", "Gate", "Block"], fields: [{ key: "description", label: "Classify by", input: "text", placeholder: "Fraud risk of the wire", required: true }, { key: "branches", label: "Paths", input: "branches" }] },
  { id: "extract", label: "Extract", description: "Typed fields from text or a document", icon: ScanText, group: "ai", type: "step", isNew: true, fields: [{ key: "description", label: "Fields", input: "text", placeholder: "employer, annual income, start date", required: true }] },
  // Data and tools
  { id: "knowledge", label: "Knowledge search", description: "Searches collections, keeps citations", icon: BookOpen, group: "tool", type: "step", fields: [{ key: "description", label: "Collection", input: "select", options: "collections", required: true }] },
  { id: "tool", label: "Tool", description: "A registered HTTP, code or MCP tool", icon: Wrench, group: "tool", type: "step", fields: [F.tool] },
  { id: "http", label: "HTTP request", description: "Ad-hoc call to an allow-listed host", icon: Globe, group: "tool", type: "step", fields: [{ key: "description", label: "URL", input: "text", placeholder: "https://api.internal/…", required: true, mono: true }] },
  { id: "code", label: "Code", description: "Sandboxed JavaScript transform", icon: Code2, group: "tool", type: "step", fields: [{ key: "description", label: "Code", input: "textarea", placeholder: "return { total: input.items.length }", mono: true, required: true }] },
  { id: "subworkflow", label: "Run workflow", description: "Calls another workflow and waits", icon: Workflow, group: "tool", type: "step", isNew: true, fields: [{ key: "description", label: "Workflow", input: "select", options: "workflows", required: true }] },
  // Human
  { id: "approval", label: "Approval gate", description: "Pauses into the Reviews queue with an SLA", icon: UserCheck, group: "human", type: "review", fields: [] },
  { id: "two-person", label: "Two-person approval", description: "Same gate, two reviewers required", icon: ShieldCheck, group: "human", type: "review", fields: [] },
  { id: "ask", label: "Ask the customer", description: "Requests missing information and waits", icon: MessageCircleQuestion, group: "human", type: "step", isNew: true, fields: [{ key: "description", label: "Question", input: "textarea", placeholder: "Please upload your latest T4.", required: true }, { key: "sla", label: "Wait up to", input: "select", options: "durations" }] },
  { id: "handoff", label: "Hand off to person", description: "Moves the conversation to a live team", icon: Headset, group: "human", type: "step", fields: [{ key: "description", label: "Team", input: "select", options: "owners", required: true }] },
  // Logic
  { id: "condition", label: "Condition", description: "If / else on run fields", icon: Split, group: "logic", type: "branch", branches: ["Yes", "No"], fields: [{ key: "description", label: "If", input: "text", placeholder: "amount > 50,000", required: true, mono: true }] },
  { id: "switch", label: "Switch", description: "Many-way branch on a value", icon: GitBranch, group: "logic", type: "branch", isNew: true, branches: ["A", "B", "Other"], fields: [{ key: "description", label: "Value", input: "text", placeholder: "dispute.reasonCode", required: true, mono: true }, { key: "branches", label: "Cases", input: "branches" }] },
  { id: "loop", label: "Loop", description: "Repeats steps per item", icon: Repeat, group: "logic", type: "step", fields: [{ key: "description", label: "For each", input: "text", placeholder: "owners", required: true, mono: true }] },
  { id: "wait", label: "Wait", description: "Delay, or wait for a time or event", icon: Clock, group: "logic", type: "step", fields: [{ key: "description", label: "Wait", input: "select", options: "durations", required: true }] },
  { id: "set", label: "Set fields", description: "Assigns run variables", icon: Settings, group: "logic", type: "step", fields: [{ key: "description", label: "Assignments", input: "textarea", placeholder: "riskBand = output.band", mono: true }] },
  // Output
  { id: "reply", label: "Reply", description: "Answers on the triggering channel", icon: Send, group: "output", type: "step", fields: [{ key: "description", label: "Message", input: "textarea", placeholder: "Leave empty to send the agent's answer" }] },
  { id: "send-email", label: "Send email", description: "From an approved sender address", icon: Mail, group: "output", type: "step", isNew: true, fields: [{ key: "description", label: "To", input: "text", placeholder: "{{customer.email}}", required: true }, { key: "subject", label: "Subject", input: "text", placeholder: "About your dispute", required: true }, { key: "body", label: "Message", input: "textarea", placeholder: "Leave empty to send the agent's answer" }] },
  { id: "end", label: "End", description: "Finishes with an outcome label", icon: CheckCircle, group: "output", type: "end", fields: [] },
  { id: "error", label: "On error", description: "Path taken when any step fails", icon: AlertTriangle, group: "output", type: "trigger", isNew: true, fields: [] },
]

export const kindOf = (id?: unknown) => NODE_KINDS.find((k) => k.id === id)

// ── Palette groups ──

export interface PaletteCategory {
  id: GroupId
  label: string
  iconBg: string
  iconText: string
  kinds: NodeKind[]
}

const GROUP_META: Record<GroupId, { label: string; iconBg: string; iconText: string }> = {
  trigger: { label: "Trigger", iconBg: "bg-violet-500/15", iconText: "text-violet-600 dark:text-violet-400" },
  ai: { label: "AI", iconBg: "bg-indigo-500/15", iconText: "text-indigo-600 dark:text-indigo-300" },
  tool: { label: "Data and tools", iconBg: "bg-teal-500/15", iconText: "text-teal-600 dark:text-teal-400" },
  human: { label: "Human", iconBg: "bg-amber-500/15", iconText: "text-amber-600 dark:text-amber-400" },
  logic: { label: "Logic", iconBg: "bg-slate-500/15", iconText: "text-slate-600 dark:text-slate-300" },
  output: { label: "Output", iconBg: "bg-rose-500/15", iconText: "text-rose-600 dark:text-rose-400" },
}

export const PALETTE_CATEGORIES: PaletteCategory[] = (Object.keys(GROUP_META) as GroupId[]).map((id) => ({
  id,
  ...GROUP_META[id],
  kinds: NODE_KINDS.filter((k) => k.group === id),
}))

// ── Color system (category = group id; older graphs also use guard / data / response / control) ──

export const CAT_COLORS: Record<string, { bg: string; text: string; border: string; glow?: string }> = {
  trigger:  { bg: "bg-violet-500/15", text: "text-violet-600 dark:text-violet-400", border: "border-violet-500/30" },
  ai:       { bg: "bg-indigo-500/15", text: "text-indigo-600 dark:text-indigo-300", border: "border-indigo-500/40", glow: "shadow-indigo-500/10" },
  tool:     { bg: "bg-teal-500/15",   text: "text-teal-600 dark:text-teal-400",   border: "border-teal-500/30" },
  human:    { bg: "bg-amber-500/15",  text: "text-amber-600 dark:text-amber-400", border: "border-amber-500/50" },
  logic:    { bg: "bg-slate-500/15",  text: "text-slate-600 dark:text-slate-300",  border: "border-slate-500/30" },
  output:   { bg: "bg-rose-500/15",   text: "text-rose-600 dark:text-rose-400",   border: "border-rose-500/30" },
  response: { bg: "bg-rose-500/15",   text: "text-rose-600 dark:text-rose-400",   border: "border-rose-500/30" },
  control:  { bg: "bg-rose-500/15",   text: "text-rose-600 dark:text-rose-400",   border: "border-rose-500/30" },
  data:     { bg: "bg-teal-500/15",   text: "text-teal-700 dark:text-teal-400",   border: "border-teal-500/30" },
  guard:    { bg: "bg-orange-500/15", text: "text-orange-600 dark:text-orange-400", border: "border-orange-500/30" },
}

export const GROUP_LABEL: Record<string, string> = { ...Object.fromEntries(Object.entries(GROUP_META).map(([k, v]) => [k, v.label])), response: "Output", control: "Output", data: "Data and tools", guard: "Data and tools" }

// ── Node data ──

export interface StepData {
  label: string
  description: string
  icon: string
  category: string
  kind?: string
  badge?: string
  status?: "active" | "success" | "error"
  agentSlug?: string
  agentVersion?: number
  branches?: string[]
  reviewers?: string
  condition?: string
  sla?: string
  fourEyes?: boolean
  [key: string]: unknown
}

export const DND_MIME = "application/x-agent-node"

/** Resolve a palette entry into the ReactFlow node type and data it creates. */
export function paletteToNode(kindId: string): { type: string; data: StepData } | null {
  const k = kindOf(kindId)
  if (!k) return null
  const data: StepData = { label: k.label, description: "", icon: iconKey(k.icon), category: k.group, kind: k.id }
  if (k.type === "branch") data.branches = [...(k.branches ?? [])]
  if (k.type === "review") Object.assign(data, { reviewers: "Unassigned group", sla: "1 h", condition: "always", fourEyes: k.id === "two-person" })
  if (k.id === "end") data.description = "Done"
  return { type: k.type, data }
}

/** Kind of a node, including graphs saved before nodes carried an explicit kind. */
export function resolveKind(n: { type?: string; data: StepData }): NodeKind | undefined {
  const k = kindOf(n.data.kind);
  if (k) return k;
  if (n.type === "review") return kindOf(n.data.fourEyes ? "two-person" : "approval");
  if (n.type === "end") return kindOf("end");
  if (n.type === "router") return undefined;
  if (n.type === "step" && n.data.category === "ai") return kindOf("agent");
  if (n.type === "step" && n.data.category === "tool") return kindOf("tool");
  return undefined;
}
