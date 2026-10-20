/** An agent's chat served to pages on other origins (agents-service `/v1/widget-deployments`, c-117). */
export interface WidgetDeployment {
  id: string;
  name: string;
  agentId: string;
  /** The published version it serves; a newer one is served only after "Serve the newest version". */
  agentVersion: number;
  /** Exact `scheme://host[:port]` origins allowed to embed it. */
  origins: string[];
  paused: boolean;
  /** Set once, never cleared (c-130): a retired embed answers no page and cannot be changed. */
  retiredAt?: string | null;
  /** Conversations started on it in the last 7 days, and when one last had a message (c-130). */
  conversations7d?: number;
  lastUsedAt?: string | null;
  /** Unrevoked mint keys. */
  activeKeys?: number;
  teamId: string;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
}

export interface WidgetDeploymentInput {
  name: string;
  agentId: string;
  origins: string[];
}

export interface WidgetDeploymentPatch {
  name?: string;
  origins?: string[];
  paused?: boolean;
  /** One way: there is no un-retire. */
  retired?: boolean;
  /** The agent version the embed answers from: a number pins it, `latest` follows each new publish. */
  serves?: { kind: 'agent'; id: string; version: number | 'latest' };
}

/** A key the bank's server mints this deployment's sessions with (c-131). The secret is shown once, at creation. */
export interface WidgetMintKey {
  id: string;
  name: string;
  createdBy: string;
  createdAt: string;
  lastUsedAt: string | null;
  revokedAt: string | null;
  /** Every key ends; it mints nothing after this (90 days unless chosen otherwise, up to a year). */
  expiresAt: string | null;
}

export interface CreatedWidgetMintKey {
  key: WidgetMintKey;
  /** `wk.<tenant>.<key id>.<secret>`; only its hash is kept, so it cannot be shown again. */
  secret: string;
}
