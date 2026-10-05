import type { AuditEntry } from '@/lib/types/governance';
import type { NotificationSettings, SettingsLookups, UsageReport, UsageRow, WebhookDelivery } from '@/lib/types/settings';

import { ApiError } from '../../contract';
import type { SettingsApi } from '../../settings-contract';
import * as F from '../fixtures';
import { bulk, field, id, list, notFound, respond } from '../runtime';
import { teamDirectory } from '../teams';
import { seedApiKeys, seedDeliveries, seedMembers, seedNotifications, seedUsage, seedWebhooks } from './seed';

export type AuditLog = (e: Pick<AuditEntry, 'action' | 'target' | 'summary'> & Partial<Pick<AuditEntry, 'diff' | 'reason'>>) => void;

const LOOKUPS: SettingsLookups = {
  roles: [
    { value: 'admin', label: 'Admin', description: 'Manages members, keys, webhooks and access for the team' },
    { value: 'builder', label: 'Builder', description: 'Edits agents and workflows and requests publishes' },
    { value: 'approver', label: 'Approver', description: 'Decides reviews and drafted actions' },
    { value: 'viewer', label: 'Viewer', description: 'Reads everything in the team, changes nothing' },
  ],
  webhookEvents: [
    { value: 'review.decided', label: 'Review decided' },
    { value: 'run.completed', label: 'Run completed' },
    { value: 'run.failed', label: 'Run failed' },
    { value: 'case.closed', label: 'Case closed' },
    { value: 'call.denied', label: 'Gateway call denied' },
    { value: 'access.changed', label: 'Access changed' },
    { value: 'audit.created', label: 'Audit entry created' },
    { value: 'mailbox.disconnected', label: 'Mailbox disconnected' },
  ],
  apiScopes: [
    { value: 'runs:write', label: 'Start runs' },
    { value: 'runs:read', label: 'Read runs' },
    { value: 'logs:read', label: 'Read tool-call logs' },
    { value: 'audit:read', label: 'Read the audit log' },
    { value: 'usage:read', label: 'Read usage and cost' },
  ],
};

const ROLE_LABEL = Object.fromEntries(LOOKUPS.roles.map((r) => [r.value, r.label]));

