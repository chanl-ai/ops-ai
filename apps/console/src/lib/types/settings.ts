/** Team settings: members, notification routing, webhooks, API keys and usage. Scoped to the current team. */

export type MemberRole = 'admin' | 'builder' | 'approver' | 'viewer';

export interface Member {
  id: string;
  name: string;
  email: string;
  role: MemberRole;
  teamId: string;
  team: string;
  status: 'active' | 'invited';
  lastActiveAt?: string;
  invitedAt?: string;
}

export type MemberFilters = { role?: string[]; status?: string[]; teamId?: string[] };

export interface InviteInput {
  emails: string[];
  role: MemberRole;
  /** Platform scope only: the team to invite into. Ignored inside a team, which always invites into itself. */
  teamId?: string;
}

// ── Notifications ──────────────────────────────────────────────────────────

export type NotificationEvent = 'approval_waiting' | 'sla_at_risk' | 'publish_request' | 'mailbox_disconnected';

/** A place notifications can go. The list comes from the API, so new channels need no UI change. */
export interface NotificationChannel {
  id: string;
  name: string;
  connected: boolean;
  /** Where messages land, e.g. the Teams channel or the sender address. */
  detail?: string;
  /** Approvals can be approved or rejected from this channel without opening Ops AI. */
  actionable: boolean;
}

export interface NotificationRule {
  event: NotificationEvent;
  label: string;
  description: string;
  channelIds: string[];
}

export interface NotificationSettings {
  version: number;
  updatedAt: string;
  updatedBy: string;
  channels: NotificationChannel[];
  rules: NotificationRule[];
}

export interface NotificationSettingsInput {
  /** The version being edited; a newer saved version rejects the save. */
  version: number;
  rules: { event: NotificationEvent; channelIds: string[] }[];
}

// ── Webhooks ───────────────────────────────────────────────────────────────

export interface Webhook {
  id: string;
  name: string;
  url: string;
  events: string[];
  status: 'active' | 'paused' | 'failing';
  secretPrefix: string;
  lastDeliveryAt?: string;
  /** Share of the last 7 days' deliveries that were delivered; absent when there were none. */
  successRate7d?: number;
  /** Deliveries attempted in the last 7 days, counted from the same history the deliveries sheet shows. */
  deliveries7d: number;
  createdAt: string;
  team: string;
}

export interface WebhookInput {
  name: string;
  url: string;
  events: string[];
}

export type DeliveryStatus = 'success' | 'failed' | 'pending' | 'skipped';

export interface WebhookDelivery {
  id: string;
  event: string;
  status: DeliveryStatus;
  statusCode?: number;
  attempts: number;
  durationMs?: number;
  at: string;
  error?: string;
  payload?: Record<string, unknown>;
  responseBody?: string;
}

export type DeliveryFilters = { status?: string[] };

// ── API keys ───────────────────────────────────────────────────────────────

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  createdBy: string;
  createdAt: string;
  lastUsedAt?: string;
  expiresAt?: string;
  team: string;
}

export interface ApiKeyInput {
  name: string;
  scopes: string[];
  expiresInDays: number | null;
  /** Platform scope only: the team the key acts for. Ignored inside a team. */
  teamId?: string;
}

// ── Usage ──────────────────────────────────────────────────────────────────

export type UsageDays = 7 | 30;

export interface UsageRow {
  key: string;
  name: string;
  /** Team of a workflow row. */
  team?: string;
  runs: number;
  toolCalls: number;
  tokens: number;
  /** Model cost in CAD. */
  modelCost: number;
  costPerRun: number;
  /** Share of the period's model cost, 0–1. */
  share: number;
}

export interface UsageReport {
  days: UsageDays;
  /** `all` for the Platform team, which sees every team; `team` otherwise. */
  scope: 'all' | 'team';
  teamName: string;
  totals: { runs: number; toolCalls: number; tokens: number; modelCost: number; costTrendPct: number };
  /** Chart series: teams when scope is `all`, workflows otherwise. */
  series: { key: string; label: string }[];
  /** One point per day; each series key holds that day's model cost in CAD. */
  daily: ({ date: string } & Record<string, number | string>)[];
  byTeam: UsageRow[];
  byWorkflow: UsageRow[];
}

export interface SettingsLookups {
  roles: { value: MemberRole; label: string; description: string }[];
  webhookEvents: { value: string; label: string }[];
  apiScopes: { value: string; label: string }[];
}
