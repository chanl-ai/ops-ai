import type { Tool, ToolType } from '@/lib/types/domain';
import type { ToolCallDetail, ToolCallRow } from '@/lib/types/governance';
import type {
  CredentialKind,
  DiscoveredOperation,
  Environment,
  ModuleApproval,
  ModuleOperation,
  ModuleRef,
  ModuleType,
  ModuleVersion,
  ModuleView,
  OperationChange,
  RunContextOption,
  SchemaField,
  SecurityReview,
  SubjectBinding,
  ToolModule,
  ToolModuleDetail,
} from '@/lib/types/tool-modules';

import { ApiError } from '../../contract';
import type { ToolModulesApi } from '../../tool-modules-contract';
import * as F from '../fixtures';
import { rng } from '../governance/catalog';
import { seedToolCalls } from '../governance/seed-calls';
import { bulk, id, list, notFound, respond } from '../runtime';
import { guardTeam, inTeam, teamOwner } from '../teams';
import { MODULE_CONNECTION } from '../integrations/seed';
import type { ConnectionLink } from '../integrations';
import { daysAgo, DAY, DISCOVERY, f, inDays, MODULE_SEEDS, RUN_CONTEXTS, type ModuleSeed } from './seed';

interface Op {
  id: string;
  toolId: string;
  name: string;
  method?: ModuleOperation['method'];
  path?: string;
  input: SchemaField[];
  maskedOutput: string[];
  binding: SubjectBinding | null;
  rateLimitPerMin: number;
  requiresApproval: boolean;
  amountMax?: number;
  stub: Record<string, unknown>;
}

interface Mod {
  id: string;
  name: string;
  displayName: string;
  system: string;
  description: string;
  type: ModuleType;
  status: ToolModule['status'];
  ownerTeam: string;
  ownerContacts: string[];
  endpoint: string;
  auth: { kind: CredentialKind | 'none'; header?: string };
  timeoutMs: number;
  egressHosts: string[];
  dataClassification: ToolModuleDetail['dataClassification'];
  catalogId?: string;
  reachable: boolean;
  drift: boolean;
  updatedAt: string;
  version: string;
  ops: Op[];
  approvals: ModuleApproval[];
  reviews: SecurityReview[];
  versions: ModuleVersion[];
  connectionId?: string;
  pending: OperationChange[];
  /** Operations and their tool flags as they were before the first staged change, for discard. */
  baseline: { ops: Op[]; tools: Record<string, Pick<Tool, 'enabled' | 'description'>> } | null;
}

type AgentLike = { id: string; slug: string; toolIds: string[] };

const EXPIRING_MS = 30 * DAY;
const FAILING_RATE = 0.02;
const majorOf = (v: string) => Number(v.split('.')[0]);
const toolTypeOf = (t: ModuleType): ToolType => (t === 'mcp' ? 'mcp' : t === 'code' ? 'code' : 'http');
const kebab = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const wfName = (wid: string) => F.WORKFLOWS.find((w) => w.id === wid)?.name ?? wid;
const wfOwner = (wid: string) => F.WORKFLOWS.find((w) => w.id === wid)?.owner;

const DENY_TEXT: Record<string, string> = {
  no_approval: 'This workflow has no approval for the module.',
  approval_expired: 'The workflow’s approval for this module has expired.',
  operation_not_approved: 'The workflow’s approval does not include this operation.',
  operation_hidden: 'The operation is hidden in this module.',
  subject_unbound: 'The case has no bound value for this record, so the call cannot name one.',
  subject_mismatch: 'The input names a different record from the one bound to the case.',
  constraint: 'The amount is above the operation’s limit.',
  approval_token_missing: 'This call needs an approval token bound to this input. Simulate the approval to continue the test, or run it against the stub.',
  module_not_published: 'The module is not published, so only the stub can be called.',
};

/**
 * Tool modules over the shared tool records: each operation is one grantable tool, so agents keep granting tools
 * while the module holds the manifest, approvals and reviews. The credential lives on the module's integration.
 */
