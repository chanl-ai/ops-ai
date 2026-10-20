import type { ApiKey, Member, MemberRole, NotificationSettings, Webhook, WebhookDelivery } from '@/lib/types/settings';
import type { Team } from '@/lib/types/team';

import * as F from '../fixtures';
import { emailOf, inDays, minsAgo, rng } from '../governance/catalog';

const D = 1440;

const FIRST = ['Aisha', 'Ben', 'Chloe', 'Dev', 'Erin', 'Felix', 'Hana', 'Ivan', 'Jade', 'Kofi', 'Laura', 'Mateo', 'Nadia', 'Owen', 'Paula', 'Quinn', 'Rosa', 'Sam', 'Tara', 'Victor', 'Wen', 'Yusuf', 'Zoe', 'Arjun', 'Bianca', 'Carlos', 'Dina', 'Elliot'];
const LAST = ['Abara', 'Bergstrom', 'Chowdhury', 'Dubois', 'Esposito', 'Fraser', 'Gill', 'Hughes', 'Ito', 'Jensen', 'Kaur', 'Lavoie', 'Mensah', 'Novak', "O'Neil", 'Petrov', 'Quintero', 'Roy', 'Sato', 'Tremblay', 'Usman', 'Vos', 'Wong'];

/** Named people the rest of the demo already uses, in their home teams. */
const KNOWN: { name: string; teamId: string; role: MemberRole }[] = [
  { name: 'James Richardson', teamId: 'team_platform', role: 'admin' },
  { name: 'Omar Siddiqui', teamId: 'team_platform', role: 'builder' },
  { name: 'Grace Liu', teamId: 'team_platform', role: 'builder' },
  { name: 'Rafael Costa', teamId: 'team_platform', role: 'viewer' },
  { name: 'Maya Okafor', teamId: 'team_fraud', role: 'admin' },
  { name: 'Priya Shah', teamId: 'team_lending', role: 'admin' },
  { name: 'Daniel Brooks', teamId: 'team_cards', role: 'admin' },
  { name: 'Anika Singh', teamId: 'team_onboarding', role: 'admin' },
  { name: 'Tom Haddad', teamId: 'team_retail', role: 'admin' },
  { name: 'Lena Fischer', teamId: 'team_wealth', role: 'admin' },
];

export function seedMembers(teams: Team[]): Member[] {
  const r = rng(11);
  const out: Member[] = [];
  let n = 0;
  for (const t of teams) {
    const known = KNOWN.filter((k) => k.teamId === t.id);
    for (let i = 0; i < t.memberCount; i++) {
      const k = known[i];
      const name = k?.name ?? `${FIRST[(n * 7 + i) % FIRST.length]} ${LAST[(n * 5 + i * 3) % LAST.length]}`;
      const invited = !k && i === t.memberCount - 1 && t.memberCount > 5;
      const role: MemberRole = k?.role ?? (['builder', 'approver', 'approver', 'viewer', 'approver'] as const)[(n + i) % 5];
      out.push({
        id: `mem_${++n}`,
        name,
        email: emailOf(name).replace("'", ''),
        role,
        teamId: t.id,
        team: t.name,
        status: invited ? 'invited' : 'active',
        lastActiveAt: invited ? undefined : minsAgo(Math.floor(r() * 9 * D) + 5),
        invitedAt: invited ? minsAgo(2 * D + i * 60) : undefined,
      });
    }
  }
  return out;
}

const TEAMS_CHANNEL: Record<string, string> = {
  team_platform: 'Ops AI › Platform alerts',
  team_fraud: 'Fraud Ops › Wire approvals',
  team_lending: 'Lending Ops › Approvals',
  team_cards: 'Card Services › Disputes',
  team_onboarding: 'Onboarding › KYC reviews',
  team_retail: 'Retail Digital › Branch chat',
  team_wealth: 'Wealth › Advisor sign-off',
};

