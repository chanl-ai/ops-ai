import type { LifecycleStatus, ToolAccess } from './domain';

/**
 * Skills: versioned, reusable procedures an agent loads when a task matches its "use when" line. A skill adds
 * instructions, resources and guardrails; it never grants a tool or knowledge base the agent does not already
 * hold. Portable as an Agent Skills folder (`SKILL.md` with `name` and `description` frontmatter, plus
 * resources). Spec 11.
 */

import type { StepValue } from '@/components/shared/instruction-document/document-model';
import type { Blocker, PublishBlocker, PublishWarning } from './references';

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
  /** What the agent says when one of these guardrails refuses: a next step, not just a no. Absent uses the platform's sentence. */
  refusal?: string;
  /** Jobs picked on their own from the chat's / menu, each loaded with the instructions as the shared overview. */
  parts?: SkillPartContent[];
  /** What the skill asks for when it starts; absent when it takes none. A skill with parts takes them on each part. */
  inputs?: SkillInputField[];
  /** When not to use the skill. */
  notWhen?: string;
  /** The skill as written in the text editor; absent on a skill saved as a list of steps. */
  source?: string;
  /** Numbered steps the agent follows in order; a skill has steps or parts, never both. */
  steps?: StepValue[];
  /** The ways the skill may end beside done and failed: a name and what it means. */
  exit?: Record<string, string>;
  /** What the skill hands back when it ends. */
  returns?: SkillReturnField[];
  /** Lines that say the skill went well. */
  success?: string[];
}

/** One result a skill with steps hands back. */
export interface SkillReturnField {
  name: string;
  type: 'text' | 'number' | 'yes_no';
  required: boolean;
  description: string;
}

/** One part of a skill as saved in its version. */
export interface SkillPartContent {
  slug: string;
  name: string;
  useWhen: string;
  instructions: string;
  inputs: SkillInputField[];
  /** Some of the skill's own tools. */
  toolIds: string[];
  /** Most tokens it may hold when loaded; absent takes the reply's whole skill budget. */
  budget?: number;
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
  /** Who made it live. */
  publishedBy?: string;
  /** Who asked for the publish; null for a version no request published. */
  requestedBy?: string | null;
  /** Who approved it; null when the team's publish policy let it go live without a review. */
  approvedBy?: string | null;
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

/** One input a skill or part asks for when picked from the chat's / menu. */
export interface SkillInputField {
  name: string;
  type: 'string';
  description: string;
  required: boolean;
}

/** One part of a skill with parts, as the / menu offers it. */
export interface SkillPartSummary {
  slug: string;
  name: string;
  useWhen: string;
  inputs: SkillInputField[];
}

/** A published skill the chat's / menu offers for one agent: its inputs or parts, and `locked` when the agent lacks
 *  a tool or knowledge base it needs (named in `needs`). */
export interface ChatMenuSkill extends Skill {
  inputs?: SkillInputField[];
  parts?: SkillPartSummary[];
  locked?: boolean;
  needs?: string[];
}

export type SkillCheckType = 'calls_tool' | 'not_calls_tool' | 'cites' | 'reply_contains' | 'reply_not_contains' | 'refuses' | 'extracts' | 'rubric';

/** One argument a skill test's tool call must carry. */
export interface SkillArgMatcher {
  path: string;
  equals: string;
}

/** One expectation on a skill test; only the fields its `type` needs are set. */
export interface SkillCheck {
  type: SkillCheckType;
  tool?: string;
  args?: SkillArgMatcher[];
  source?: string;
  section?: string;
  text?: string;
  field?: string;
  value?: string;
}

/** Result of one skill test check; `advisory` is a rubric check, recorded and never pass or fail. */
export interface SkillCheckResult {
  label: string;
  status: 'pass' | 'fail' | 'advisory';
  detail?: string;
}

export interface SkillTestCase {
  id: string;
  name: string;
  input: string;
  /** Expected tool calls, must cite, must not say. */
  checks: SkillCheck[];
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
  checks: SkillCheckResult[];
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
  /** The agent's owning team id; the console names it from the person's teams list. */
  agentTeamId: string | null;
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
  blockers: Blocker[];
  /** Each blocker with where it is: a step's number when it is on a step. */
  problems?: PublishBlocker[];
  /** What the check noticed and does not block on, placed like a problem; absent on an older service. */
  warnings?: PublishWarning[];
  editClass: SkillEditClass;
  approversNeeded: number;
}

export interface SkillDetail extends Skill {
  content: SkillContent;
  /** The text the editor shows: `content.source`, or a skill's stored steps written as text by the service. */
  text: string;
  /** With `version`, the copy a draft save names as its base (`baseOf`). */
  digest: string;
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
  refusal?: string;
  parts?: SkillPartContent[];
  /** What the skill asks for when it starts. */
  inputs?: SkillInputField[];
  /** When not to use the skill. */
  notWhen?: string;
  /** Numbered steps the agent follows in order; a skill has steps or parts, never both. */
  steps?: StepValue[];
  /** The skill written as text: the service reads its steps from it and sets `instructions` to it. */
  source?: string;
  /** The ways the skill may end beside done and failed: a name and what it means. */
  exit?: Record<string, string>;
  /** What the skill hands back when it ends. */
  returns?: SkillReturnField[];
  /** Lines that say the skill went well. */
  success?: string[];
  note?: string;
  /** The copy the edit was made on (`baseOf` the skill as read); a save from an older copy returns 409 `stale_base`. */
  baseVersion: number;
  baseDigest: string;
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
  /** The published text this request replaces ('' for a first version) and the text it publishes, kept as they were
   * when the request opened. Absent on a request opened before they were kept. */
  textBefore?: string;
  textAfter?: string;
  /** The hints on the new text's lines; none of them blocks the publish. */
  hints: { line: number; message: string }[];
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

// ── Text editor ─────────────────────────────────────────────────────────────

/** A hint or an error on a line (from 1) of a skill's text. */
export interface SkillTextNote {
  line: number;
  message: string;
}

/** One line of a skill's text as the service reads it. */
export interface SkillTextLine {
  line: number;
  kind: 'text' | 'step' | 'if' | 'else' | 'stop' | 'blank';
  /** The step (from 1) the line is part of. */
  step: number | null;
  /** An `if` line: checked on the tool's result, or decided by the agent from the conversation. */
  how: 'checked' | 'agent' | null;
  /** The line runs this tool (`@tool:id`). */
  tool: string | null;
  /** How many path levels in the line is, as the service's reader counts its indent. */
  depth?: number;
  /** The keyword the line is written with and where it sits after the indent, past any list marker; set even when
   * the line reads as text (an `if …:` with nothing indented under it yet). */
  keyword?: { word: 'if' | 'else' | 'stop'; start: number; end: number } | null;
}

/** POST /v1/skills/{id}/text: how a text reads, as a save will read it. Hints never block; errors block a publish. */
export interface SkillTextReading {
  hints: SkillTextNote[];
  errors: (SkillTextNote & { id: string })[];
  uses: { tools: number; knowledge: number; skills: number; agents: number; workflows: number };
  lines: SkillTextLine[];
  /** What to offer after `if ` for each mentioned tool, from what it returns. */
  phrases: Record<string, string[]>;
  steps: number;
  stepLines: number[];
}
