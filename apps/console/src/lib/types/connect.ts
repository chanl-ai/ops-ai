import type { Risk, WorkflowToolApproval } from './domain';

/**
 * Connect: the workspace MCP URL that staff paste into their own assistant, the workflows exposed on it as
 * tools, and the assistants that have connected. Exposing a workflow is an MCP deployment (spec 01 5.9).
 */

export type ConnectRange = '24h' | '7d' | '30d';

export interface ConnectJourney {
  copiedUrl: boolean;
  installedClient: boolean;
  firstCall: boolean;
}

/** How a workflow behaves when an assistant calls it, from its approval rules. */
export type ConnectApproval = WorkflowToolApproval;

/** Who may call an exposed workflow: staff assistants over the MCP URL, or the platform's own agents as a tool. */
export type ConnectAudience = 'assistants' | 'agents';

export interface ConnectTool {
  workflowId: string;
  name: string;
  /** The tool name assistants see, snake case. */
  toolId: string;
  tier: Risk;
  approval: ConnectApproval;
  /** Calls over MCP in the selected range. */
  calls: number;
  /** True when exposed to assistants (an active MCP deployment). */
  exposed: boolean;
  /** Every audience the workflow is exposed to; `agents` registers a workflow tool, never an MCP deployment. */
  exposedTo: ConnectAudience[];
  /** Agents granted the workflow tool; it cannot be withdrawn from agents while any hold it. */
  grantedAgents: number;
  /** The MCP deployment behind the switch, when one exists (active or paused). */
  deploymentId?: string;
  /** Set when the switch is disabled, e.g. the workflow has no published version. */
  disabledReason?: string;
}

/** Whether the assistant's user was proven by the workspace IdP or only asserted by the client. */
export type IdentityAssurance = 'attested' | 'claimed';

export interface ConnectedAssistant {
  id: string;
  client: string;
  person: string;
  team: string;
  lastCallAt: string;
  calls: number;
  assurance: IdentityAssurance;
}

export interface ConnectSettings {
  /** Teams whose members may connect an assistant; empty means every team. */
  allowedTeams: string[];
  /** Whether a newly published workflow is exposed on the MCP URL. */
  defaultExposed: boolean;
  tokenLifetimeHours: number;
  updatedAt: string;
  updatedBy: string;
}

export interface ConnectOverview {
  url: string;
  authLabel: string;
  journey: ConnectJourney;
  /** True once any assistant has made a call. */
  live: boolean;
  range: ConnectRange;
  stats: { calls: number; held: number; failed: number; assistants: number };
  series: { date: string; calls: number; held: number; failed: number }[];
  /** Up to 5, exposed first, then by calls. */
  tools: ConnectTool[];
  workflowCount: number;
  exposedCount: number;
  /** Up to 5, most recent call first. */
  assistants: ConnectedAssistant[];
  assistantCount: number;
  settings: ConnectSettings;
  /** Option list for "who may connect". */
  teams: string[];
}

export type ConnectSettingsInput = Pick<ConnectSettings, 'allowedTeams' | 'defaultExposed' | 'tokenLifetimeHours'>;
