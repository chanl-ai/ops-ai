import type {
  AuthMethod,
  ConnectionActivity,
  ConnectionRef,
  Dependant,
  HealthCheck,
  Integration,
  IntegrationStatus,
  ScopeRequest,
} from '@/lib/types/integrations';

import type { IntegrationsApi } from '../../integrations-contract';
import { auditSink } from '../governance';
import { rng } from '../governance/catalog';
import { id, notFound, respond } from '../runtime';
import { inTeam, teamDirectory, teamOwner } from '../teams';
import { CATALOG, CONNECTIONS, daysAgo, inDays } from './seed';
import { appPageHref } from '@/lib/app-links';

const DAY = 86_400_000;
const EXPIRING_MS = 30 * DAY;

export interface ConnectionLink extends ConnectionRef {
  catalogId: string;
  authMethod: AuthMethod;
  instanceUrl: string;
}

interface Conn {
  id: string;
  catalogId: string;
  name: string;
  instanceUrl: string;
  tenant?: string;
  authMethod: AuthMethod;
  scopes: string[];
  ownerTeam: string;
  createdBy: string;
  createdAt: string;
  expiresAt?: string;
  rotateBy?: string;
  credentialRef?: string;
  /** Drafts on OAuth: who granted consent on the Setup tab. */
  consentBy?: string;
  base: 'draft' | 'healthy' | 'needs_reconnect' | 'revoked' | 'error';
  lastError?: string;
  lastCheckedAt: string;
  checks: HealthCheck[];
  scopeRequests: ScopeRequest[];
}

/**
 * Connections to bank systems. Sources, tool modules and mailboxes hold a connection id; `dependants` and
 * `activity` read them from their own mocks, and `onStatus` tells the knowledge mock when a revoke or reconnect
 * stops or resumes its sources.
 */