export function seedNotifications(teamId: string): NotificationSettings {
  return {
    version: 3,
    updatedAt: minsAgo(6 * D),
    updatedBy: 'James Richardson',
    channels: [
      { id: 'in_app', name: 'In Ops AI', connected: true, detail: 'Bell and Reviews queue', actionable: true },
      { id: 'email', name: 'Email', connected: true, detail: 'From ops-ai@northfieldbank.com', actionable: true },
      { id: 'teams', name: 'Microsoft Teams', connected: true, detail: TEAMS_CHANNEL[teamId] ?? 'Ops AI › Alerts', actionable: true },
      { id: 'slack', name: 'Slack', connected: false, detail: 'Not connected', actionable: false },
    ],
    rules: [
      { event: 'approval_waiting', label: 'Approval waiting', description: 'A drafted action or review is waiting for someone in this team', channelIds: ['in_app', 'email', 'teams'] },
      { event: 'sla_at_risk', label: 'SLA at risk', description: 'An open review or case passes 80% of its SLA', channelIds: ['in_app', 'teams'] },
      { event: 'publish_request', label: 'Publish request', description: 'Someone asks to publish a workflow this team owns', channelIds: ['in_app', 'email'] },
      { event: 'mailbox_disconnected', label: 'Mailbox disconnected', description: 'A connected mailbox stops syncing', channelIds: ['in_app', 'email', 'teams'] },
    ],
  };
}

export function seedWebhooks(teamName: (id: string) => string): (Webhook & { teamId: string; volume: number })[] {
  // Stats are derived from the delivery history in the mock; `volume` only sizes that history.
  const w = (id: string, teamId: string, name: string, url: string, events: string[], status: Webhook['status'], volume: number, createdDays: number): Webhook & { teamId: string; volume: number } => ({
    id,
    teamId,
    team: teamName(teamId),
    name,
    url,
    events,
    status,
    secretPrefix: `whsec_${id.slice(3, 7)}`,
    deliveries7d: 0,
    volume,
    createdAt: minsAgo(createdDays * D),
  });
  return [
    w('wh_siem', 'team_platform', 'Splunk Cloud SIEM', 'https://http-inputs-northfield.splunkcloud.com/services/collector', ['audit.created', 'call.denied', 'access.changed'], 'active', 4120, 61),
    w('wh_snow', 'team_platform', 'ServiceNow incidents', 'https://northfield.service-now.com/api/now/ops_ai/events', ['run.failed', 'mailbox.disconnected'], 'failing', 38, 120),
    w('wh_fraudcm', 'team_fraud', 'Fraud case manager', 'https://fcm.internal.northfieldbank.com/hooks/ops-ai', ['review.decided', 'run.completed'], 'active', 1611, 88),
    w('wh_disputes', 'team_cards', 'Dispute system of record', 'https://disputes.internal.northfieldbank.com/v2/events', ['case.closed', 'review.decided'], 'active', 702, 40),
    w('wh_loansvc', 'team_lending', 'Loan servicing callbacks', 'https://loansvc.internal.northfieldbank.com/ops-ai', ['case.closed'], 'paused', 12, 33),
  ];
}

/** `volume` deliveries spread over the last 7 days (a paused hook's stop when it was paused, 3 days ago). */
export function seedDeliveries(hook: Webhook, volume: number): WebhookDelivery[] {
  const r = rng(hook.id.length * 31 + hook.url.length);
  const failing = hook.status === 'failing';
  const paused = hook.status === 'paused';
  const start = paused ? 3 * D : 0;
  const step = (7 * D - start - 30) / Math.max(volume, 1);
  return Array.from({ length: volume }, (_, i) => {
    const event = hook.events[i % hook.events.length];
    const roll = r();
    const status: WebhookDelivery['status'] = hook.status === 'paused' && i < 4 ? 'skipped' : failing && roll < 0.4 ? 'failed' : roll < 0.015 ? 'failed' : i === 0 && roll < 0.3 ? 'pending' : 'success';
    const failed = status === 'failed';
    return {
      id: `dl_${hook.id}_${i}`,
      event,
      status,
      statusCode: status === 'success' ? 200 : failed ? (failing ? 504 : 500) : undefined,
      attempts: failed ? 3 : 1,
      durationMs: status === 'skipped' || status === 'pending' ? undefined : Math.round(80 + r() * (failed ? 9000 : 400)),
      // A paused hook's newest few are the events skipped since it was paused.
      at: paused && i < 4 ? minsAgo(i * 900 + 60) : minsAgo(start + i * step + Math.floor(r() * Math.min(step, 20)) + 1),
      error: failed ? (failing ? 'Gateway timeout after 3 attempts' : 'Internal Server Error') : status === 'skipped' ? 'Webhook paused' : undefined,
      payload: { event, id: `evt_${(i * 7919).toString(36)}`, workspace: 'Northfield Bank', data: event.startsWith('review') ? { reviewId: F.REVIEWS[i % F.REVIEWS.length].id, decision: 'approved' } : event.startsWith('case') ? { caseId: `CASE-${4100 + (i % 36)}` } : { workflowId: F.WORKFLOWS[i % F.WORKFLOWS.length].id } },
      responseBody: status === 'success' ? '{"ok":true}' : failed ? (failing ? '<html>504 Gateway Time-out</html>' : '{"error":"internal"}') : undefined,
    };
  });
}

