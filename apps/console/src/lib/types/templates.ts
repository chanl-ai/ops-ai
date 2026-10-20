import type { AgentGuardrails, Channel } from './domain';
import type { EvalCaseInput } from './evals';

export type TemplateCategory =
  | 'Intake and triage'
  | 'Drafting'
  | 'Documents'
  | 'Knowledge'
  | 'Risk and compliance'
  | 'Internal'
  | 'Start from scratch';

export type TemplateRiskTier = 'low' | 'medium' | 'high';

/** A published template version is immutable; a team's submission waits for the platform team in review. */
export type TemplateStatus = 'published' | 'in_review' | 'rejected';

export interface TemplateTool {
  /** Tool name in the catalog, e.g. `get_transactions`. */
  name: string;
  /** Why the template expects it, shown on the card and in Configure. */
  purpose: string;
  access: 'read' | 'write';
}

export interface AgentTemplate {
  id: string;
  name: string;
  category: TemplateCategory;
  /** One line on the card. */
  summary: string;
  version: number;
  status: TemplateStatus;
  /** Templates are owned by the platform team; a team submission names the team that sent it. */
  ownerTeam: string;
  submittedBy?: string;
  riskTier: TemplateRiskTier;
  role: string;
  model: string;
  channels: Channel[];
  expectedTools: TemplateTool[];
  /** Knowledge base names the instructions assume. */
  expectedKnowledge: string[];
  starterTestCount: number;
  /** Agents created from any version of it. */
  agentCount: number;
  updatedAt: string;
}

export interface TemplateVersion {
  version: number;
  note: string;
  publishedAt: string;
  publishedBy: string;
}

export interface AgentTemplateDetail extends AgentTemplate {
  description: string;
  instructions: string;
  guardrails: AgentGuardrails;
  example: { input: string; output: string };
  starterTests: EvalCaseInput[];
  versions: TemplateVersion[];
  /** Expected knowledge bases that do not exist in this workspace. Computed by the server. */
  missingKnowledge: string[];
  /** Expected tools the current team cannot grant. Computed by the server. */
  unavailableTools: string[];
  /** Published skills the template's author recommends attaching; the wizard preselects the attachable ones. */
  suggestedSkills: TemplateSkillSuggestion[];
}

export interface TemplateSkillSuggestion {
  skillId: string;
  name: string;
  /** One line on why it fits, shown in the Skills step. */
  reason: string;
}

/** A skill pinned at a published version when the agent is created. */
export interface SkillPinInput {
  skillId: string;
  version: number;
}

export type TemplateFilters = { category?: string[]; riskTier?: string[]; status?: string[] };

/** One request creates the agent at version 1 from a template version and, optionally, its starter tests. */
export interface CreateFromTemplateInput {
  templateId: string;
  templateVersion: number;
  name: string;
  model: string;
  collections: string[];
  toolIds: string[];
  instructions: string;
  guardrails: AgentGuardrails;
  includeStarterTests: boolean;
  /** 422 when the agent will not hold a tool or knowledge base a pinned version needs. */
  skills: SkillPinInput[];
}

export interface CreateFromTemplateResult {
  agentId: string;
  agentName: string;
  testsAdded: number;
  skillsAttached: number;
}

/** "Save agent as template": sends the agent's current version to the platform team for review. */
export interface TemplateSubmissionInput {
  agentId: string;
  name: string;
  category: TemplateCategory;
  summary: string;
  note: string;
}

/** What a template carries, shown in the gallery preview and in a submission review. */
export interface TemplateContent {
  role: string;
  model: string;
  channels: Channel[];
  instructions: string;
  guardrails: AgentGuardrails;
  expectedTools: TemplateTool[];
  expectedKnowledge: string[];
  suggestedSkills: TemplateSkillSuggestion[];
}

export interface TemplateDiffRow {
  field: string;
  /** On the source agent. */
  agent: string;
  /** In the template. */
  template: string;
}

/** Body of a `template_submission` review. The platform team decides; the submitter cannot approve. */
export interface TemplateSubmissionRequest {
  templateId: string;
  templateName: string;
  category: TemplateCategory;
  summary: string;
  riskTier: TemplateRiskTier;
  note: string;
  submittedBy: string;
  submittedTeam: string;
  sourceAgentId: string;
  sourceAgentName: string;
  /** The agent version the template copies. */
  sourceVersion: number;
  /** The agent's version when the review is read; newer than `sourceVersion` when it changed after submitting. */
  agentVersionNow: number;
  /** Instructions on the agent now, set only when they differ from the copied ones. */
  agentInstructionsNow?: string;
  content: TemplateContent;
  /** Fields where the template differs from the agent it was made from. */
  diff: TemplateDiffRow[];
}
