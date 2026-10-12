import type { LifecycleStatus, ToolAccess } from './domain';
import type { EvalCheck, EvalCheckResult } from './evals';

/**
 * Skills: versioned, reusable procedures an agent loads when a task matches its "use when" line. A skill adds
 * instructions, resources and guardrails; it never grants a tool or knowledge base the agent does not already
 * hold. Portable as an Agent Skills folder (`SKILL.md` with `name` and `description` frontmatter, plus
 * resources). Spec 11.
 */

export type SkillStatus = 'draft' | 'in_review' | 'published' | 'deprecated';
export type SkillVersionState = 'draft' | 'in_review' | 'published' | 'superseded' | 'deprecated' | 'rejected';
/** Wording changes re-run the tests; tool, knowledge base or guardrail changes also need a second approver. */
export type SkillEditClass = 'free' | 're_test' | 're_approval';
export type SkillOrigin = 'blank' | 'generated' | 'imported' | 'duplicated';
/**
 * When the runtime adds a skill to a turn. `on_match`: when a message matches its use-when line. `always`: in every
 * turn of every agent that pins it, after the agent's own instructions; shared text such as a disclosure or a tone
 * guide is an always-on skill. An always-on skill needs no use-when line.
 */
export type SkillLoading = 'on_match' | 'always';
export type SkillSectionKey = 'steps' | 'rules' | 'examples' | 'output_format';

/** A tool module operation the skill's steps call. The agent must already hold it. */
export interface SkillToolRef {
  toolId: string;
  name: string;
  module: string;
  system: string;
  access: ToolAccess;
}

export interface SkillResource {
  id: string;
  /** `file` is stored through the Files API; `template` is text kept on the version (a reply or memo skeleton). */
  kind: 'file' | 'template';
  name: string;
  description?: string;
  fileId?: string;
  size?: number;
  /** Set while the file is quarantined or unscanned: the skill loads without it. */
  blocked?: string;
  body?: string;
  addedAt: string;
  addedBy: string;
}

/** Where a generated line came from: a document section, a past case, run or chat, or a template. */
export interface SkillCitation {
  id: string;
  kind: 'document' | 'case' | 'run' | 'chat' | 'template' | 'description';
  label: string;
  detail?: string;
  href?: string;
  section: SkillSectionKey | 'use_when';
}

export interface SkillContent {
  /** Display name, e.g. "Hardship request triage". */
  name: string;
  /** Identifier, kebab-case, at most 64 characters. Becomes `name` in SKILL.md. */
  slug: string;
  /** What the model reads to decide to load the skill. At most 1,024 characters. Becomes `description` in SKILL.md. Empty allowed when `loading` is `always`. */
  useWhen: string;
  loading: SkillLoading;
  /** Markdown body: steps, rules, examples and the output format. */
  instructions: string;
  tools: SkillToolRef[];
  knowledgeBases: string[];
  /** Rules the platform adds to the turn while the skill is loaded, e.g. "Never quote a payoff figure older than today". */
  guardrails: string[];
  resources: SkillResource[];
}

export interface SkillTestRunSummary {
  runId: string;
  version: number;
  ranAt: string;
  passed: number;
  total: number;
}

export interface SkillVersion {
  version: number;
  state: SkillVersionState;
  editClass: SkillEditClass;
  note: string;
  changes: string[];
  savedBy: string;
  savedAt: string;
  content: SkillContent;
  /** Tokens the body adds to a turn when it loads. */
  tokens: number;
  reviewId?: string;
  publishedAt?: string;
  publishedBy?: string;
  testRun: SkillTestRunSummary | null;
}

export interface Skill {
  id: string;
  name: string;
  slug: string;
  useWhen: string;
  loading: SkillLoading;
  ownerTeam: string;
  status: SkillStatus;
  /** Newest version number, whatever its state. */
  version: number;
  publishedVersion: number | null;
  /** Set when the newest version is an unpublished draft or in review. */
  draftVersion: number | null;
  /** Agents that pin any version. */
  usedBy: number;
  liveAgents: number;
  toolCount: number;
  kbCount: number;
  /** Latest test run on the newest version, 0–1. */
  lastEvalPassRate: number | null;
  tokens: number;
  updatedAt: string;
  updatedBy: string;
  origin: SkillOrigin;
  pendingReviewId?: string;
}

export interface SkillTestCase {
  id: string;
  name: string;
  input: string;
  /** Reuses the agent eval checks: expected tool calls, must cite, must not say. */
  checks: EvalCheck[];
  source: 'generated' | 'manual' | 'case' | 'document' | 'imported';
  /** The case, run or document the input came from. */
  sourceRef?: string;
  createdAt: string;
  createdBy: string;
  lastOutcome: 'pass' | 'fail' | null;
}

export type SkillTestCaseInput = Pick<SkillTestCase, 'name' | 'input' | 'checks'> & { source?: SkillTestCase['source']; sourceRef?: string };

