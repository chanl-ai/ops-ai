/** Team settings: members, notification routing, webhooks, API keys and usage. Scoped to the current team. */

import type { OpsAI } from '@chanl-ai/ops-ai';

import type { Narrow } from './served';

// Entity types come from the generated SDK (platform-service's OpenAPI document), so a field renamed there fails the console's typecheck.
type Platform = OpsAI['raw']['platform'];
type Reply<K extends keyof Platform> = Awaited<ReturnType<Platform[K]>>;
type Body<K extends keyof Platform> = NonNullable<NonNullable<Parameters<Platform[K]>[0]>['body']>;

export type MemberRole = 'admin' | 'builder' | 'approver' | 'viewer' | 'chat_user';

/** The signed-in person and their role on each of their teams (platform-service GET /v1/me). */
export type Me = Narrow<Reply<'me_me'>, { teams: { id: string; name: string; role: MemberRole }[]; permissions: MyPermissions }>;

/** One action the person may take, as `can()` decides it (platform-service GET /v1/me/permissions). */
export type EffectivePermission = Reply<'me_my_permissions'>['workspace'][number];

/** What the person may do in each of their teams, and in every team at once (`workspace`, from a `*` role). */
export type MyPermissions = Reply<'me_my_permissions'>;

export type Member = Narrow<Reply<'members_list_members'>['data'][number], { role: MemberRole }> & {
  /** Not returned by platform-service yet. */
  lastActiveAt?: string;
  /** Invited members: the token of their invitation link, opened at /invite/[token]. platform-service does not return it on the list yet. */
  inviteToken?: string;
};

/** A role of the workspace (GET /v1/roles): what it grants and how many hold it. */
export type RoleSummary = Reply<'roles_list_roles'>['data'][number];

type Grid = { area: string; actions: Record<string, 'own' | 'all' | null> }[];

/** A role and its grid (GET /v1/roles/{id}): every area, each action's scope or null when not granted. */
export type RoleDetail = Narrow<Reply<'roles_read_role'>, { grid: Grid }>;

/** A new custom role (POST /v1/roles): from nothing, from `permissions`, or a copy of `copyOf`. */
export type RoleInput = Body<'roles_create_role'>;

/** The answer to a create: the role, and the cells of the copied role a custom role may not hold, left out. */
export type RoleCreated = Narrow<Reply<'roles_create_role'>, { grid: Grid }>;

/** A custom role given to a person in one of their teams (GET /v1/people/{id}/role-grants). */
export type RoleGrant = Reply<'people_person_role_grants'>['data'][number];

/** Who holds a role and in which team (GET /v1/roles/{id}/holders). */
export type RoleHolder = Reply<'roles_role_holders'>['data'][number];

/** One cell a role holds after a save (PUT /v1/roles/{id}/permissions). */
export type RoleCell = NonNullable<Body<'roles_create_role'>['permissions']>[number];

/** One action checked for one person (POST /v1/access/check): allowed with the granting roles, or refused. */
export type AccessCheck = Reply<'access_check_access'>;

/** The signed-in person's own answer for one action (GET /v1/me/why): why it is refused and who to ask. */
export type WhyNot = Reply<'me_why_not'>;

/** What a person may do (GET /v1/people/{id}/permissions), with their name and address. */
export type PersonPermissions = Reply<'people_person_permissions'>;

export type MemberFilters = { role?: string[]; status?: string[]; teamId?: string[] };

/** An invite's result: per email, done or skipped with why, and each new invite's link token, shown once. */
export type InviteResult = Reply<'members_invite_members'>;

/** A new link invite to each member who cannot sign in: `mailed` names who it went to; the link itself is never returned. */
export type ReinviteResult = Reply<'members_reinvite_members'>;

export type InviteInput = Narrow<Body<'members_invite_members'>, { role: MemberRole }> & {
  /** Platform scope only: the team to invite into. Ignored inside a team, which always invites into itself. */
  teamId?: string;
};

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

export type ApiKey = Reply<'api_keys_list_api_keys'>['data'][number];

/** `scopes` names what the console offers (`runs:write`); the client sends the service its `read` and `write`. */
export type ApiKeyInput = Narrow<Body<'api_keys_create_api_key'>, { scopes: string[] }> & {
  /** Platform scope only: the team the key acts for. Ignored inside a team. */
  teamId?: string;
};

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
export type Holders = Reply<'access_access_holders'>;