export function createToolModulesMock(deps: { tools: Tool[]; agents: AgentLike[]; connection: (id?: string) => ConnectionLink | undefined }): {
  api: ToolModulesApi;
  /** Modules calling through a connection, for its Used by tab. */
  using: (connId: string) => ToolModule[];
  /** A module's latest gateway calls, newest first. */
  recentCalls: (moduleId: string, n: number) => ToolCallRow[];
} {
  const { tools, agents } = deps;
  const me = F.CURRENT_USER.name;
  const toolOf = (o: Op) => tools.find((t) => t.id === o.toolId)!;
  let calls: ToolCallDetail[] | null = null;
  const allCalls = () => (calls ??= seedToolCalls());

  const grantToWorkflowAgent = (wid: string, toolId: string) => {
    const slug = F.WORKFLOWS.find((w) => w.id === wid)?.agentSlugs[0];
    const a = agents.find((x) => x.slug === slug);
    const t = tools.find((x) => x.id === toolId);
    if (!a || !t) return;
    if (!a.toolIds.includes(toolId)) a.toolIds.push(toolId);
    if (!t.grantedAgentIds.includes(a.id)) t.grantedAgentIds.push(a.id);
  };

  const sampleInput = (fields: SchemaField[]) => JSON.stringify(Object.fromEntries(fields.filter((x) => x.required).map((x) => [x.name, x.example ?? ''])), null, 2);

  function fromSeed(s: ModuleSeed): Mod {
    const ops: Op[] = s.operations.map((o, i) => {
      let t = tools.find((x) => x.name === o.name);
      if (!t) {
        const base = o.tool ?? { description: o.name, access: 'read' as const, calls24h: 0, errorRate: 0, p95Ms: 0 };
        t = { id: `tl_${o.name}`, name: o.name, description: base.description, type: toolTypeOf(s.type), system: s.system, access: base.access, requiresReview: base.access !== 'read' && o.requiresApproval !== false, enabled: base.enabled ?? true, calls24h: base.calls24h, errorRate: base.errorRate, p95Ms: base.p95Ms, grantedAgentIds: [], sampleInput: sampleInput(o.input) };
        tools.push(t);
      }
      Object.assign(t, { moduleId: s.id, module: s.displayName, system: s.system, type: toolTypeOf(s.type) });
      const money = t.access === 'money_movement';
      return { id: `${s.id}_op${i + 1}`, toolId: t.id, name: o.name, method: o.method, path: o.path, input: o.input, maskedOutput: o.masked ?? [], binding: o.binding, rateLimitPerMin: o.rate ?? 60, requiresApproval: money || (t.access === 'write' && o.requiresApproval !== false), amountMax: o.amountMax, stub: o.stub };
    });
    const last = s.versions[s.versions.length - 1];
    const status = s.status ?? 'published';
    const versions: ModuleVersion[] = s.versions.map((v, i) => {
      const isLast = i === s.versions.length - 1;
      return {
        version: v.version,
        major: majorOf(v.version),
        status: isLast ? (status === 'in_review' ? 'in_review' : 'published') : 'deprecated',
        publishedAt: status === 'in_review' && isLast ? undefined : daysAgo(v.daysAgo),
        publishedBy: v.by,
        note: v.note,
        changes: v.changes,
        pinnedBy: (v.pinnedBy ?? []).map((w) => ({ id: w, name: wfName(w) })),
        reachability: isLast ? [{ environment: 'production', ok: s.reachable !== false, checkedAt: daysAgo(0.01) }, { environment: 'test', ok: true, checkedAt: daysAgo(0.02) }] : [{ environment: 'production', ok: true, checkedAt: daysAgo(v.daysAgo) }],
      };
    });
    const majors = [...new Set(s.versions.map((v) => majorOf(v.version)))];
    const reviews: SecurityReview[] = majors.map((mj) => {
      const first = s.versions.find((v) => majorOf(v.version) === mj)!;
      const current = mj === majorOf(last.version);
      const pending = current && s.reviewPending;
      return {
        id: `${s.id}_rev${mj}`,
        major: mj,
        version: first.version,
        decision: pending ? 'pending' : 'approved',
        requestedBy: first.by,
        requestedAt: daysAgo(first.daysAgo + 3),
        reviewer: pending ? undefined : s.reviewer,
        decidedAt: pending ? undefined : daysAgo(first.daysAgo + 1),
        findings: current ? (s.findings ?? []) : ['Reviewed; superseded by the next major version'],
      };
    });
    const approvals: ModuleApproval[] = s.approvals.map((a, i) => {
      const requested = a.status === 'requested';
      const age = a.ageDays ?? 30 + ((i * 37) % 120);
      return {
        id: `${s.id}_apr${i + 1}`,
        workflowId: a.workflowId,
        workflowName: wfName(a.workflowId),
        environment: a.environment ?? 'production',
        major: majorOf(last.version),
        operations: a.operations,
        constraints: a.constraints,
        requestedBy: a.requestedBy ?? ['Maya Okafor', 'Priya Shah', 'Anika Singh'][i % 3],
        justification: a.justification,
        requestedAt: daysAgo(age + 1),
        decidedBy: requested ? undefined : a.decidedBy,
        decidedAt: requested ? undefined : daysAgo(age),
        status: a.status ?? 'approved',
        expiresAt: a.expiresIn != null ? inDays(a.expiresIn) : undefined,
      };
    });
    for (const a of approvals) if (a.status === 'approved') for (const name of a.operations) if (s.operations.find((o) => o.name === name)?.tool) grantToWorkflowAgent(a.workflowId, ops.find((o) => o.name === name)!.toolId);
    return {
      id: s.id,
      name: s.name,
      displayName: s.displayName,
      system: s.system,
      description: s.description,
      type: s.type,
      status,
      ownerTeam: s.ownerTeam,
      ownerContacts: s.ownerContacts,
      endpoint: s.endpoint,
      auth: { kind: s.auth, header: s.authHeader },
      timeoutMs: s.timeoutMs,
      egressHosts: s.egressHosts,
      dataClassification: s.dataClassification,
      catalogId: s.catalogId,
      reachable: s.reachable !== false,
      drift: !!s.drift,
      updatedAt: daysAgo(last.daysAgo),
      version: last.version,
      ops,
      approvals,
      reviews,
      versions,
      connectionId: MODULE_CONNECTION[s.id],
      pending: [],
      baseline: null,
    };
  }

  const mods: Mod[] = MODULE_SEEDS.map(fromSeed);
  // A tool not yet in any module (created before modules existed) gets nothing here; every seeded tool is covered.

  // ── Derived views ─────────────────────────────────────────────────────────
  const approvalStatus = (a: ModuleApproval): ModuleApproval['status'] => (a.status === 'approved' && a.expiresAt && new Date(a.expiresAt).getTime() < Date.now() ? 'expired' : a.status);
  const approvalsOf = (m: Mod) => m.approvals.map((a) => ({ ...a, status: approvalStatus(a) }));
  const ownersOf = (m: Mod) => [m.ownerTeam, ...m.approvals.map((a) => wfOwner(a.workflowId))];

  function row(m: Mod): ToolModule {
    const conn = deps.connection(m.connectionId);
    const ops = m.ops.map((o) => ({ o, t: toolOf(o) }));
    const live = ops;
    const calls24h = live.reduce((s, { t }) => s + t.calls24h, 0);
    const errors = live.reduce((s, { t }) => s + t.calls24h * t.errorRate, 0);
    const approvals = approvalsOf(m);
    const active = approvals.filter((a) => a.status === 'approved');
    const expired = approvals.filter((a) => a.status === 'expired');
    const pendingApprovals = approvals.filter((a) => a.status === 'requested').length;
    const nextExpiry = active.map((a) => a.expiresAt).filter((x): x is string => !!x).sort()[0];
    const reviewOpen = m.reviews.some((r) => r.decision !== 'approved');
    const approvalState: ToolModule['approvalState'] =
      m.status === 'draft'
        ? 'draft'
        : m.status !== 'published' || reviewOpen || m.drift || pendingApprovals
          ? 'needs_approval'
          : !active.length && expired.length
            ? 'expired'
            : nextExpiry && new Date(nextExpiry).getTime() - Date.now() < EXPIRING_MS
              ? 'expiring'
              : 'approved';
    const workflows: ModuleRef[] = [...new Map(active.map((a) => [a.workflowId, { id: a.workflowId, name: a.workflowName }])).values()];
    return {
      id: m.id,
      name: m.name,
      displayName: m.displayName,
      system: m.system,
      description: m.description,
      type: m.type,
      status: m.status,
      version: m.version,
      major: majorOf(m.version),
      ownerTeam: m.ownerTeam,
      endpoint: m.endpoint,
      operationCount: m.ops.length,
      accessClasses: (['read', 'write', 'money_movement'] as const).filter((acc) => ops.some(({ t }) => t.access === acc)),
      approvalState,
      nextExpiry,
      pendingApprovals,
      workflows,
      calls24h,
      errorRate: calls24h ? errors / calls24h : 0,
      p95Ms: Math.max(0, ...live.filter(({ t }) => t.calls24h).map(({ t }) => t.p95Ms)),
      // A connection that is revoked, expired or failing makes the system unreachable from the gateway.
      reachable: m.reachable && !['revoked', 'needs_reconnect', 'error'].includes(conn?.status ?? ''),
      drift: m.drift,
      connectionId: m.connectionId,
      connection: conn ? { id: conn.id, name: conn.name, kind: conn.kind, status: conn.status, expiresAt: conn.expiresAt } : null,
      updatedAt: m.updatedAt,
    };
  }

  const inView = (r: ToolModule, v: ModuleView) =>
    v === 'all'
      ? true
      : v === 'needs_approval'
        ? r.approvalState === 'needs_approval' || r.approvalState === 'draft'
        : v === 'expired'
          ? r.approvalState === 'expired'
          : v === 'expiring'
            ? r.approvalState !== 'expired' && !!r.nextExpiry && new Date(r.nextExpiry).getTime() - Date.now() < EXPIRING_MS
            : r.errorRate >= FAILING_RATE || !r.reachable;

  function runContexts(m: Mod): RunContextOption[] {
    // Only the current team's workflows: running as another team's workflow would borrow its approval.
    const wids = [...new Set(m.approvals.map((a) => a.workflowId))].filter((w) => inTeam(wfOwner(w)));
    return wids.flatMap((w) => (RUN_CONTEXTS[w] ?? []).map((c) => ({ id: `${w}:${c.caseId}`, label: `${c.caseId} · ${c.label}`, workflowId: w, workflowName: wfName(w), caseId: c.caseId, bindings: c.bindings })));
  }

  function detail(m: Mod): ToolModuleDetail {
    const approvals = approvalsOf(m);
    const order: Record<ModuleApproval['status'], number> = { requested: 0, approved: 1, expired: 2, rejected: 3, revoked: 4 };
    return {
      ...row(m),
      ownerContacts: m.ownerContacts,
      auth: m.auth,
      timeoutMs: m.timeoutMs,
      egressHosts: m.egressHosts,
      dataClassification: m.dataClassification,
      operations: m.ops.map((o) => {
        const t = toolOf(o);
        return {
          id: o.id,
          toolId: o.toolId,
          name: o.name,
          description: t.description,
          access: t.access,
          enabled: t.enabled,
          method: o.method,
          path: o.path,
          input: o.input,
          maskedOutput: o.maskedOutput,
          binding: o.binding,
          rateLimitPerMin: o.rateLimitPerMin,
          requiresApproval: o.requiresApproval,
          fourEyes: t.access === 'money_movement',
          amountMax: o.amountMax,
          idempotent: t.access !== 'read',
          // Last 24 hours as measured; hiding is staged and does not rewrite history.
          calls24h: t.calls24h,
          errorRate: t.errorRate,
          p95Ms: t.p95Ms,
          approvedWorkflows: new Set(approvals.filter((a) => a.status === 'approved' && a.operations.includes(o.name)).map((a) => a.workflowId)).size,
        };
      }),
      pendingChanges: m.pending,
      approvals: approvals.sort((a, b) => order[a.status] - order[b.status] || (a.expiresAt ?? '9').localeCompare(b.expiresAt ?? '9')),
      reviews: [...m.reviews].reverse(),
      versions: [...m.versions].reverse(),
      runContexts: runContexts(m),
    };
  }

  const find = (mid: string) => {
    const m = mods.find((x) => x.id === mid) ?? notFound('Module');
    guardTeam(ownersOf(m), 'module');
    return m;
  };
  const holdersOf = (m: Mod) => [...new Set(approvalsOf(m).filter((a) => a.status === 'approved').map((a) => a.workflowName))];
  const drop = (m: Mod) => {
    for (const o of m.ops) {
      const i = tools.findIndex((t) => t.id === o.toolId);
      if (i >= 0) tools.splice(i, 1);
      for (const a of agents) a.toolIds = a.toolIds.filter((x) => x !== o.toolId);
    }
    mods.splice(mods.indexOf(m), 1);
  };
  const touch = (m: Mod) => {
    m.updatedAt = new Date().toISOString();
  };

  function stage(m: Mod, changes: OperationChange[]) {
    if (!changes.length) return;
    for (const c of changes) {
      const i = m.pending.findIndex((p) => p.operation === c.operation && p.kind === c.kind);
      if (i >= 0) m.pending[i] = c;
      else m.pending.push(c);
    }
  }

  function bumped(m: Mod, major: boolean) {
    const [a, b] = m.version.split('.').map(Number);
    return major ? `${a + 1}.0.0` : `${a}.${b + 1}.0`;
  }

  function discovered(source: Parameters<ToolModulesApi['discover']>[0]) {
    const conn = deps.connection(source.connectionId);
    if (source.connectionId && !conn) throw new ApiError('That connection no longer exists. Pick another one.', 400);
    if (conn?.status === 'revoked') throw new ApiError(`${conn.name} is revoked. Reconnect it in Integrations first.`, 409);
    const known = conn ? DISCOVERY[conn.catalogId] : undefined;
    if (source.kind === 'mcp') {
      let host: string;
      try {
        const u = new URL(source.url);
        host = u.hostname;
        if (u.protocol !== 'https:') throw new ApiError('Use an https address; the gateway does not call plain http.', 400);
      } catch (e) {
        if (e instanceof ApiError) throw e;
        throw new ApiError('That is not a complete address. Enter it with https://.', 400);
      }
      const d = known ?? (host.includes('servicenow') ? DISCOVERY.cat_servicenow : DISCOVERY.mcp);
      const label = host.split('.')[0];
      const system = host.includes('servicenow') || conn?.catalogId === 'cat_servicenow' ? 'ServiceNow' : label.charAt(0).toUpperCase() + label.slice(1);
      return { type: 'mcp' as const, system, suggestedName: kebab(system), version: d.version, endpoint: source.url, operations: d.operations, warnings: d.warnings ?? [] };
    }
    const ref = source.specUrl || source.fileName;
    if (!ref) throw new ApiError('Add the spec as a URL or a file.', 400);
    const base = (source.fileName ?? new URL(source.specUrl!).hostname).split(/[./]/)[0];
    const system = base.charAt(0).toUpperCase() + base.slice(1);
    const d = known ?? DISCOVERY.openapi;
    return { type: 'openapi' as const, system, suggestedName: kebab(system), version: d.version, endpoint: source.specUrl ? source.specUrl.replace(/\/[^/]*$/, '') : `https://${kebab(system)}.northfield.internal/api`, operations: d.operations, warnings: d.warnings ?? [] };
  }

  const api: ToolModulesApi = {
    list: (p) =>
      respond((md) => {
        const scoped = mods.filter((m) => inTeam(ownersOf(m))).map(row);
        const src = md === 'empty' ? [] : scoped;
        const viewCounts = { all: src.length, needs_approval: 0, expiring: 0, expired: 0, failing: 0 };
        for (const v of ['needs_approval', 'expiring', 'expired', 'failing'] as const) viewCounts[v] = src.filter((r) => inView(r, v)).length;
        const calls24h = src.reduce((s, r) => s + r.calls24h, 0);
        const errors = src.reduce((s, r) => s + r.calls24h * r.errorRate, 0);
        const scopedMods = mods.filter((m) => src.some((r) => r.id === m.id));
        return {
          ...list(
            scoped.filter((r) => inView(r, p.view)),
            p,
            {
              text: (r) => `${r.displayName} ${r.name} ${r.system} ${r.description} ${r.ownerTeam}`,
              value: (r, k) => (k === 'access' ? r.accessClasses : String((r as unknown as Record<string, unknown>)[k])),
              facetKeys: ['type', 'access', 'approvalState'],
            },
            md,
          ),
          stats: {
            modules: src.length,
            operations: src.reduce((s, r) => s + r.operationCount, 0),
            calls24h,
            errorRate: calls24h ? errors / calls24h : 0,
            moneyOperations: scopedMods.reduce((s, m) => s + m.ops.filter((o) => toolOf(o).access === 'money_movement').length, 0),
            expiringModules: viewCounts.expiring,
            expiringApprovals: scopedMods.reduce((s, m) => s + approvalsOf(m).filter((a) => a.status === 'approved' && a.expiresAt && new Date(a.expiresAt).getTime() - Date.now() < EXPIRING_MS).length, 0),
          },
          viewCounts,
        };
      }),

    get: (mid) => respond(() => detail(find(mid))),

    discover: (source) => respond(() => discovered(source)),

    create: (input) =>
      respond(() => {
        const name = kebab(input.name);
        if (!name) throw new ApiError('Name the module.', 400);
        if (mods.some((m) => m.name === name)) throw new ApiError(`A module named ${name} already exists.`, 409);
        if (!input.displayName.trim()) throw new ApiError('Give the module a display name.', 400);
        let opsIn: DiscoveredOperation[] = input.operations ?? [];
        let endpoint = input.endpoint;
        const conn = deps.connection(input.connectionId);
        if (!conn) throw new ApiError('Choose the connection this module calls through.', 400);
        if (conn.status === 'revoked') throw new ApiError(`${conn.name} is revoked. Reconnect it in Integrations or pick another connection.`, 409);
        if (input.type === 'code') throw new ApiError('Code modules need the sandbox, which is not available yet.', 422);
        if (input.http) {
          const h = input.http;
          const keyLike = h.headers.find((x) => /^(authorization|x-api-key|cookie)$/i.test(x.key.trim()) && x.value.trim() && !/^\{\{[A-Z][A-Z0-9_]*\}\}$/.test(x.value.trim()));
          if (keyLike) throw new ApiError(`The ${keyLike.key} header holds a literal value. Reference the vault instead, e.g. {{CORE_API_KEY}}.`, 400);
          let url: URL;
          try {
            url = new URL(h.url.replace(/\{([a-zA-Z0-9_]+)\}/g, 'x'));
          } catch {
            throw new ApiError('Enter the full https URL of the operation.', 400);
          }
          endpoint = url.origin;
          const path = h.url.slice(url.origin.length) || '/';
          const vars = [...new Set([...h.url.matchAll(/\{([a-zA-Z0-9_]+)\}/g), ...(h.body ?? '').matchAll(/\{\{\s*([a-z][a-zA-Z0-9_]*)\s*\}\}/g)].map((m) => m[1]))];
          opsIn = [{ name: kebab(h.name).replace(/-/g, '_'), description: h.description, access: h.access, method: h.method, path, group: 'operations', input: vars.map((v) => f(v, 'string', true)) }];
        }
        if (!opsIn.length) throw new ApiError('Choose at least one operation to expose.', 400);
        for (const o of opsIn) if (tools.some((t) => t.name === o.name)) throw new ApiError(`An operation named ${o.name} already exists in another module.`, 409);
        const mid = id('mod');
        const version = input.http ? '1.0.0' : (DISCOVERY[conn.catalogId]?.version ?? '1.0.0');
        const owner = teamOwner() ?? 'Platform';
        const ops: Op[] = opsIn.map((o, i) => {
          const t: Tool = { id: id('tl'), name: o.name, description: o.description, type: toolTypeOf(input.type), system: input.system, access: o.access, requiresReview: o.access !== 'read', enabled: true, calls24h: 0, errorRate: 0, p95Ms: 0, grantedAgentIds: [], sampleInput: sampleInput(o.input), moduleId: mid, module: input.displayName };
          tools.unshift(t);
          return { id: `${mid}_op${i + 1}`, toolId: t.id, name: o.name, method: o.method, path: o.path, input: o.input, maskedOutput: [], binding: null, rateLimitPerMin: 60, requiresApproval: o.access !== 'read', amountMax: undefined, stub: { ok: true } };
        });
        const kind: CredentialKind = conn.authMethod === 'api_key' ? 'api_key' : conn.authMethod === 'mtls' ? 'mtls' : 'oauth_client_credentials';
        const m: Mod = {
          id: mid,
          name,
          displayName: input.displayName.trim(),
          system: input.system.trim() || input.displayName.trim(),
          description: `${input.system} operations behind the data gateway.`,
          type: input.type,
          status: 'draft',
          ownerTeam: owner,
          ownerContacts: [me],
          endpoint,
          auth: { kind },
          timeoutMs: 8000,
          egressHosts: (() => {
            try {
              return [new URL(endpoint).hostname];
            } catch {
              return [];
            }
          })(),
          dataClassification: 'confidential',
          catalogId: conn.catalogId,
          reachable: true,
          drift: false,
          updatedAt: new Date().toISOString(),
          version,
          ops,
          approvals: [],
          reviews: [],
          versions: [{ version, major: majorOf(version), status: 'draft', publishedBy: me, note: 'First version', changes: opsIn.map((o) => ({ operation: o.name, kind: 'added' as const, detail: `New ${o.access === 'money_movement' ? 'money movement' : o.access} operation`, major: true })), pinnedBy: [], reachability: [{ environment: 'test', ok: true, checkedAt: new Date().toISOString() }] }],
          connectionId: conn.id,
          pending: [],
          baseline: null,
        };
        mods.unshift(m);
        return detail(m);
      }),

    remove: (mid) =>
      respond(() => {
        const m = find(mid);
        const holders = holdersOf(m);
        if (holders.length) throw new ApiError(`${holders.join(', ')} ${holders.length === 1 ? 'holds an approval' : 'hold approvals'} for this module. Revoke ${holders.length === 1 ? 'it' : 'them'} first.`, 409);
        drop(m);
      }),

    bulkRemove: (ids) =>
      respond(() =>
        bulk(ids, (mid) => {
          const m = mods.find((x) => x.id === mid);
          if (!m || !inTeam(ownersOf(m))) return 'Not found';
          const holders = holdersOf(m);
          if (holders.length) return `Approved for ${holders.length === 1 ? holders[0] : `${holders.length} workflows`}`;
          drop(m);
        }),
      ),

    updateOperation: (mid, opId, patch) =>
      respond(() => {
        const m = find(mid);
        const o = m.ops.find((x) => x.id === opId) ?? notFound('Operation');
        const t = toolOf(o);
        const money = t.access === 'money_movement';
        if (patch.requiresApproval === false && money) throw new ApiError('Operations that move money always need a person’s approval.', 422);
        if (patch.rateLimitPerMin !== undefined && (!Number.isInteger(patch.rateLimitPerMin) || patch.rateLimitPerMin < 1 || patch.rateLimitPerMin > 10_000)) throw new ApiError('Set a rate limit between 1 and 10,000 calls a minute.', 400);
        if (patch.amountMax !== undefined && (!money || patch.amountMax <= 0)) throw new ApiError('Only money movement operations take an amount limit, and it must be above zero.', 400);
        if (patch.binding && !o.input.some((x) => x.name === patch.binding!.arg)) throw new ApiError(`${patch.binding.arg} is not an input of ${o.name}.`, 400);
        if (!m.baseline) m.baseline = { ops: structuredClone(m.ops), tools: Object.fromEntries(m.ops.map((x) => [x.toolId, { enabled: toolOf(x).enabled, description: toolOf(x).description }])) };
        const changes: OperationChange[] = [];
        if (patch.enabled !== undefined && patch.enabled !== t.enabled) {
          // Hiding an operation a workflow is approved for breaks that workflow, so it is a major change.
          const users = [...new Set(approvalsOf(m).filter((a) => a.status === 'approved' && a.operations.includes(o.name)).map((a) => a.workflowName))];
          changes.push(
            patch.enabled
              ? { operation: o.name, kind: 'added', detail: 'Exposed to workflows', major: true }
              : users.length
                ? { operation: o.name, kind: 'removed', detail: `Hidden from workflows; breaks ${users.join(', ')}, which ${users.length === 1 ? 'calls' : 'call'} it`, major: true }
                : { operation: o.name, kind: 'removed', detail: 'Hidden from workflows; no workflow is approved for it', major: false },
          );
          t.enabled = patch.enabled;
        }
        if (patch.requiresApproval !== undefined && patch.requiresApproval !== o.requiresApproval) {
          changes.push({ operation: o.name, kind: 'settings', detail: patch.requiresApproval ? 'Every call waits for an approval' : 'Calls no longer wait for a person', major: !patch.requiresApproval });
          o.requiresApproval = patch.requiresApproval;
          t.requiresReview = patch.requiresApproval;
        }
        if (patch.rateLimitPerMin !== undefined && patch.rateLimitPerMin !== o.rateLimitPerMin) {
          changes.push({ operation: o.name, kind: 'settings', detail: `Rate limit ${o.rateLimitPerMin} → ${patch.rateLimitPerMin} a minute`, major: false });
          o.rateLimitPerMin = patch.rateLimitPerMin;
        }
        if (patch.amountMax !== undefined && patch.amountMax !== o.amountMax) {
          changes.push({ operation: o.name, kind: 'settings', detail: `Amount limit $${o.amountMax ?? 0} → $${patch.amountMax}`, major: patch.amountMax > (o.amountMax ?? 0) });
          o.amountMax = patch.amountMax;
        }
        if (patch.description !== undefined && patch.description.trim() !== t.description) {
          changes.push({ operation: o.name, kind: 'settings', detail: 'Description edited', major: false });
          t.description = patch.description.trim();
        }
        if (patch.binding !== undefined && JSON.stringify(patch.binding) !== JSON.stringify(o.binding)) {
          const b = patch.binding;
          const widened = !b || (!!o.binding && ((o.binding.required && !b.required) || (o.binding.mode === 'equals' && b.mode === 'within')));
          changes.push({ operation: o.name, kind: 'binding_changed', detail: b ? `${b.arg} ${b.mode === 'equals' ? '=' : 'within'} ${b.bindTo}${b.required ? '' : ', optional'}` : 'No record binding', major: widened });
          o.binding = b;
        }
        if (!changes.length) throw new ApiError('Nothing changed.', 400);
        stage(m, changes);
        touch(m);
        return detail(m);
      }),

    publishVersion: (mid, note) =>
      respond(() => {
        const m = find(mid);
        if (!m.pending.length) throw new ApiError('There are no changes to publish.', 400);
        if (!note.trim()) throw new ApiError('Say what changed.', 400);
        const major = m.pending.some((c) => c.major);
        const version = bumped(m, major);
        if (!major) for (const v of m.versions) if (v.status === 'published') v.status = 'deprecated';
        m.versions.push({ version, major: majorOf(version), status: major ? 'in_review' : 'published', publishedAt: major ? undefined : new Date().toISOString(), publishedBy: me, note: note.trim(), changes: m.pending, pinnedBy: [], reachability: [{ environment: 'test', ok: true, checkedAt: new Date().toISOString() }] });
        if (major) m.reviews.push({ id: id('rev'), major: majorOf(version), version, decision: 'pending', requestedBy: me, requestedAt: new Date().toISOString(), findings: [], note: note.trim() });
        m.version = version;
        m.pending = [];
        m.baseline = null;
        touch(m);
        return detail(m);
      }),

    discardChanges: (mid) =>
      respond(() => {
        const m = find(mid);
        if (!m.baseline) throw new ApiError('There are no changes to discard.', 400);
        m.ops = m.baseline.ops;
        for (const [tid, v] of Object.entries(m.baseline.tools)) Object.assign(tools.find((t) => t.id === tid) ?? {}, v);
        m.pending = [];
        m.baseline = null;
        return detail(m);
      }),

    requestReview: (mid, note) =>
      respond(() => {
        const m = find(mid);
        if (m.reviews.some((r) => r.decision === 'pending')) throw new ApiError('A security review is already open for this module.', 409);
        m.reviews.push({ id: id('rev'), major: majorOf(m.version), version: m.version, decision: 'pending', requestedBy: me, requestedAt: new Date().toISOString(), findings: [], note: note.trim() || undefined });
        if (m.status === 'draft') m.status = 'in_review';
        const v = m.versions[m.versions.length - 1];
        if (v.status === 'draft') v.status = 'in_review';
        touch(m);
        return detail(m);
      }),

    requestApproval: (mid, input) =>
      respond(() => {
        const m = find(mid);
        if (m.status === 'draft') throw new ApiError('Submit the module for security review before workflows can request it.', 409);
        if (!F.WORKFLOWS.some((w) => w.id === input.workflowId)) throw new ApiError('Choose a workflow.', 400);
        if (!input.operations.length) throw new ApiError('Choose at least one operation.', 400);
        const max = input.environment === 'production' ? 365 : 90;
        if (input.expiresInDays < 1 || input.expiresInDays > max) throw new ApiError(`${input.environment === 'production' ? 'Production' : 'Test'} approvals last at most ${max} days.`, 400);
        if (input.justification.trim().length < 10) throw new ApiError('Explain why the workflow needs these operations.', 400);
        if (approvalsOf(m).some((a) => a.workflowId === input.workflowId && a.status === 'requested')) throw new ApiError(`${wfName(input.workflowId)} already has an open request for this module.`, 409);
        const a: ModuleApproval = { id: id('apr'), workflowId: input.workflowId, workflowName: wfName(input.workflowId), environment: input.environment, major: majorOf(m.version), operations: input.operations, requestedBy: me, justification: input.justification.trim(), requestedAt: new Date().toISOString(), status: 'requested', expiresAt: inDays(input.expiresInDays) };
        m.approvals.push(a);
        return a;
      }),

    decideApproval: (mid, aid, decision, reason) =>
      respond(() => {
        const m = find(mid);
        const a = m.approvals.find((x) => x.id === aid) ?? notFound('Approval');
        if (a.status !== 'requested') throw new ApiError('This request was already decided.', 409);
        if (a.requestedBy === me) throw new ApiError(`You requested this. Someone else in ${m.ownerTeam} must decide it.`, 403);
        if (decision === 'rejected' && !reason?.trim()) throw new ApiError('Give a reason for the rejection.', 400);
        Object.assign(a, { status: decision, decidedBy: me, decidedAt: new Date().toISOString(), reason: reason?.trim() || undefined });
        if (decision === 'approved') for (const name of a.operations) grantToWorkflowAgent(a.workflowId, m.ops.find((o) => o.name === name)?.toolId ?? '');
        return a;
      }),

    revokeApprovals: (mid, ids, reason) =>
      respond(() => {
        const m = find(mid);
        if (!reason.trim()) throw new ApiError('Give a reason.', 400);
        return bulk(ids, (aid) => {
          const a = m.approvals.find((x) => x.id === aid);
          if (!a) return 'Not found';
          const s = approvalStatus(a);
          if (s !== 'approved' && s !== 'requested') return s === 'expired' ? 'Already expired' : `Already ${s}`;
          Object.assign(a, { status: 'revoked', reason: reason.trim(), decidedBy: me, decidedAt: new Date().toISOString() });
        });
      }),

    test: (mid, input) =>
      respond(() => {
        const m = find(mid);
        const o = m.ops.find((x) => x.name === input.operation) ?? notFound('Operation');
        const t = toolOf(o);
        const ctx = runContexts(m).find((c) => c.id === input.contextId);
        if (!ctx && input.contextId !== 'owner') throw new ApiError('Choose a run context.', 400);
        const callId = `test_${Math.random().toString(36).slice(2, 10)}`;
        const deny = (reason: string) => ({ decision: 'deny' as const, denyReason: reason, denyMessage: DENY_TEXT[reason], status: 403, latencyMs: 4 + Math.round(Math.random() * 8), bound: [], wouldPause: false, output: { error: reason, message: DENY_TEXT[reason] }, masked: [], callId });
        if (!t.enabled) return deny('operation_hidden');
        if (m.status !== 'published' && input.target === 'sandbox') return deny('module_not_published');
        if (!ctx && input.target === 'sandbox') return deny('no_approval');
        if (m.status === 'published' && ctx) {
          const approvals = approvalsOf(m).filter((a) => a.workflowId === ctx.workflowId);
          const active = approvals.filter((a) => a.status === 'approved');
          if (!active.length) return deny(approvals.some((a) => a.status === 'expired') ? 'approval_expired' : 'no_approval');
          if (!active.some((a) => a.operations.includes(o.name))) return deny('operation_not_approved');
        }
        const args: Record<string, unknown> = { ...input.input };
        const bound: { arg: string; value: string; source: SubjectBinding['bindTo'] }[] = [];
        if (o.binding) {
          const v = ctx?.bindings[o.binding.bindTo];
          if (!v) {
            if (o.binding.required) return deny('subject_unbound');
          } else {
            const given = args[o.binding.arg];
            if (given !== undefined && given !== '' && given !== v && o.binding.mode === 'equals') return deny('subject_mismatch');
            args[o.binding.arg] = v;
            bound.push({ arg: o.binding.arg, value: v, source: o.binding.bindTo });
          }
        }
        const missing = o.input.filter((x) => x.required && (args[x.name] === undefined || args[x.name] === '')).map((x) => x.name);
        const latencyMs = input.target === 'stub' ? 12 + Math.round(Math.random() * 30) : Math.round((t.p95Ms || 300) * (0.35 + Math.random() * 0.4));
        if (missing.length) return { decision: 'invalid' as const, status: 422, latencyMs, bound, wouldPause: false, invalid: missing.map((field) => ({ field, message: 'Required.' })), output: { error: 'invalid_input', missing }, masked: [], callId };
        if (o.amountMax && Number(args.amount ?? 0) > o.amountMax) return deny('constraint');
        const wouldPause = t.access !== 'read' && o.requiresApproval;
        if (wouldPause && input.target === 'sandbox' && !input.simulateApproval) return deny('approval_token_missing');
        const testApprovalToken = wouldPause && input.simulateApproval ? `test-apt_${Math.random().toString(36).slice(2, 8)}` : undefined;
        return { decision: 'allow' as const, status: 200, latencyMs, bound, wouldPause, testApprovalToken, output: o.stub, masked: o.maskedOutput, callId };
      }),

    activity: (mid) =>
      respond(() => {
        const m = find(mid);
        const r = rng(mods.indexOf(m) + 11);
        const s = row(m);
        const days = Array.from({ length: 14 }, (_, i) => {
          const d = new Date(Date.now() - (13 - i) * DAY);
          const weekend = d.getDay() === 0 || d.getDay() === 6 ? 0.55 : 1;
          const count = s.calls24h ? Math.round(s.calls24h * weekend * (0.75 + r() * 0.4)) : 0;
          const spike = s.errorRate >= FAILING_RATE && i >= 11 ? 2.4 : 1;
          return { date: d.toISOString().slice(0, 10), count, errors: Math.round(count * s.errorRate * (0.5 + r()) * spike), p95Ms: s.p95Ms ? Math.round(s.p95Ms * (0.85 + r() * 0.3) * (spike > 1 ? 1.4 : 1)) : 0 };
        });
        const names = new Set(m.ops.map((o) => o.name));
        const mine = allCalls().filter((c) => c.gateway === 'data' && names.has(c.target));
        const strip = ({ request: _q, response: _r, redacted: _d, policy: _p, identity: _i, requestId: _x, error: _e, ...rest }: ToolCallDetail): ToolCallRow => rest;
        return {
          days,
          denied24h: mine.filter((c) => c.status === 'denied' && Date.now() - new Date(c.at).getTime() < DAY).length,
          recent: mine.slice(0, 12).map(strip),
        };
      }),
  };

  const stripCall = ({ request: _q, response: _r, redacted: _d, policy: _p, identity: _i, requestId: _x, error: _e, ...rest }: ToolCallDetail): ToolCallRow => rest;
  return {
    api,
    using: (connId) => mods.filter((m) => m.connectionId === connId).map(row),
    recentCalls: (mid, n) => {
      const m = mods.find((x) => x.id === mid);
      if (!m) return [];
      const names = new Set(m.ops.map((o) => o.name));
      return allCalls().filter((c) => c.gateway === 'data' && names.has(c.target)).slice(0, n).map(stripCall);
    },
  };
}
