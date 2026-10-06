import type { AccessGrant, AuditEntry, AuditView, GrantStatus, RoleAssignment, ToolCallDetail, ToolCallRow } from '@/lib/types/governance';

import { ApiError } from '../../contract';
import type { GovernanceApi } from '../../governance-contract';
import type { SettingsApi } from '../../settings-contract';
import * as F from '../fixtures';
import { bulk, field, id, list, notFound, respond } from '../runtime';
import { createSettingsMock } from '../settings';
import { guardTeam, inTeam, teamDirectory } from '../teams';
import { emailOf, KB_IDS, MODULES, moduleLabel, PEOPLE, principalOf, WORKFLOW_ACCESS } from './catalog';
import { GROUPS, seedGrants, seedRoles } from './seed-access';
import { AUDIT_SEED, loginSeeds } from './seed-audit';
import { seedToolCalls } from './seed-calls';

type Owned<T> = T & { owner?: string };

const EXPIRING_DAYS = 14;
const VIEW: Record<Exclude<AuditView, 'all'>, (e: AuditEntry) => boolean> = {
  publishes: (e) => ['published', 'approved', 'rejected', 'restored'].includes(e.action),
  access: (e) => ['granted', 'revoked'].includes(e.action) || ['access_grant', 'role', 'member', 'api_key'].includes(e.target.type),
  deletions: (e) => e.action === 'deleted',
};

const req = () => `req_${Math.random().toString(36).slice(2, 12)}`;

export type AuditWrite = Pick<AuditEntry, 'action' | 'target' | 'summary'> & Partial<Pick<AuditEntry, 'diff' | 'reason'>> & { owner?: string };
/** Lets other mocks (model risk, evals, integrations) write to and read the same audit log; set when the governance mock is created. */
export const auditSink: { log: (e: AuditWrite) => void; entries: () => AuditEntry[] } = { log: () => undefined, entries: () => [] };

/**
 * Logs and access, plus team settings (which write to the same audit log). Seeds come from the fixtures, so
 * every call, audit entry and grant names a real workflow, agent, gate or review.
 */