export interface SkillTestResult {
  caseId: string;
  caseName: string;
  status: 'pass' | 'fail';
  checks: EvalCheckResult[];
  failure?: string;
  reply: string;
  /** False when the runtime did not choose the skill for this input: the use-when line missed. */
  skillLoaded: boolean;
  toolsCalled: string[];
  latencyMs: number;
}

export interface SkillTestRun {
  id: string;
  version: number;
  ranAt: string;
  ranBy: string;
  passed: number;
  total: number;
  results: SkillTestResult[];
}

export interface SkillUsage {
  agentId: string;
  agentName: string;
  agentOwner: string;
  agentAvailability: import('./domain').AgentAvailability;
  pinnedVersion: number;
  latestPublished: number | null;
  upgradeAvailable: boolean;
  /** Why the agent cannot move to the latest version yet, e.g. it needs a tool the agent lacks. */
  upgradeBlocked?: string;
  loads7d: number;
  /** Share of the agent's turns in 7 days that loaded the skill, 0–1. */
  share7d: number;
  lastLoadedAt: string | null;
  attachedAt: string;
  attachedBy: string;
}

export interface SkillTrace {
  id: string;
  at: string;
  agentName: string;
  version: number;
  input: string;
  outcome: 'completed' | 'handed_off' | 'failed';
  toolCalls: string[];
  tookMs: number;
}

export interface SkillActivity {
  agents: string[];
  /** 14 days, oldest first; `counts` is loads per agent name. */
  loadsPerDay: { date: string; counts: Record<string, number>; total: number }[];
  loads30d: number;
  /** Loaded turns that completed without a hand-off or failure, 0–1. */
  successRate: number | null;
  samples: SkillTrace[];
}

/** What publishing the newest version needs, computed by the server. */
export interface SkillPublishCheck {
  canRequest: boolean;
  blockers: string[];
  editClass: SkillEditClass;
  approversNeeded: number;
}

export interface SkillDetail extends Skill {
  content: SkillContent;
  /** Newest first. */
  versions: SkillVersion[];
  tests: SkillTestCase[];
  /** Newest first. */
  runs: SkillTestRun[];
  usage: SkillUsage[];
  activity: SkillActivity;
  provenance: { origin: SkillOrigin; detail: string; citations: SkillCitation[] };
  pendingReview?: { id: string; version: number; editClass: SkillEditClass; approvals: number; needed: number };
  publishCheck: SkillPublishCheck;
}

export type SkillView = 'all' | 'published' | 'always' | 'drafts' | 'in_review' | 'deprecated' | 'unused';
export type SkillFilters = { status?: string[]; ownerTeam?: string[]; tools?: string[]; knowledgeBases?: string[]; origin?: string[]; loading?: string[] };
export type SkillViewCounts = Record<SkillView, number>;

export interface SkillCreateInput {
  name: string;
  useWhen: string;
  /** Defaults to `on_match`. */
  loading?: SkillLoading;
  instructions: string;
  ownerTeam: string;
  toolIds: string[];
  knowledgeBases: string[];
  guardrails: string[];
  tests?: SkillTestCaseInput[];
  origin: SkillOrigin;
  provenance?: { detail: string; citations: SkillCitation[] };
  /** Generation only: the AI gateway call that drafted it, kept on version 1 as evidence. */
  gatewayCallId?: string;
  /** Agents the author means to attach once published; shown to the reviewer. */
  targetAgentIds?: string[];
  requestReview?: boolean;
  reviewNote?: string;
}

/** Edits the newest draft, or opens one when the newest version is published. */
export interface SkillDraftPatch {
  name?: string;
  useWhen?: string;
  loading?: SkillLoading;
  instructions?: string;
  toolIds?: string[];
  knowledgeBases?: string[];
  guardrails?: string[];
  note?: string;
  /** The version the edit was made against; a newer one returns 409. */
  baseVersion: number;
}

// ── Generation ──────────────────────────────────────────────────────────────

export type SkillStartKind = 'describe' | 'document' | 'past_work' | 'template';

export type SkillStart =
  | { kind: 'describe'; text: string }
  | { kind: 'document'; documentIds: string[]; fileIds: string[] }
  | { kind: 'past_work'; itemIds: string[] }
  | { kind: 'template'; templateId: string; text?: string };

export interface SkillScope {
  targetAgentIds: string[];
  ownerTeam: string;
  toolIds: string[];
  knowledgeBases: string[];
  riskNotes: string;
}

export interface SkillGenerateInput {
  start: SkillStart;
  scope: SkillScope;
}

export interface SkillWarning {
  kind: 'tool_out_of_scope' | 'kb_out_of_scope' | 'agent_lacks';
  ref: string;
  message: string;
}

export interface GeneratedSkill {
  name: string;
  slug: string;
  useWhen: string;
  sections: Record<SkillSectionKey, string>;
  tools: SkillToolRef[];
  knowledgeBases: string[];
  guardrails: string[];
  citations: SkillCitation[];
  warnings: SkillWarning[];
  /** AI gateway alias and call id, so the draft's origin is auditable. */
  model: string;
  gatewayCallId: string;
}

