import type {
  AuthMethod,
  CatalogSystem,
  ConnectionActivity,
  ConnectionRef,
  Dependant,
  FixAction,
  HealthCheck,
  Integration,
  IntegrationDetail,
  IntegrationStatus,
  IntegrationView,
  ScopeRequest,
} from '@/lib/types/integrations';

import { ApiError } from '../../contract';
import type { IntegrationsApi } from '../../integrations-contract';
import { auditSink } from '../governance';
import { rng } from '../governance/catalog';
import { bulk, field, id, list, notFound, respond } from '../runtime';
import { guardTeam, inTeam, teamDirectory, teamOwner } from '../teams';
import { CATALOG, CONNECTIONS, daysAgo, inDays } from './seed';

const DAY = 86_400_000;
const EXPIRING_MS = 30 * DAY;
const VAULT_RE = /^vault:\/\/[a-z0-9][a-z0-9/_.-]+$/;
/** Shapes that look like a pasted secret rather than a vault path. */
const LITERAL_RE = /^(sk[-_]|xox[abp]-|ghp_|eyJ|-----BEGIN|AKIA)|^[A-Za-z0-9+/=_-]{32,}$/;

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
  base: 'healthy' | 'needs_reconnect' | 'revoked' | 'error';
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
    if (c.base === 'revoked') return 'revoked';
    if (c.base === 'error') return 'error';
    const left = c.expiresAt ? new Date(c.expiresAt).getTime() - Date.now() : Infinity;
    if (c.base === 'needs_reconnect' || left < 0) return 'needs_reconnect';
    return left < EXPIRING_MS ? 'expiring' : 'healthy';
  };
  const ownersOf = (c: Conn) => [c.ownerTeam, ...deps.dependants(c.id).map((d) => d.owner)];
  const visible = () => conns.filter((c) => inTeam(ownersOf(c)));
  const find = (cid: string) => {
    const c = conns.find((x) => x.id === cid) ?? notFound('Integration');
    guardTeam(ownersOf(c), 'integration');
    return c;
  };

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
    };
  }

  const fixFor = (c: Conn): IntegrationDetail['fix'] => {
    const s = statusOf(c);
    const act = (action: FixAction, label: string) => ({ action, label });
    if (s === 'revoked') return act('reconnect', c.authMethod === 'oauth_consent' ? 'Reconnect and grant consent again' : 'Reconnect');
    if (s === 'needs_reconnect') return act('reconnect', c.authMethod === 'oauth_consent' ? 'Renew consent' : 'Reconnect');
    if (s === 'error') return c.authMethod === 'oauth_consent' ? act('reconnect', 'Reconnect') : act('rotate', 'Point at the current vault secret');
    return undefined;
  };

  function detail(c: Conn): IntegrationDetail {
    const href = `/integrations/${c.id}`;
    const cat = catalogOf(c.catalogId);
    return {
      ...row(c),
      availableScopes: cat.scopes,
      checks: c.checks.slice(0, 10),
      scopeRequests: c.scopeRequests,
      dependants: deps.dependants(c.id),
      activity: deps.activity(c.id),
      audit: auditSink.entries().filter((e) => e.target.href === href),
      fix: fixFor(c),
      systemOwner: cat.owner,
    };
  }

  const audit = (c: Conn, action: 'connected' | 'revoked' | 'edited', summary: string, diff: { field: string; before?: string; after?: string }[], reason?: string) =>
    auditSink.log({ action, target: { type: 'integration', name: c.name, href: `/integrations/${c.id}` }, summary, diff, reason, owner: c.ownerTeam });

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

  const inView = (r: Integration, v: IntegrationView) =>
    v === 'all'
      ? true
      : v === 'attention'
        ? r.status === 'needs_reconnect' || r.status === 'error'
        : v === 'revoked'
          ? r.status === 'revoked'
          : r.status !== 'revoked' && !!r.expiresAt && new Date(r.expiresAt).getTime() - Date.now() < EXPIRING_MS && new Date(r.expiresAt).getTime() > Date.now();

  const ref = (c: Conn): ConnectionLink => ({ id: c.id, name: c.name, kind: catalogOf(c.catalogId).kind, status: statusOf(c), expiresAt: c.expiresAt, catalogId: c.catalogId, authMethod: c.authMethod, instanceUrl: c.instanceUrl });

  const checkCredential = (raw: string | undefined) => {
    const v = raw?.trim() ?? '';
    if (!v) throw new ApiError('Add the vault reference, e.g. vault://prod/integrations/servicenow/client-secret.', 400);
    if (LITERAL_RE.test(v) && !v.startsWith('vault://')) throw new ApiError('That looks like a secret. Paste the vault path that holds it, never the value.', 400);
    if (!VAULT_RE.test(v)) throw new ApiError('Use a vault path that starts with vault://, e.g. vault://prod/integrations/servicenow/client-secret.', 400);
    return v;
  };

  const api: IntegrationsApi = {
    list: (p) =>
      respond((m) => {
        const rows = visible().map(row);
        const src = m === 'empty' ? [] : rows;
        const viewCounts = { all: src.length, attention: 0, expiring: 0, revoked: 0 };
        for (const v of ['attention', 'expiring', 'revoked'] as const) viewCounts[v] = src.filter((r) => inView(r, v)).length;
        const rank: Record<IntegrationStatus, number> = { error: 0, needs_reconnect: 1, expiring: 2, revoked: 3, healthy: 4 };
        return {
          ...list(
            rows.filter((r) => inView(r, p.view)).sort((a, b) => rank[a.status] - rank[b.status] || a.name.localeCompare(b.name)),
            p,
            { text: (r) => `${r.name} ${r.instanceUrl} ${r.ownerTeam} ${catalogOf(r.catalogId).name}`, value: field, facetKeys: ['kind', 'authMethod', 'status', 'ownerTeam'] },
            m,
          ),
          viewCounts,
        };
      }),

    get: (cid) => respond(() => detail(find(cid))),

    options: () => respond(() => visible().map(ref)),

    catalog: () =>
      respond((m): CatalogSystem[] => {
        if (m === 'empty') return [];
        const vis = visible();
        return CATALOG.map((c) => {
          const mine = vis.filter((x) => x.catalogId === c.id);
          return { ...c, connected: mine.length, connectionId: mine.length === 1 ? mine[0].id : undefined };
        });
      }),

    connect: (input) =>
      respond(() => {
        const cat = catalogOf(input.catalogId);
        if (!cat.available) throw new ApiError(`${cat.name} is not available yet: ${cat.unavailableReason ?? 'not offered'}.`, 409);
        if (!cat.authMethods.includes(input.authMethod)) throw new ApiError(`${cat.name} does not accept that sign-in method.`, 400);
        const name = input.name.trim();
        if (!name) throw new ApiError('Name the connection.', 400);
        if (conns.some((c) => c.name.toLowerCase() === name.toLowerCase())) throw new ApiError(`A connection named ${name} already exists.`, 409);
        if (!input.scopes.length) throw new ApiError('Grant at least one scope.', 400);
        const unknown = input.scopes.filter((s) => !cat.scopes.some((x) => x.id === s));
        if (unknown.length) throw new ApiError(`${cat.name} does not offer ${unknown.join(', ')}.`, 400);
        if (!input.ownerTeam.trim()) throw new ApiError('Choose the owner team.', 400);
        if (!input.expiresAt || new Date(input.expiresAt).getTime() <= Date.now()) throw new ApiError('Choose an expiry date in the future.', 400);
        let credentialRef: string | undefined;
        if (input.authMethod === 'oauth_consent') {
          if (!input.consentBy) throw new ApiError('Sign in and grant consent first.', 400);
        } else credentialRef = checkCredential(input.credentialRef);
        const c: Conn = {
          id: id('int'),
          catalogId: cat.id,
          name,
          instanceUrl: input.instanceUrl.trim() || `https://${cat.instanceHint}`,
          tenant: cat.kind === 'm365' || cat.kind === 'sharepoint' ? 'northfield.onmicrosoft.com' : undefined,
          authMethod: input.authMethod,
          scopes: [...input.scopes],
          ownerTeam: input.ownerTeam,
          createdBy: me,
          createdAt: new Date().toISOString(),
          expiresAt: input.expiresAt,
          rotateBy: credentialRef ? inDays(90) : undefined,
          credentialRef,
          base: 'healthy',
          lastCheckedAt: new Date().toISOString(),
          checks: [],
          scopeRequests: [],
        };
        runCheck(c, me);
        conns.unshift(c);
        const granted = cat.scopes.filter((s) => c.scopes.includes(s.id)).map((s) => s.label);
        audit(c, 'connected', `Connected ${cat.name}`, [
          { field: 'Sign-in', after: input.authMethod === 'oauth_consent' ? `Consent by ${input.consentBy}` : credentialRef },
          { field: 'Scopes', after: granted.join(', ') },
          { field: 'Expires', after: new Date(c.expiresAt!).toLocaleDateString('en-CA', { dateStyle: 'medium' }) },
        ]);
        return row(c);
      }),

    reconnect: (cid) =>
      respond(() => {
        const c = find(cid);
        const before = statusOf(c);
        if (before === 'healthy') throw new ApiError('This connection is healthy; nothing to reconnect.', 409);
        c.base = 'healthy';
        c.lastError = undefined;
        if (!c.expiresAt || new Date(c.expiresAt).getTime() - Date.now() < EXPIRING_MS) c.expiresAt = inDays(c.authMethod === 'oauth_consent' ? 90 : 180);
        runCheck(c, me);
        deps.onStatus(c.id, false);
        audit(c, 'connected', c.authMethod === 'oauth_consent' ? 'Renewed consent; dependants resume' : 'Reconnected; dependants resume', [{ field: 'Status', before: STATUS_TEXT[before], after: 'Healthy' }]);
        return detail(c);
      }),

    rotate: (cid, credentialRef) =>
      respond(() => {
        const c = find(cid);
        if (c.authMethod === 'oauth_consent') throw new ApiError('OAuth consent has no stored credential; renew consent instead.', 400);
        if (c.base === 'revoked') throw new ApiError('Reconnect the connection before rotating its credential.', 409);
        const next = checkCredential(credentialRef);
        if (next === c.credentialRef) throw new ApiError('That is the reference already in use.', 400);
        const before = c.credentialRef;
        c.credentialRef = next;
        c.rotateBy = inDays(90);
        if (c.base === 'error') {
          c.base = 'healthy';
          c.lastError = undefined;
        }
        runCheck(c, me);
        audit(c, 'edited', 'Rotated the credential reference', [{ field: 'Credential', before, after: next }]);
        return detail(c);
      }),

    check: (cid) =>
      respond(() => {
        const c = find(cid);
        runCheck(c, me);
        return detail(c);
      }),

    bulkCheck: (ids) =>
      respond(() =>
        bulk(ids, (cid) => {
          const c = conns.find((x) => x.id === cid);
          if (!c || !inTeam(ownersOf(c))) return 'Not found';
          if (c.base === 'revoked') return 'Revoked; reconnect it instead';
          runCheck(c, me);
        }),
      ),

    impact: (ids) =>
      respond(() => {
        const ds = ids.flatMap((cid) => {
          const c = conns.find((x) => x.id === cid);
          return c && inTeam(ownersOf(c)) && c.base !== 'revoked' ? deps.dependants(c.id) : [];
        });
        return { dependants: ds, sources: ds.filter((d) => d.type === 'source').length, modules: ds.filter((d) => d.type === 'tool_module').length, mailboxes: ds.filter((d) => d.type === 'mailbox').length };
      }),

    revoke: (ids, reason) =>
      respond(() => {
        if (!reason.trim()) throw new ApiError('Say why the connection is revoked.', 400);
        return bulk(ids, (cid) => {
          const c = conns.find((x) => x.id === cid);
          if (!c || !inTeam(ownersOf(c))) return 'Not found';
          if (c.base === 'revoked') return 'Already revoked';
          const before = statusOf(c);
          const ds = deps.dependants(c.id);
          c.base = 'revoked';
          c.lastError = `Revoked by ${me}: ${reason.trim()}`;
          runCheck(c, me);
          deps.onStatus(c.id, true);
          audit(c, 'revoked', `Revoked the connection; ${ds.length ? ds.map((d) => d.name).join(', ') + ' stopped' : 'nothing used it'}`, [{ field: 'Status', before: STATUS_TEXT[before], after: 'Revoked' }, { field: 'Dependants affected', after: String(ds.length) }], reason.trim());
        });
      }),

    requestScopes: (cid, input) =>
      respond(() => {
        const c = find(cid);
        const cat = catalogOf(c.catalogId);
        const wanted = input.scopes.filter((s) => !c.scopes.includes(s));
        if (!wanted.length) throw new ApiError('Choose at least one scope the connection does not already have.', 400);
        if (!input.justification.trim()) throw new ApiError('Say what the extra scopes are for.', 400);
        if (c.scopeRequests.some((r) => r.status === 'pending')) throw new ApiError(`A scope request is already waiting for ${cat.owner}.`, 409);
        c.scopeRequests.unshift({ id: id('sr'), scopes: wanted, justification: input.justification.trim(), requestedBy: me, requestedAt: new Date().toISOString(), approver: cat.owner, status: 'pending' });
        audit(c, 'edited', `Requested ${wanted.length === 1 ? 'a scope' : `${wanted.length} scopes`}; waiting for ${cat.owner}`, [{ field: 'Requested scopes', after: cat.scopes.filter((s) => wanted.includes(s.id)).map((s) => s.label).join(', ') }], input.justification.trim());
        return detail(c);
      }),
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
        tenant: 'northfield.onmicrosoft.com',
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

const STATUS_TEXT: Record<IntegrationStatus, string> = { healthy: 'Healthy', needs_reconnect: 'Needs reconnect', expiring: 'Expiring', revoked: 'Revoked', error: 'Error' };