export function createGovernanceMock(): { governance: GovernanceApi; settings: SettingsApi } {
  const me = F.CURRENT_USER.name;
  const ownerOf = (wid: string) => F.WORKFLOWS.find((w) => w.id === wid)?.owner;
  const calls = seedToolCalls();
  const grants: Owned<AccessGrant>[] = seedGrants();
  const teamName = (tid: string) => teamDirectory.all().find((t) => t.id === tid)?.name ?? tid;
  const roles: RoleAssignment[] = seedRoles(teamName);

  const toEntry = (s: (typeof AUDIT_SEED)[number], i: number): Owned<AuditEntry> => {
    const t = teamDirectory.ofOwner(s.owner);
    const { min, ...rest } = s;
    return { ...rest, id: `aud_${String(1000 - i)}`, at: new Date(Date.now() - min * 60_000).toISOString(), teamId: t.id, team: t.name, requestId: `req_${(i * 104729).toString(36)}` };
  };
  const audit: Owned<AuditEntry>[] = [...AUDIT_SEED, ...loginSeeds()].sort((a, b) => a.min - b.min).map(toEntry);

  /** Appends an audit entry as the current user, in the current team unless an owner says otherwise. */
  const log = (e: Pick<AuditEntry, 'action' | 'target' | 'summary'> & Partial<Pick<AuditEntry, 'diff' | 'reason'>> & { owner?: string }) => {
    const cur = teamDirectory.current();
    const owner = e.owner ?? (cur.scope === 'all' ? undefined : cur.ownerGroups[0]);
    const t = teamDirectory.ofOwner(owner);
    audit.unshift({ diff: [], ...e, owner, id: id('aud'), at: new Date().toISOString(), actor: { kind: 'person', name: me, detail: emailOf(me) }, teamId: t.id, team: t.name, requestId: req() });
  };
  auditSink.log = log;
  auditSink.entries = () => audit.filter((e) => inTeam(e.owner)).map(strip);

  const statusOf = (g: AccessGrant): GrantStatus => {
    if (!g.expiresAt) return 'active';
    const left = new Date(g.expiresAt).getTime() - Date.now();
    return left < 0 ? 'expired' : left < EXPIRING_DAYS * 86_400_000 ? 'expiring' : 'active';
  };
  const teamGrants = () => grants.filter((g) => inTeam(g.owner)).map((g) => ({ ...g, status: statusOf(g) }));
  const strip = <T extends { owner?: string }>(r: T) => {
    const { owner: _o, ...rest } = r;
    void _o;
    return rest;
  };
  const scopedRoles = () => (teamDirectory.current().scope === 'all' ? roles : roles.filter((r) => r.teamId === teamDirectory.current().id));
  const scopeLabel = (s: string) => (s === 'money_movement' ? 'Moves money' : s[0].toUpperCase() + s.slice(1));

  const governance: GovernanceApi = {
    toolCalls: {
      list: (p) =>
        respond((m) => {
          const scoped = calls.filter((c) => inTeam(ownerOf(c.workflowId)));
          const src = m === 'empty' ? [] : scoped;
          const lat = src.map((c) => c.latencyMs).sort((a, b) => a - b);
          const rows: ToolCallRow[] = scoped.map(({ request: _q, response: _r, redacted: _d, policy: _p, identity: _i, requestId: _x, error: _e, ...row }) => row);
          return {
            ...list(rows, p, {
              text: (c) => `${c.target} ${c.system} ${c.workflowName} ${c.agentName} ${c.runId} ${c.caseId ?? ''} ${c.record ?? ''}`,
              value: (c, k) => (k === 'approval' ? c.approval.kind : field(c, k)),
              facetKeys: ['gateway', 'operation', 'approval', 'status', 'workflowId'],
            }, m),
            stats: {
              failed: src.filter((c) => c.status === 'error').length,
              errorRate: src.length ? src.filter((c) => c.status === 'error').length / src.length : 0,
              denied: src.filter((c) => c.status === 'denied').length,
              writesApprovedByPerson: src.filter((c) => c.approval.kind === 'person' && c.approval.tokenId).length,
              awaitingApproval: src.filter((c) => c.status === 'awaiting_approval').length,
              p95Ms: lat.length ? lat[Math.floor(lat.length * 0.95)] : 0,
            },
          };
        }),
      get: (cid) =>
        respond((): ToolCallDetail => {
          const c = calls.find((x) => x.id === cid) ?? notFound('Call');
          guardTeam(ownerOf(c.workflowId), 'call');
          return c;
        }),
    },

    audit: {
      list: (p) =>
        respond((m) => {
          const scoped = audit.filter((e) => inTeam(e.owner)).map(strip);
          const inView = p.view === 'all' ? scoped : scoped.filter(VIEW[p.view]);
          const src = m === 'empty' ? [] : scoped;
          return {
            ...list(inView, p, {
              text: (e) => `${e.actor.name} ${e.target.name} ${e.summary} ${e.reason ?? ''} ${e.requestId}`,
              value: (e, k) => (k === 'actorKind' ? e.actor.kind : k === 'targetType' ? e.target.type : field(e, k)),
              facetKeys: ['action', 'targetType', 'actorKind', 'teamId'],
            }, m),
            viewCounts: { all: src.length, publishes: src.filter(VIEW.publishes).length, access: src.filter(VIEW.access).length, deletions: src.filter(VIEW.deletions).length },
          };
        }),
    },

    access: {
      identities: (p) =>
        respond((m) => {
          const tg = teamGrants().filter((g) => g.status !== 'expired');
          const rows = F.WORKFLOWS.filter((w) => inTeam(w.owner) && WORKFLOW_ACCESS[w.id]).map((w) => {
            const mine = tg.filter((g) => g.workflowId === w.id);
            return {
              id: `wid_${w.id.slice(3)}`,
              workflowId: w.id,
              workflowName: w.name,
              principal: principalOf(w.name),
              owner: w.owner,
              team: teamDirectory.ofOwner(w.owner).name,
              status: 'active' as const,
              grants: mine.length,
              expiringSoon: mine.filter((g) => g.status === 'expiring').length,
              moneyMovement: mine.some((g) => g.scope === 'money_movement'),
              lastUsedAt: calls.find((c) => c.workflowId === w.id)?.at,
            };
          });
          const src = m === 'empty' ? [] : tg;
          return {
            ...list(rows, p, { text: (r) => `${r.workflowName} ${r.principal}`, value: field, facetKeys: [] }, m),
            stats: {
              identities: m === 'empty' ? 0 : rows.length,
              activeGrants: src.length,
              expiringSoon: src.filter((g) => g.status === 'expiring').length,
              moneyMovementGrants: src.filter((g) => g.scope === 'money_movement').length,
            },
          };
        }),
      grants: (p) =>
        respond((m) => {
          const scoped = teamGrants().map(strip);
          const inView = p.view === 'all' ? scoped : scoped.filter((g) => g.status === p.view);
          const src = m === 'empty' ? [] : scoped;
          return {
            ...list(inView, p, { text: (g) => `${g.resource} ${g.workflowName} ${g.grantedBy} ${g.reason ?? ''}`, value: field, facetKeys: ['workflowId', 'resourceKind', 'scope', 'status'] }, m),
            viewCounts: { all: src.length, expiring: src.filter((g) => g.status === 'expiring').length, expired: src.filter((g) => g.status === 'expired').length },
          };
        }),
      grant: (input) =>
        respond(() => {
          const w = F.WORKFLOWS.find((x) => x.id === input.workflowId) ?? notFound('Workflow');
          guardTeam(w.owner, 'workflow');
          const known = input.resourceKind === 'module' ? MODULES.some((x) => moduleLabel(x.tool) === input.resource) : input.resource in KB_IDS;
          if (!known) throw new ApiError('Pick a module or knowledge base from the list.', 400);
          if (input.resourceKind === 'knowledge_base' && input.scope !== 'read') throw new ApiError('Knowledge bases are granted read access only.', 400);
          if (!Number.isInteger(input.expiresInDays) || input.expiresInDays < 1 || input.expiresInDays > 365) throw new ApiError('Choose when the access expires, at most 365 days from now.', 400);
          if (input.scope === 'money_movement' && input.expiresInDays > 180) throw new ApiError('Money-movement grants must expire within 180 days.', 400);
          if (input.scope === 'money_movement' && !input.reason.trim()) throw new ApiError('Give the approval reference for money-movement access.', 400);
          if (grants.some((g) => g.workflowId === w.id && g.resource === input.resource && statusOf(g) !== 'expired')) throw new ApiError(`${w.name} already has access to ${input.resource}.`, 409);
          const g: Owned<AccessGrant> = {
            id: id('gr'),
            identityId: `wid_${w.id.slice(3)}`,
            workflowId: w.id,
            workflowName: w.name,
            owner: w.owner,
            resourceKind: input.resourceKind,
            resource: input.resource,
            scope: input.scope,
            grantedBy: me,
            grantedAt: new Date().toISOString(),
            expiresAt: new Date(Date.now() + input.expiresInDays * 86_400_000).toISOString(),
            status: 'active',
            reason: input.reason.trim() || undefined,
          };
          grants.unshift(g);
          log({ owner: w.owner, action: 'granted', target: { type: 'access_grant', name: `${w.name} → ${input.resource}`, href: '/access?tab=grants' }, summary: `Granted ${scopeLabel(input.scope).toLowerCase()} access`, diff: [{ field: 'Scope', after: scopeLabel(input.scope) }, { field: 'Expires', after: `In ${input.expiresInDays} days` }], reason: g.reason });
          return { ...strip(g), status: statusOf(g) };
        }),
      revoke: (ids, reason) =>
        respond(() =>
          bulk(ids, (gid) => {
            const i = grants.findIndex((g) => g.id === gid);
            if (i < 0) return 'Not found';
            if (!inTeam(grants[i].owner)) return 'Belongs to another team';
            const [g] = grants.splice(i, 1);
            log({ owner: g.owner, action: 'revoked', target: { type: 'access_grant', name: `${g.workflowName} → ${g.resource}`, href: '/access?tab=grants' }, summary: `Revoked ${scopeLabel(g.scope).toLowerCase()} access`, diff: [{ field: 'Status', before: 'Active', after: 'Revoked' }], reason });
          }),
        ),
      extend: (ids, days) =>
        respond(() =>
          bulk(ids, (gid) => {
            const g = grants.find((x) => x.id === gid);
            if (!g) return 'Not found';
            if (g.scope === 'money_movement' && days > 180) return 'Money movement is capped at 180 days';
            const before = g.expiresAt;
            const wasExpired = statusOf(g) === 'expired';
            g.expiresAt = new Date(Date.now() + days * 86_400_000).toISOString();
            log({
              owner: g.owner,
              action: 'edited',
              target: { type: 'access_grant', name: `${g.workflowName} → ${g.resource}`, href: '/access?tab=grants' },
              summary: wasExpired ? `Reactivated access for ${days} days` : `Extended access by ${days} days`,
              diff: [
                ...(wasExpired ? [{ field: 'Status', before: 'Expired', after: 'Active' }] : []),
                { field: 'Expires', before: new Date(before).toLocaleDateString('en-CA'), after: new Date(g.expiresAt).toLocaleDateString('en-CA') },
              ],
            });
          }),
        ),
      roles: (p) => respond((m) => list(scopedRoles(), p, { text: (r) => `${r.principal} ${r.team}`, value: (r, k) => (k === 'capabilities' ? r.capabilities : field(r, k)), facetKeys: ['principalKind', 'capabilities', 'teamId'] }, m)),
      assignRole: (input) =>
        respond(() => {
          const cur = teamDirectory.current();
          const teamId = cur.scope === 'all' ? input.teamId : cur.id;
          if (!input.principal.trim()) throw new ApiError('Pick a person or group.', 400);
          if (!input.capabilities.length) throw new ApiError('Pick at least one of author, approve or publish.', 400);
          if (roles.some((r) => r.teamId === teamId && r.principal === input.principal)) throw new ApiError(`${input.principal} already has a role in ${teamName(teamId)}. Edit that one instead.`, 409);
          const r: RoleAssignment = { id: id('role'), principal: input.principal, principalKind: input.principalKind, members: input.principalKind === 'group' ? 3 + (input.principal.length % 9) : 1, teamId, team: teamName(teamId), capabilities: input.capabilities, addedBy: me, addedAt: new Date().toISOString() };
          roles.unshift(r);
          const owner = teamDirectory.all().find((t) => t.id === teamId)?.ownerGroups[0];
          log({ owner, action: 'granted', target: { type: 'role', name: `${r.principal} · ${r.team}`, href: '/access?tab=roles' }, summary: `Can ${r.capabilities.join(', ')} in ${r.team}`, diff: [{ field: 'Capabilities', after: r.capabilities.join(', ') }] });
          return r;
        }),
      removeRoles: (ids) =>
        respond(() =>
          bulk(ids, (rid) => {
            const i = roles.findIndex((r) => r.id === rid);
            if (i < 0) return 'Not found';
            const r = roles[i];
            if (r.capabilities.includes('publish') && !roles.some((x) => x.id !== r.id && !ids.includes(x.id) && x.teamId === r.teamId && x.capabilities.includes('publish'))) return `Last publisher in ${r.team}`;
            roles.splice(i, 1);
            const owner = teamDirectory.all().find((t) => t.id === r.teamId)?.ownerGroups[0];
            log({ owner, action: 'revoked', target: { type: 'role', name: `${r.principal} · ${r.team}`, href: '/access?tab=roles' }, summary: `Removed ${r.capabilities.join(', ')}`, diff: [{ field: 'Capabilities', before: r.capabilities.join(', '), after: 'None' }] });
          }),
        ),
      options: () =>
        respond(() => {
          const cur = teamDirectory.current();
          return {
            workflows: F.WORKFLOWS.filter((w) => inTeam(w.owner)).map((w) => ({ id: w.id, name: w.name })),
            modules: MODULES.map((x) => ({ value: moduleLabel(x.tool), system: x.system, access: x.access })),
            knowledgeBases: Object.keys(KB_IDS),
            people: PEOPLE,
            groups: GROUPS,
            teams: (cur.scope === 'all' ? teamDirectory.all() : [cur]).map((t) => ({ id: t.id, name: t.name })),
          };
        }),
    },
  };

  return { governance, settings: createSettingsMock({ log, me }) };
}