/** Team settings. Members, webhooks, keys and usage follow the current team; Platform sees every team. */
export function createSettingsMock({ log, me }: { log: AuditLog; me: string }): SettingsApi {
  const teamName = (tid: string) => teamDirectory.all().find((t) => t.id === tid)?.name ?? tid;
  const members = seedMembers(teamDirectory.all());
  const notifications: Record<string, NotificationSettings> = {};
  const webhooks = seedWebhooks(teamName);
  const deliveries: Record<string, WebhookDelivery[]> = {};
  const historyOf = (w: (typeof webhooks)[number]) => (deliveries[w.id] ??= seedDeliveries(strip(w), w.volume));
  /** List stats come from the same history the deliveries sheet pages through, so the two always agree. */
  const withStats = (w: (typeof webhooks)[number]) => {
    const { volume: _v, ...rest } = strip(w);
    void _v;
    const since = Date.now() - 7 * 86_400_000;
    const recent = historyOf(w).filter((d) => new Date(d.at).getTime() >= since);
    return {
      ...rest,
      deliveries7d: recent.length,
      successRate7d: recent.length ? recent.filter((d) => d.status === 'success').length / recent.length : undefined,
      lastDeliveryAt: historyOf(w)[0]?.at,
    };
  };
  const keys = seedApiKeys(teamName);
  const usage = seedUsage();

  const all = () => teamDirectory.current().scope === 'all';
  /** Platform may create in any team; a team always creates in itself. */
  const targetTeam = (tid?: string) => {
    if (!all() || !tid) return teamDirectory.current();
    return teamDirectory.all().find((t) => t.id === tid) ?? notFound('Team');
  };
  const scoped = <T extends { teamId: string }>(rows: T[]) => (all() ? rows : rows.filter((r) => r.teamId === teamDirectory.current().id));
  const strip = <T extends { teamId: string }>(r: T) => {
    const { teamId: _drop, ...rest } = r;
    void _drop;
    return rest;
  };

  return {
    members: {
      list: (p) => respond((m) => list(scoped(members), p, { text: (x) => `${x.name} ${x.email}`, value: field, facetKeys: ['role', 'status', 'teamId'] }, m)),
      invite: (input) =>
        respond(() => {
          const t = targetTeam(input.teamId);
          const res = bulk(input.emails, (email) => {
            const e = email.trim().toLowerCase();
            if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e)) return 'Not an email address';
            if (!e.endsWith('@northfieldbank.com')) return 'Outside northfieldbank.com';
            if (members.some((x) => x.email === e && x.teamId === t.id)) return `Already in ${t.name}`;
            const name = e.split('@')[0].split('.').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');
            members.unshift({ id: id('mem'), name, email: e, role: input.role, teamId: t.id, team: t.name, status: 'invited', invitedAt: new Date().toISOString() });
            log({ action: 'created', target: { type: 'member', name: e, href: '/settings/members' }, summary: `Invited to ${t.name} as ${ROLE_LABEL[input.role]}`, diff: [{ field: 'Role', after: ROLE_LABEL[input.role] }] });
          });
          return res;
        }),
      setRole: (ids, role) =>
        respond(() =>
          bulk(ids, (mid) => {
            const x = members.find((y) => y.id === mid);
            if (!x) return 'Not found';
            if (x.role === role) return `Already ${ROLE_LABEL[role]}`;
            if (x.role === 'admin' && members.filter((y) => y.teamId === x.teamId && y.role === 'admin' && !ids.includes(y.id)).length === 0) return `Last admin of ${x.team}`;
            log({ action: 'edited', target: { type: 'member', name: x.name, href: '/settings/members' }, summary: 'Changed role', diff: [{ field: 'Role', before: ROLE_LABEL[x.role], after: ROLE_LABEL[role] }] });
            x.role = role;
          }),
        ),
      remove: (ids) =>
        respond(() =>
          bulk(ids, (mid) => {
            const i = members.findIndex((y) => y.id === mid);
            if (i < 0) return 'Not found';
            const x = members[i];
            if (x.name === me) return 'You can’t remove yourself';
            if (x.role === 'admin' && members.filter((y) => y.teamId === x.teamId && y.role === 'admin').length === 1) return `Last admin of ${x.team}`;
            members.splice(i, 1);
            log({ action: 'deleted', target: { type: 'member', name: x.name, href: '/settings/members' }, summary: `Removed from ${x.team}`, diff: [{ field: 'Role', before: ROLE_LABEL[x.role] }] });
          }),
        ),
    },

    notifications: {
      get: () => respond(() => (notifications[teamDirectory.current().id] ??= seedNotifications(teamDirectory.current().id))),
      update: (input) =>
        respond(() => {
          const tid = teamDirectory.current().id;
          const cur = (notifications[tid] ??= seedNotifications(tid));
          if (input.version !== cur.version) throw new ApiError(`${cur.updatedBy} saved newer settings (version ${cur.version}). Reload to see them, then make your change again.`, 409);
          const off = cur.channels.filter((c) => !c.connected).map((c) => c.id);
          const bad = input.rules.find((r) => r.channelIds.some((c) => off.includes(c)));
          if (bad) throw new ApiError('Connect a channel before routing notifications to it.', 400);
          const changed = cur.rules.filter((r) => {
            const next = input.rules.find((x) => x.event === r.event);
            return next && next.channelIds.slice().sort().join() !== r.channelIds.slice().sort().join();
          });
          const name = (ids: string[]) => ids.map((c) => cur.channels.find((x) => x.id === c)?.name ?? c).join(', ') || 'Nowhere';
          const diff = changed.map((r) => ({ field: r.label, before: name(r.channelIds), after: name(input.rules.find((x) => x.event === r.event)!.channelIds) }));
          for (const r of cur.rules) r.channelIds = input.rules.find((x) => x.event === r.event)?.channelIds ?? r.channelIds;
          Object.assign(cur, { version: cur.version + 1, updatedAt: new Date().toISOString(), updatedBy: me });
          log({ action: 'edited', target: { type: 'notifications', name: `Notifications · ${teamDirectory.current().name}`, href: '/settings/notifications' }, summary: `Saved version ${cur.version}`, diff });
          return cur;
        }),
    },

    webhooks: {
      list: (p) => respond((m) => list(scoped(webhooks).map(withStats), p, { text: (w) => `${w.name} ${w.url} ${w.events.join(' ')}`, value: field, facetKeys: ['status'] }, m)),
      create: (input) =>
        respond(() => {
          const name = input.name.trim();
          if (!name) throw new ApiError('Name the webhook.', 400);
          if (!/^https:\/\/[^\s]+\.[^\s]+/.test(input.url.trim())) throw new ApiError('Use an https:// URL.', 400);
          if (!input.events.length) throw new ApiError('Pick at least one event.', 400);
          const t = teamDirectory.current();
          const w = { id: id('wh'), teamId: t.id, team: t.name, name, url: input.url.trim(), events: input.events, status: 'active' as const, secretPrefix: `whsec_${Math.random().toString(36).slice(2, 6)}`, deliveries7d: 0, volume: 0, createdAt: new Date().toISOString() };
          webhooks.unshift(w);
          log({ action: 'created', target: { type: 'webhook', name, href: '/settings/webhooks' }, summary: `Sends ${input.events.length === 1 ? '1 event' : `${input.events.length} events`} to ${new URL(w.url).host}`, diff: [{ field: 'URL', after: w.url }] });
          return withStats(w);
        }),
      setStatus: (wid, status) =>
        respond(() => {
          const w = webhooks.find((x) => x.id === wid) ?? notFound('Webhook');
          log({ action: 'edited', target: { type: 'webhook', name: w.name, href: '/settings/webhooks' }, summary: status === 'paused' ? 'Paused deliveries' : 'Resumed deliveries', diff: [{ field: 'Status', before: w.status, after: status }] });
          w.status = status;
          return withStats(w);
        }),
      remove: (wid) =>
        respond(() => {
          const i = webhooks.findIndex((x) => x.id === wid);
          if (i < 0) notFound('Webhook');
          const [w] = webhooks.splice(i, 1);
          log({ action: 'deleted', target: { type: 'webhook', name: w.name, href: '/settings/webhooks' }, summary: 'Deleted a webhook', diff: [{ field: 'URL', before: w.url }] });
        }),
      deliveries: (wid, p) =>
        respond((m) => {
          const w = webhooks.find((x) => x.id === wid) ?? notFound('Webhook');
          return list(historyOf(w), p, { text: (d) => `${d.event} ${d.error ?? ''}`, value: field, facetKeys: ['status'] }, m);
        }),
      resend: (wid, did) =>
        respond(() => {
          const w = webhooks.find((x) => x.id === wid) ?? notFound('Webhook');
          if (w.status === 'paused') throw new ApiError('Resume the webhook before resending.', 409);
          const d = historyOf(w).find((x) => x.id === did) ?? notFound('Delivery');
          if (d.status !== 'failed') throw new ApiError('Only failed deliveries can be resent.', 409);
          // The failing endpoint still times out; any other endpoint accepts the retry.
          const ok = w.status !== 'failing';
          const next: WebhookDelivery = {
            ...d,
            id: id('dl'),
            status: ok ? 'success' : 'failed',
            statusCode: ok ? 200 : d.statusCode,
            attempts: ok ? 1 : 3,
            durationMs: ok ? 140 : d.durationMs,
            at: new Date().toISOString(),
            error: ok ? undefined : d.error,
            responseBody: ok ? '{"ok":true}' : d.responseBody,
          };
          historyOf(w).unshift(next);
          log({ action: 'edited', target: { type: 'webhook', name: w.name, href: '/settings/webhooks' }, summary: `Resent ${d.event}`, diff: [{ field: 'Delivery', before: 'Failed', after: ok ? 'Delivered' : 'Failed' }] });
          return next;
        }),
    },

    apiKeys: {
      list: (p) => respond((m) => list(scoped(keys).map(strip), p, { text: (k) => `${k.name} ${k.prefix} ${k.createdBy}`, value: field, facetKeys: [] }, m)),
      create: (input) =>
        respond(() => {
          const name = input.name.trim();
          if (!name) throw new ApiError('Name the key.', 400);
          if (!input.scopes.length) throw new ApiError('Pick at least one scope.', 400);
          const t = targetTeam(input.teamId);
          const key = `nfb_live_${Array.from({ length: 32 }, () => 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'[Math.floor(Math.random() * 57)]).join('')}`;
          const k = { id: id('key'), teamId: t.id, team: t.name, name, prefix: key.slice(0, 12), scopes: input.scopes, createdBy: me, createdAt: new Date().toISOString(), expiresAt: input.expiresInDays ? new Date(Date.now() + input.expiresInDays * 86_400_000).toISOString() : undefined };
          keys.unshift(k);
          log({ action: 'created', target: { type: 'api_key', name: `${name} (${k.prefix}…)`, href: '/settings/api-keys' }, summary: 'Created an API key', diff: [{ field: 'Scopes', after: input.scopes.join(', ') }, { field: 'Expires', after: input.expiresInDays ? `In ${input.expiresInDays} days` : 'Never' }] });
          return { key, apiKey: strip(k) };
        }),
      revoke: (kid) =>
        respond(() => {
          const i = keys.findIndex((x) => x.id === kid);
          if (i < 0) notFound('API key');
          const [k] = keys.splice(i, 1);
          log({ action: 'revoked', target: { type: 'api_key', name: `${k.name} (${k.prefix}…)`, href: '/settings/api-keys' }, summary: 'Revoked an API key; calls using it now get 401', diff: [{ field: 'Status', before: 'Active', after: 'Revoked' }] });
        }),
    },

    usage: {
      get: (days) =>
        respond((m): UsageReport => {
          const t = teamDirectory.current();
          const scope = t.scope === 'all' ? 'all' : 'team';
          const ownerOf = (wid: string) => F.WORKFLOWS.find((w) => w.id === wid)!.owner;
          const teamOf = (wid: string) => teamDirectory.ofOwner(ownerOf(wid));
          const mine = usage.filter((u) => scope === 'all' || teamOf(u.workflowId).id === t.id);
          const dates = [...new Set(usage.map((u) => u.date))].sort();
          const current = new Set(dates.slice(-days));
          const previous = new Set(dates.slice(-2 * days, -days));
          const rows = m === 'empty' ? [] : mine.filter((u) => current.has(u.date));
          const prevCost = mine.filter((u) => previous.has(u.date)).reduce((s, u) => s + u.modelCost, 0);
          const sum = (xs: typeof rows) => ({
            runs: xs.reduce((s, u) => s + u.runs, 0),
            toolCalls: xs.reduce((s, u) => s + u.toolCalls, 0),
            tokens: xs.reduce((s, u) => s + u.tokens, 0),
            modelCost: Math.round(xs.reduce((s, u) => s + u.modelCost, 0) * 100) / 100,
          });
          const totals = sum(rows);
          const toRow = (key: string, name: string, xs: typeof rows, team?: string): UsageRow => {
            const s = sum(xs);
            return { key, name, team, ...s, costPerRun: s.runs ? Math.round((s.modelCost / s.runs) * 1000) / 1000 : 0, share: totals.modelCost ? s.modelCost / totals.modelCost : 0 };
          };
          const wfIds = [...new Set(rows.map((u) => u.workflowId))];
          const byWorkflow = wfIds
            .map((wid) => toRow(wid, F.WORKFLOWS.find((w) => w.id === wid)!.name, rows.filter((u) => u.workflowId === wid), teamOf(wid).name))
            .sort((a, b) => b.modelCost - a.modelCost);
          const teamIds = [...new Set(rows.map((u) => teamOf(u.workflowId).id))];
          const byTeam = teamIds
            .map((tid) => toRow(tid, teamDirectory.all().find((x) => x.id === tid)!.name, rows.filter((u) => teamOf(u.workflowId).id === tid)))
            .sort((a, b) => b.modelCost - a.modelCost);
          const series = scope === 'all' ? byTeam.map((r) => ({ key: r.key, label: r.name })) : byWorkflow.map((r) => ({ key: r.key, label: r.name }));
          const daily = [...current].map((date) => {
            const point: { date: string } & Record<string, number | string> = { date };
            for (const s of series) {
              const xs = rows.filter((u) => u.date === date && (scope === 'all' ? teamOf(u.workflowId).id === s.key : u.workflowId === s.key));
              point[s.key] = Math.round(xs.reduce((a, u) => a + u.modelCost, 0) * 100) / 100;
            }
            return point;
          });
          return {
            days,
            scope,
            teamName: t.name,
            totals: { ...totals, costTrendPct: prevCost ? Math.round(((totals.modelCost - prevCost) / prevCost) * 1000) / 10 : 0 },
            series,
            daily: rows.length ? daily : [],
            byTeam,
            byWorkflow,
          };
        }),
    },

    lookups: () => respond(() => LOOKUPS),
  };
}
