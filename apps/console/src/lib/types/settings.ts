/** Team settings: members, notification routing, webhooks, API keys and usage. Scoped to the current team. */

import type { BulkResult } from './domain';

export type MemberRole = 'admin' | 'builder' | 'approver' | 'viewer';

/** The signed-in person and their role on each of their teams (platform-service GET /v1/me). */
export interface Me {
  user: { id: string; email: string; name: string };
  tenantId: string;
  /** The workspace's own name (platform-service), for the header. */
  tenantName?: string;
  teams: { id: string; name: string; role: MemberRole }[];
}

/** One action the person may take, as `can()` decides it (platform-service GET /v1/me/permissions, c-186). */
export interface EffectivePermission {
  area: string;
  action: string;
  scope: 'all' | 'own';
  /** Held in the Security team whichever team a request acts in. */
  securityTeamOnly: boolean;
  /** The roles that grant it, and whether the person holds each directly or through a team. */
  roles: { id: string; name: string; via: 'person' | 'team' }[];
}

/** What the person may do in each of their teams, and in every team at once (`workspace`, from a `*` role). */
export interface MyPermissions {
  personId: string;
  permissionVersion: number;
  workspace: EffectivePermission[];
  teams: { teamId: string; teamName: string; permissions: EffectivePermission[] }[];
}

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
  /** Invited members: the token of their invitation link, opened at /invite/[token]. */
  inviteToken?: string;
  /** The person's own id once joined; their page is /access/people/[userId]. */
  userId?: string | null;
  /** Roles held in every team, by name: where access beyond the team role comes from (platform-service). */
  workspaceRoles?: string[];
}

/** A role of the workspace (GET /v1/roles): what it grants and how many hold it. */
export interface RoleSummary {
  id: string;
  name: string;
  builtin: boolean;
  description: string;
  permissionCount: number;
  assignmentCount: number;
}

/** A role and its grid (GET /v1/roles/{id}): every area, each action's scope or null when not granted. */
export interface RoleDetail extends RoleSummary {
  grid: { area: string; actions: Record<string, 'own' | 'all' | null> }[];
}

/** One action checked for one person (POST /v1/access/check, c-150): allowed with the granting roles, or refused. */
export interface AccessCheck {
  personId: string;
  teamId: string;
  area: string;
  action: string;
  allowed: boolean;
  scope: 'own' | 'all' | null;
  grantedBy: { id: string; name: string; via: 'person' | 'team' }[];
  refusedBy: { code: string; reason: string } | null;
}

/** The signed-in person's own answer for one action (GET /v1/me/why): why it is refused and who to ask. */
export type WhyNot = AccessCheck & { roles: { id: string; name: string }[]; askable: string[] };

/** What a person may do (GET /v1/people/{id}/permissions), with their name and address. */
export type PersonPermissions = MyPermissions & { name?: string | null; email?: string | null };

export type MemberFilters = { role?: string[]; status?: string[]; teamId?: string[] };

/** An invite's result: per email, done or skipped with why, and each new invite's link token, shown once. */
export interface InviteResult extends BulkResult {
  invites?: { email: string; token: string }[];
}

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

/** Who in a team may take an action: the roles that grant it and the people holding them (GET /v1/access/holders). */
export interface Holders {
  teamId: string;
  roles: { id: string; name: string }[];
  holders: { id: string; name: string; email: string; roles: string[] }[];
}