export function seedApiKeys(teamName: (id: string) => string): (ApiKey & { teamId: string })[] {
  const k = (id: string, teamId: string, name: string, prefix: string, scopes: string[], createdBy: string, createdDays: number, lastMin?: number, expiresInDays?: number): ApiKey & { teamId: string } => ({
    id,
    teamId,
    team: teamName(teamId),
    name,
    prefix,
    scopes,
    createdBy,
    createdAt: minsAgo(createdDays * D),
    lastUsedAt: lastMin != null ? minsAgo(lastMin) : undefined,
    expiresAt: expiresInDays != null ? inDays(expiresInDays) : undefined,
  });
  return [
    k('key_payhub', 'team_fraud', 'Payments Hub events', 'nfb_live_Wr2', ['runs:write'], 'James Richardson', 3, 1, 362),
    k('key_broker', 'team_lending', 'Broker portal', 'nfb_live_Mg9', ['runs:write', 'runs:read'], 'Priya Shah', 30, 4 * 60, 335),
    k('key_mobile', 'team_retail', 'Mobile app chat', 'nfb_live_7Qx', ['runs:write'], 'Tom Haddad', 21, 2, 344),
    k('key_bi', 'team_platform', 'Power BI usage export', 'nfb_live_Bi4', ['usage:read', 'logs:read'], 'Grace Liu', 64, 9 * 60),
    k('key_audit', 'team_platform', 'Internal audit read-only', 'nfb_live_Au1', ['logs:read', 'audit:read'], 'James Richardson', 120, 3 * D, 12),
  ];
}

/** Daily usage per workflow over 60 days (30 shown plus the period before, for the trend), derived from each workflow's run volume and model. */
export function seedUsage(): { workflowId: string; date: string; runs: number; toolCalls: number; tokens: number; modelCost: number }[] {
  const r = rng(5);
  const out: { workflowId: string; date: string; runs: number; toolCalls: number; tokens: number; modelCost: number }[] = [];
  const PRICE: Record<string, number> = { 'claude-haiku-4-5': 2.2, 'claude-sonnet-5': 6.6, 'claude-opus-5-5': 11 };
  const CALLS: Record<string, number> = { wf_wire: 3.4, wf_mortgage: 6.1, wf_dispute: 3.8, wf_kyb: 3.2, wf_branch_chat: 2.6, wf_card_inbox: 4.9, wf_lending_inbox: 4.2 };
  for (const w of F.WORKFLOWS) {
    if (!w.runs24h) continue;
    const model = F.AGENTS.find((a) => a.slug === w.agentSlugs[0])?.model ?? 'claude-sonnet-5';
    const tokensPerRun = model === 'claude-haiku-4-5' ? 5200 : 9800;
    for (let d = 59; d >= 0; d--) {
      const day = new Date(Date.now() - d * 86_400_000);
      const weekend = day.getDay() === 0 || day.getDay() === 6;
      const runs = Math.round(w.runs24h * (weekend ? 0.35 : 0.85 + r() * 0.3) * (1 + (59 - d) * 0.004));
      const tokens = Math.round(runs * tokensPerRun * (0.9 + r() * 0.2));
      out.push({ workflowId: w.id, date: day.toISOString().slice(0, 10), runs, toolCalls: Math.round(runs * (CALLS[w.id] ?? 3)), tokens, modelCost: Math.round((tokens / 1e6) * PRICE[model] * 100) / 100 });
    }
  }
  return out;
}
