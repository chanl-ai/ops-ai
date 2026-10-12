import type { AgentGuardrails } from './domain';

/** A value the runtime fills into instructions, written `{customer.first_name}`. */
export interface PromptVariable {
  key: string;
  label: string;
  example: string;
  /** Where the runtime reads it from. */
  source: string;
}

// ── Generator ────────────────────────────────────────────────────────────────

export type Verbosity = 'brief' | 'standard' | 'detailed';
export type OutputFormat = 'email' | 'json' | 'bullets' | 'memo' | 'chat';

/** The feature fields of the prompt generator, grouped as its steps are. */
export interface PromptSpec {
  purpose: { role: string; serves: string; goals: string[]; outOfScope: string[] };
  behaviour: {
    tone: string;
    readingLevel: string;
    languages: string[];
    verbosity: Verbosity;
    whenUnsure: AgentGuardrails['whenUnsure'];
    escalationTriggers: string[];
  };
  process: { steps: string[]; decisionRules: string[]; requiredChecks: string[] };
  toolsKnowledge: { toolUse: { tool: string; when: string }[]; knowledge: string[]; citationRule: string; neverWithTools: string[] };
  compliance: { disclosures: string[]; forbiddenPhrases: string[]; piiHandling: string; regulatoryNotes: string };
  output: { format: OutputFormat; structure: string; variables: string[]; examples: { input: string; output: string }[] };
}

/** What the generated prompt is checked against: the agent's grants, not what the prompt claims. */
export interface PromptContext {
  model: string;
  grantedTools: string[];
  collections: string[];
}

export interface PromptSection {
  id: string;
  title: string;
  body: string;
}

export type PromptLintRule = 'conflicting_rules' | 'unknown_variable' | 'tool_not_granted' | 'missing_citation_rule' | 'too_long' | 'unknown_block';

export interface PromptLintFinding {
  id: string;
  rule: PromptLintRule;
  severity: 'error' | 'warning';
  message: string;
  sectionId?: string;
  /** The section body after the fix; absent when the fix needs a person. */
  fix?: { label: string; sectionId: string; body: string };
}

export interface PromptAnalysis {
  tokens: number;
  /** Prompt input cost per 1,000 runs at the model's list price, in USD. */
  costPer1kRunsUsd: number;
  findings: PromptLintFinding[];
}

export type PromptStreamEvent =
  | { type: 'section'; section: Omit<PromptSection, 'body'> }
  | { type: 'delta'; sectionId: string; text: string }
  | { type: 'done'; analysis: PromptAnalysis };

export interface RewriteSectionInput {
  section: PromptSection;
  instruction: string;
  context: PromptContext;
}