export function createIntegrationsMock(deps: {
  me: string;
  dependants: (connId: string) => Dependant[];
  activity: (connId: string) => ConnectionActivity[];
  onStatus: (connId: string, revoked: boolean) => void;
}): { api: IntegrationsApi; link: (connId?: string) => ConnectionLink | undefined; addMailbox: (address: string, ownerTeam: string) => string } {
  const { me } = deps;
  const catalogOf = (cid: string) => CATALOG.find((c) => c.id === cid) ?? notFound('Catalog system');

  const seedChecks = (cid: string, base: Conn['base'], since: number, i: number): HealthCheck[] => {
    const r = rng(i + 3);
    return Array.from({ length: 10 }, (_, k) => {
      const ageDays = k * 0.25 + 0.02;
      const failing = base !== 'healthy' && ageDays <= since + 0.01;
      const at = daysAgo(ageDays);
      return {
        id: `${cid}_chk${k}`,
        at,
        ok: !failing,
        latencyMs: failing ? Math.round(40 + r() * 30) : Math.round(90 + r() * 260),
        message: failing ? (base === 'revoked' ? 'Refused: access revoked' : base === 'needs_reconnect' ? 'Refused: consent expired' : 'Token request failed: invalid_client') : 'Token issued and a read call answered',
        by: 'Scheduled',
      };
    });
  };

  const switches: Record<string, { syncKnowledge?: boolean; exposeTools?: boolean }> = {};
  const conns: Conn[] = CONNECTIONS.map((c, i) => ({
    id: c.id,
    catalogId: c.catalogId,
    name: c.name,
    instanceUrl: c.instanceUrl,
    tenant: c.tenant,
    authMethod: c.authMethod,
    scopes: [...c.scopes],
    ownerTeam: c.ownerTeam,
    createdBy: c.createdBy,
    createdAt: daysAgo(c.createdDaysAgo),
    expiresAt: c.expiresIn != null ? inDays(c.expiresIn) : undefined,
    rotateBy: c.rotateIn != null ? inDays(c.rotateIn) : undefined,
    credentialRef: c.credentialRef,
    base: c.base,
    lastError: c.lastError,
    lastCheckedAt: daysAgo(0.02),
    checks: seedChecks(c.id, c.base, c.since ?? 0, i),
    scopeRequests:
      c.id === 'int_salesforce'
        ? [{ id: 'sr_sf1', scopes: ['knowledge.read'], justification: 'Branch chat should cite Salesforce Knowledge articles on account opening', requestedBy: 'Tom Haddad', requestedAt: daysAgo(2), approver: 'CRM Platform', status: 'pending' }]
        : [],
  }));

  // ── Derived ─────────────────────────────────────────────────────────────
  const statusOf = (c: Conn): IntegrationStatus => {
    if (c.base === 'draft') return 'draft';
    if (c.base === 'revoked') return 'revoked';
    if (c.base === 'error') return 'error';
    const left = c.expiresAt ? new Date(c.expiresAt).getTime() - Date.now() : Infinity;
    if (c.base === 'needs_reconnect' || left < 0) return 'needs_reconnect';
    return left < EXPIRING_MS ? 'expiring' : 'healthy';
  };
  const ownersOf = (c: Conn) => [c.ownerTeam, ...deps.dependants(c.id).map((d) => d.owner)];
  const visible = () => conns.filter((c) => inTeam(ownersOf(c)));

  const scopeSummary = (c: Conn) => {
    const all = catalogOf(c.catalogId).scopes;
    const granted = all.filter((s) => c.scopes.includes(s.id));
    const access = [...new Set(granted.map((s) => s.access))];
    return `${c.scopes.length} of ${all.length || c.scopes.length} · ${access.length === 2 ? 'read and write' : access[0] === 'write' ? 'write' : 'read only'}`;
  };

  function row(c: Conn): Integration {
    const ds = deps.dependants(c.id);
    const cat = catalogOf(c.catalogId);
    return {
      id: c.id,
      name: c.name,
      kind: cat.kind,
      catalogId: c.catalogId,
      authMethod: c.authMethod,
      instanceUrl: c.instanceUrl,
      tenant: c.tenant,
      scopes: c.scopes,
      scopeSummary: scopeSummary(c),
      ownerTeam: c.ownerTeam,
      createdBy: c.createdBy,
      createdAt: c.createdAt,
      expiresAt: c.expiresAt,
      rotateBy: c.rotateBy,
      credentialRef: c.credentialRef,
      status: statusOf(c),
      lastCheckedAt: c.lastCheckedAt,
      lastError: statusOf(c) === 'needs_reconnect' && !c.lastError ? 'Consent expired. Reconnect to resume.' : c.lastError,
      usedBy: { sources: ds.filter((d) => d.type === 'source').length, modules: ds.filter((d) => d.type === 'tool_module').length, mailboxes: ds.filter((d) => d.type === 'mailbox').length },
      // Until someone flips a switch, it follows what already reads through the connection.
      syncKnowledge: switches[c.id]?.syncKnowledge ?? ds.some((d) => d.type === 'source'),
      exposeTools: switches[c.id]?.exposeTools ?? ds.some((d) => d.type === 'tool_module'),
    };
  }


  const audit = (c: Conn, action: 'created' | 'connected' | 'revoked' | 'edited', summary: string, diff: { field: string; before?: string; after?: string }[], reason?: string) =>
    auditSink.log({ action, target: { type: 'integration', name: c.name, href: appPageHref(c.id) }, summary, diff, reason, owner: c.ownerTeam });

  const runCheck = (c: Conn, by: string) => {
    const s = statusOf(c);
    const ok = s === 'healthy' || s === 'expiring';
    c.lastCheckedAt = new Date().toISOString();
    c.checks.unshift({
      id: id('chk'),
      at: c.lastCheckedAt,
      ok,
      latencyMs: ok ? 120 + Math.round(Math.random() * 200) : 45,
      message: ok ? 'Token issued and a read call answered' : (row(c).lastError ?? 'Refused'),
      by,
    });
  };

  const ref = (c: Conn): ConnectionLink => ({ id: c.id, name: c.name, kind: catalogOf(c.catalogId).kind, status: statusOf(c), expiresAt: c.expiresAt, catalogId: c.catalogId, authMethod: c.authMethod, instanceUrl: c.instanceUrl });

  // The connections a knowledge source can read through; the sample integrations writes went with their pages.
  const api: IntegrationsApi = {
    options: () => respond(() => visible().map(ref)),
  };

  return {
    api,
    link: (cid) => {
      const c = cid ? conns.find((x) => x.id === cid) : undefined;
      return c ? ref(c) : undefined;
    },
    /** A new mailbox deployment's consent becomes its own Microsoft 365 connection. */
    addMailbox: (address, ownerTeam) => {
      const local = address.split('@')[0];
      const c: Conn = {
        id: id('int'),
        catalogId: 'cat_m365',
        name: `Microsoft 365 · ${local}@`,
        instanceUrl: 'https://graph.microsoft.com',
        tenant: 'harborpine.onmicrosoft.com',
        authMethod: 'oauth_consent',
        scopes: ['Mail.Read', 'Mail.Send'],
        ownerTeam: ownerTeam || teamOwner() || teamDirectory.current().name,
        createdBy: me,
        createdAt: new Date().toISOString(),
        expiresAt: inDays(90),
        base: 'healthy',
        lastCheckedAt: new Date().toISOString(),
        checks: [],
        scopeRequests: [],
      };
      runCheck(c, me);
      conns.unshift(c);
      audit(c, 'connected', `Granted mailbox consent for ${address}`, [{ field: 'Scopes', after: 'Read mail, Send mail' }]);
      return c.id;
    },
  };
}