export type SkillGenerateEvent =
  | { type: 'status'; text: string }
  | { type: 'field'; field: 'name' | 'useWhen'; value: string }
  | { type: 'section'; section: SkillSectionKey; delta: string }
  | { type: 'done'; skill: GeneratedSkill }
  | { type: 'error'; message: string };

export interface SkillRewriteInput {
  section: SkillSectionKey;
  current: string;
  instruction: string;
  name: string;
  scope: SkillScope;
}

export interface SkillGenerateOptions {
  templates: { id: string; name: string; description: string }[];
  documents: { id: string; title: string; kb: string; detail: string }[];
  /** Resolved cases, completed runs and chats that can seed a skill. */
  pastWork: { id: string; kind: 'case' | 'run' | 'chat'; title: string; detail: string; group: string; at: string }[];
  tools: SkillToolRef[];
  knowledgeBases: string[];
  agents: { id: string; name: string; owner: string; toolIds: string[]; collections: string[] }[];
  teams: string[];
  limits: SkillRuntimeLimits;
}

/** Runtime caps that apply to every agent (spec 11, 5.3). */
export interface SkillRuntimeLimits {
  maxPerTurn: number;
  maxAttached: number;
  /** Tokens of skill bodies one turn may load. */
  tokenBudget: number;
  useWhenMaxChars: number;
}

/** What attaching the draft would change on one target agent: the review step shows one per agent. */
export interface SkillImpact {
  agentId: string;
  agentName: string;
  skillsBefore: string[];
  skillsAfter: string[];
  /** Tools and knowledge bases the skill needs, split by whether the agent holds them. */
  toolsHeld: string[];
  toolsMissing: string[];
  kbsHeld: string[];
  kbsMissing: string[];
  guardrailsAdded: string[];
  tokens: number;
  attachable: boolean;
}

export interface SkillDraftForCheck {
  name: string;
  useWhen: string;
  loading?: SkillLoading;
  instructions: string;
  toolIds: string[];
  knowledgeBases: string[];
  guardrails: string[];
}

// ── Import and export ───────────────────────────────────────────────────────

export interface SkillImportPreview {
  fileId: string;
  fileName: string;
  format: 'skill_md' | 'folder_zip';
  name: string;
  slug: string;
  useWhen: string;
  instructions: string;
  resources: { name: string; size: number }[];
  /** `allowed-tools` from the frontmatter, matched to the bank's tool operations. */
  tools: { requested: string; toolId?: string; name?: string }[];
  warnings: string[];
  /** Any error refuses the import. */
  errors: string[];
}

// ── Reviews and agents ─────────────────────────────────────────────────────

/** Body of a `skill_publish` review. */
export interface SkillPublishRequest {
  skillId: string;
  skillName: string;
  ownerTeam: string;
  fromVersion: number | null;
  toVersion: number;
  editClass: SkillEditClass;
  requestedBy: string;
  note: string;
  changes: string[];
  testRun: SkillTestRunSummary | null;
  failing: string[];
  toolsAdded: string[];
  kbsAdded: string[];
  guardrails: string[];
  agents: { name: string; pinnedVersion: number | null }[];
  approvalsNeeded: number;
}

export interface AgentSkillPin {
  skillId: string;
  name: string;
  useWhen: string;
  loading: SkillLoading;
  pinnedVersion: number;
  latestPublished: number | null;
  status: SkillStatus;
  upgradeAvailable: boolean;
  upgradeBlocked?: string;
  loads7d: number;
  share7d: number;
  tokens: number;
}

export interface AgentSkills {
  agentId: string;
  pins: AgentSkillPin[];
  /** Published skills not attached, with whether the agent holds what each needs. */
  available: { skillId: string; name: string; useWhen: string; loading: SkillLoading; latestPublished: number; ownerTeam: string; attachable: boolean; missing: string[] }[];
  limits: SkillRuntimeLimits;
}

/** A skill the runtime loaded on a test turn. */
export interface LoadedSkill {
  skillId: string;
  name: string;
  version: number;
  /** The words in the message that matched its use-when line; "Always on" for always-on skills. */
  matched: string;
}

/** Scope of an agent that does not exist yet: what it will own and hold. */
export interface SkillCandidateScope {
  ownerTeam: string;
  toolIds: string[];
  knowledgeBases: string[];
}

/** A published skill an agent with the scope could pin, by version. Computed by the server. */
export interface SkillCandidate {
  skillId: string;
  name: string;
  useWhen: string;
  loading: SkillLoading;
  ownerTeam: string;
  tokens: number;
  /** Published and superseded versions, newest first; `missing` names what the agent would lack for that version. */
  versions: { version: number; current: boolean; missing: string[] }[];
}

export interface SkillCandidates {
  /** Skills with at least one version the agent could pin. */
  attachable: SkillCandidate[];
  /** Published skills of the owning team it could not pin, with the reason. */
  blocked: { skillId: string; name: string; kind: 'ownership' | 'access'; reason: string }[];
  limits: SkillRuntimeLimits;
}

export interface SkillOptions {
  teams: string[];
  tools: SkillToolRef[];
  knowledgeBases: string[];
  limits: SkillRuntimeLimits;
}
