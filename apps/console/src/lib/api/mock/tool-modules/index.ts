import type { SecretUser } from '@/lib/types/secrets';
import type { Tool, ToolType } from '@/lib/types/domain';
import type { ToolCallDetail, ToolCallRow } from '@/lib/types/governance';
import type {
  CredentialKind,
  BlankModuleInput,
  DiscoveredOperation,
  Environment,
  HttpOperationInput,
  ModuleApproval,
  ModuleOperation,
  ModuleRef,
  ModuleType,
  ModuleVersion,
  ModuleView,
  OperationChange,
  OperationPatch,
  RunContextOption,
  SchemaField,
  SubjectBinding,
  ToolModule,
  ToolModuleDetail,
} from '@/lib/types/tool-modules';

import { amountRefused } from './amount';
import { ApiError } from '../../contract';
import type { ToolModulesApi } from '../../tool-modules-contract';
import * as F from '../fixtures';
import { rng } from '../governance/catalog';
import { seedToolCalls } from '../governance/seed-calls';
import { auditSink } from '../governance';
import { bulk, id, list, notFound, respond } from '../runtime';
import { guardTeam, inTeam, teamOwner } from '../teams';
import { MODULE_CONNECTION } from '../integrations/seed';
import type { ConnectionLink } from '../integrations';
import { daysAgo, DAY, DISCOVERY, f, inDays, MODULE_SEEDS, RUN_CONTEXTS, type ModuleSeed } from './seed';

/** Headers that carry a credential: a literal value in one is refused (tools-service `CREDENTIAL_HEADER`). */
const CREDENTIAL_HEADER = /^(authorization|x-api-key|cookie)$/i;
const SECRET_REF = /^\{\{[A-Z][A-Z0-9_]*\}\}$/;

/** A review as the mock keeps it; the console reads it only through each version's review fields. */
interface MockReview {
  id: string;
  major: number;
  version: string;
  decision: 'pending' | 'approved' | 'changes_requested';
  requestedBy: string;
  requestedAt: string;
  reviewer?: string;
  decidedAt?: string;
  findings: string[];
  note?: string;
}

/** A version with its review's fields, as tools-service answers (c-163). The mock has no Reviews, so nothing here decides one. */
const withReview = (m: { reviews: MockReview[] }, v: ModuleVersion): ModuleVersion => {
  const r = [...m.reviews].reverse().find((x) => x.version === v.version);
  if (!r) return v;
  return { ...v, reviewId: r.id, requestedAt: r.requestedAt, reviewer: r.reviewer, finding: r.decision === 'changes_requested' ? r.findings.join('; ') : undefined };
};

interface Op {
  id: string;
  toolId: string;
  name: string;
  /** Unset on seeded operations: an operation with a method runs `http`, one without is an MCP tool. */
  executor?: ModuleOperation['executor'];
  method?: ModuleOperation['method'];
  path?: string;
  headers?: { key: string; value: string }[];
  body?: string;
  responseTransform?: string;
  timeoutMs?: number;
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
  /** The mock's stand-in for Reviews: who asked and, once decided elsewhere, the outcome (c-163). */
  reviews: MockReview[];
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

/**
 * The mock's stand-in for tools-service's Jinja2 transform: it fills `{{ data.a.b }}` and `{{ data.list | length }}`
 * only, and reports any other template as unsupported rather than guessing. Text that parses as JSON is returned as JSON.
 */
function renderTransform(template: string, data: unknown): { output: unknown; error?: string } {
  let error: string | undefined;
  const text = template.replace(/\{\{\s*data((?:\.\w+)*)\s*(\|\s*length\s*)?\}\}/g, (_, path: string, length?: string) => {
    let node: unknown = data;
    for (const key of path.split('.').filter(Boolean)) {
      if (node && typeof node === 'object' && key in (node as Record<string, unknown>)) node = (node as Record<string, unknown>)[key];
      else {
        error ??= `'dict object' has no attribute '${key}'`;
        return '';
      }
    }
    const value = length ? (Array.isArray(node) ? node.length : String(node ?? '').length) : node;
    return typeof value === 'string' ? value : JSON.stringify(value);
  });
  if (!error && /\{\{|\{%/.test(text)) error = 'The mock fills {{ data.path }} only; run against tools-service for the full template.';
  if (error) return { output: data, error };
  try {
    return { output: JSON.parse(text) };
  } catch {
    return { output: text };
  }
}

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
  /** Each endpoint host and the ids of the modules calling it, for the egress allow-list. */
  hostsInUse: () => Record<string, string[]>;
  /** Each secret name and the operations whose headers or path read it (c-093). */
  secretUsers: () => Record<string, SecretUser[]>;
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
      const two = F.TWO_APPROVER_TOOLS.has(o.name);
      return { id: `${s.id}_op${i + 1}`, toolId: t.id, name: o.name, method: o.method, path: o.path, input: o.input, maskedOutput: o.masked ?? [], binding: o.binding, rateLimitPerMin: o.rate ?? 60, requiresApproval: two || (t.access === 'write' && o.requiresApproval !== false), amountMax: o.amountMax, stub: o.stub, headers: o.headers };
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
    const reviews: MockReview[] = majors.map((mj) => {
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
  /** A draft with a name and a type and nothing else; operations, connection and settings are added on its page. */
  const blankMod = (input: BlankModuleInput, owner: string, at: string): Mod => ({
    id: id('mod'),
    name: kebab(input.name),
    displayName: input.displayName.trim(),
    system: input.displayName.trim(),
    description: input.description?.trim() ?? '',
    type: input.type,
    status: 'draft',
    ownerTeam: owner,
    ownerContacts: [me],
    endpoint: '',
    auth: { kind: 'none' },
    timeoutMs: 8000,
    egressHosts: [],
    dataClassification: 'confidential',
    reachable: true,
    drift: false,
    updatedAt: at,
    version: '0.1.0',
    ops: [],
    approvals: [],
    reviews: [],
    versions: [{ version: '0.1.0', major: 0, status: 'draft', publishedBy: me, note: 'First version', changes: [], pinnedBy: [], reachability: [] }],
    pending: [],
    baseline: null,
  });
  // Seed: one draft that has a name and nothing else yet.
  mods.push({ ...blankMod({ displayName: 'Document service', name: 'document-service', type: 'http', description: 'Fetches signed loan documents for the lending inbox.' }, 'Lending Ops', daysAgo(1)), id: 'mod_document_service' });
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
      accessClasses: (['read', 'write'] as const).filter((acc) => ops.some(({ t }) => t.access === acc)),
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
      pendingReview: (() => {
        const r = m.reviews.find((x) => x.decision === 'pending');
        return r ? { id: r.id, version: r.version, requestedBy: r.requestedBy, requestedAt: r.requestedAt } : null;
      })(),
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
            : v === 'security_review'
              ? !!r.pendingReview
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
          executor: o.executor ?? (o.method ? 'http' : 'mcp'),
          method: o.method,
          path: o.path,
          headers: o.headers ?? [],
          body: o.body,
          responseTransform: o.responseTransform,
          timeoutMs: o.timeoutMs,
          stub: o.stub,
          input: o.input,
          maskedOutput: o.maskedOutput,
          binding: o.binding,
          rateLimitPerMin: o.rateLimitPerMin,
          requiresApproval: o.requiresApproval,
          approvers: F.TWO_APPROVER_TOOLS.has(o.name) ? (2 as const) : (1 as const),
          approverTeam: m.ownerTeam,
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
      versions: [...m.versions].reverse().map((v) => withReview(m, v)),
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

  /** One hand-built HTTP operation as a discovered one; refuses literal credentials in headers. */
  function httpOperation(h: HttpOperationInput): { op: DiscoveredOperation; origin: string } {
    const keyLike = h.headers.find((x) => /^(authorization|x-api-key|cookie)$/i.test(x.key.trim()) && x.value.trim() && !/^\{\{[A-Z][A-Z0-9_]*\}\}$/.test(x.value.trim()));
    if (keyLike) throw new ApiError(`The ${keyLike.key} header holds a literal value. Reference the vault instead, e.g. {{CORE_API_KEY}}.`, 400);
    if (!/^[a-z][a-z0-9_]{2,}$/.test(h.name)) throw new ApiError('Name the operation in lower case letters, digits and underscores.', 400);
    let url: URL;
    try {
      url = new URL(h.url.replace(/\{([a-zA-Z0-9_]+)\}/g, 'x'));
    } catch {
      throw new ApiError('Enter the full https URL of the operation.', 400);
    }
    const path = h.url.slice(url.origin.length) || '/';
    const vars = [...new Set([...h.url.matchAll(/\{([a-zA-Z0-9_]+)\}/g), ...(h.body ?? '').matchAll(/\{\{\s*([a-z][a-zA-Z0-9_]*)\s*\}\}/g)].map((x) => x[1]))];
    return { origin: url.origin, op: { name: h.name, description: h.description, access: h.access, method: h.method, path, group: 'operations', input: vars.map((v) => f(v, 'string', true)) } };
  }

  const audit = (m: Mod, action: 'created' | 'edited', summary: string, diff?: { field: string; before?: string; after?: string }[]) =>
    auditSink.log({ action, target: { type: 'tool', name: m.displayName, href: `/tools/${m.id}` }, summary, diff, owner: m.ownerTeam });

  /** Appends operations as grantable tools. A draft takes them straight into its first version; a published module stages them. */
  function appendOps(m: Mod, opsIn: DiscoveredOperation[]) {
    for (const o of opsIn) {
      if (m.ops.some((x) => x.name === o.name)) throw new ApiError(`${o.name} is already in this module.`, 409);
      if (tools.some((t) => t.name === o.name)) throw new ApiError(`An operation named ${o.name} already exists in another module.`, 409);
    }
    const start = m.ops.length;
    const added: Op[] = opsIn.map((o, i) => {
      const t: Tool = { id: id('tl'), name: o.name, description: o.description, type: toolTypeOf(m.type), system: m.system, access: o.access, requiresReview: o.access !== 'read', enabled: true, calls24h: 0, errorRate: 0, p95Ms: 0, grantedAgentIds: [], sampleInput: sampleInput(o.input), moduleId: m.id, module: m.displayName };
      tools.unshift(t);
      return { id: `${m.id}_op${start + i + 1}`, toolId: t.id, name: o.name, method: o.method, path: o.path, input: o.input, maskedOutput: [], binding: null, rateLimitPerMin: 60, requiresApproval: o.access !== 'read', amountMax: undefined, stub: { ok: true } };
    });
    m.ops.push(...added);
    const changes = opsIn.map((o) => ({ operation: o.name, kind: 'added' as const, detail: `New ${o.access} operation`, major: o.access !== 'read' }));
    if (m.status === 'draft') m.versions[m.versions.length - 1].changes.push(...changes);
    else stage(m, changes);
    touch(m);
  }

  function bumped(m: Mod, major: boolean) {
    const [a, b] = m.version.split('.').map(Number);
    return major ? `${a + 1}.0.0` : `${a}.${b + 1}.0`;
  }

  function discovered(source: Parameters<ToolModulesApi['discover']>[0]) {
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
      const d = host.includes('servicenow') ? DISCOVERY.cat_servicenow : DISCOVERY.mcp;
      const label = host.split('.')[0];
      const system = host.includes('servicenow') ? 'ServiceNow' : label.charAt(0).toUpperCase() + label.slice(1);
      return { type: 'mcp' as const, system, suggestedName: kebab(system), version: d.version, endpoint: source.url, operations: d.operations, warnings: d.warnings ?? [], noAuth: false };
    }
    const ref = source.specUrl || source.fileName;
    if (!ref) throw new ApiError('Add the spec as a URL or a file.', 400);
    const base = (source.fileName ?? new URL(source.specUrl!).hostname).split(/[./]/)[0];
    const system = base.charAt(0).toUpperCase() + base.slice(1);
    const d = DISCOVERY.openapi;
    // As tools-service presets it: GET reads, every other method writes.
    const operations = d.operations.map((o) => (o.method ? { ...o, access: o.method === 'GET' ? ('read' as const) : ('write' as const) } : o));
    return { type: 'openapi' as const, system, suggestedName: kebab(system), version: d.version, endpoint: source.specUrl ? source.specUrl.replace(/\/[^/]*$/, '') : `https://${kebab(system)}.northfield.internal/api`, operations, warnings: d.warnings ?? [], noAuth: false };
  }

  /** The service's call-shape rules (tools-service `_checked_shape`): validated before anything is staged. */
  function checkedShape(m: Mod, o: Op, patch: OperationPatch): Partial<Op> {
    const keys = (['method', 'path', 'headers', 'body', 'responseTransform', 'timeoutMs'] as const).filter((k) => k in patch);
    if (!keys.length) return {};
    if ((o.executor ?? (o.method ? 'http' : 'mcp')) !== 'http') throw new ApiError(`${o.name} is not an HTTP operation; its call comes from its server or seed.`, 400);
    const out: Partial<Op> = {};
    if (patch.method !== undefined) out.method = patch.method;
    if (patch.path !== undefined) {
      const path = patch.path.trim();
      if (!path.startsWith('/')) throw new ApiError('Enter the path after the module endpoint, starting with /.', 400);
      if (!m.endpoint) throw new ApiError('Set the module’s endpoint before editing a path.', 400);
      out.path = path;
    }
    if (patch.headers !== undefined) {
      for (const h of patch.headers) {
        if (CREDENTIAL_HEADER.test(h.key.trim()) && h.value.trim() && !SECRET_REF.test(h.value.trim())) throw new ApiError(`The ${h.key} header holds a literal value. Reference the vault instead, e.g. {{CORE_API_KEY}}.`, 400);
      }
      out.headers = patch.headers.filter((h) => h.key.trim()).map((h) => ({ key: h.key.trim(), value: h.value.trim() }));
    }
    if (patch.body !== undefined) {
      const body = patch.body?.trim() || undefined;
      if (body) {
        try {
          JSON.parse(body.replace(/\{\{\s*[a-z][a-zA-Z0-9_]*\s*\}\}/g, 'null'));
        } catch (e) {
          throw new ApiError(`The body is not a JSON template: ${(e as Error).message}.`, 400);
        }
      }
      out.body = body;
    }
    if (patch.responseTransform !== undefined) {
      const t = patch.responseTransform?.trim() || undefined;
      // The service parses with Jinja2; the mock checks the delimiters balance, which catches the common slip.
      if (t && ((t.match(/\{\{/g) ?? []).length !== (t.match(/\}\}/g) ?? []).length || (t.match(/\{%/g) ?? []).length !== (t.match(/%\}/g) ?? []).length)) throw new ApiError('The response transform does not parse: an unclosed {{ or {%.', 400);
      out.responseTransform = t;
    }
    if (patch.timeoutMs !== undefined) {
      if (patch.timeoutMs !== null && !(patch.timeoutMs >= 1_000 && patch.timeoutMs <= 120_000)) throw new ApiError('Set a timeout between 1 and 120 seconds (1000 to 120000 ms).', 400);
      out.timeoutMs = patch.timeoutMs ?? undefined;
    }
    return Object.fromEntries(Object.entries(out).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(o[k as keyof Op]))) as Partial<Op>;
  }

  /** Applies a validated call-shape edit and says what changed: method, path or body major; the rest minor. */
  function shapeChanges(o: Op, shape: Partial<Op>): OperationChange[] {
    const out: OperationChange[] = [];
    if ('method' in shape || 'path' in shape || 'body' in shape) {
      const before = `${o.method} ${o.path}`;
      const after = `${shape.method ?? o.method} ${shape.path ?? o.path}`;
      out.push({ operation: o.name, kind: 'schema_changed', detail: (before !== after ? `Call ${before} → ${after}` : 'Call unchanged') + ('body' in shape ? '; body edited' : ''), major: true });
    }
    const minor = [
      'headers' in shape && 'Headers edited',
      'responseTransform' in shape && `Response transform ${shape.responseTransform ? 'set' : 'removed'}`,
      'timeoutMs' in shape && (shape.timeoutMs ? `Timeout ${shape.timeoutMs / 1000} s` : 'Timeout back to the module’s'),
    ].filter(Boolean);
    if (minor.length) out.push({ operation: o.name, kind: 'settings', detail: minor.join('; '), major: false });
    Object.assign(o, shape);
    const named = [...(o.path ?? '').matchAll(/\{([a-zA-Z0-9_]+)\}/g), ...(o.body ?? '').matchAll(/\{\{\s*([a-z][a-zA-Z0-9_]*)\s*\}\}/g)].map((x) => x[1]!);
    for (const n of new Set(named)) if (!o.input.some((f) => f.name === n)) o.input.push({ name: n, type: 'string', required: true, description: '' });
    return out;
  }

  const api: ToolModulesApi = {
    // Grants across modules are tools-service's; the mock lists none.
    grants: async ({ page, pageSize }) => ({ data: [], pagination: { page, pageSize, total: 0, totalPages: 1, hasNext: false, hasPrev: false }, facets: {} }),
    list: (p) =>
      respond((md) => {
        const scoped = mods.filter((m) => inTeam(ownersOf(m))).map(row);
        const src = md === 'empty' ? [] : scoped;
        const viewCounts = { all: src.length, needs_approval: 0, expiring: 0, expired: 0, failing: 0, security_review: 0 };
        for (const v of ['needs_approval', 'expiring', 'expired', 'failing', 'security_review'] as const) viewCounts[v] = src.filter((r) => inView(r, v)).length;
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
        let name = kebab(input.name);
        if (!name) throw new ApiError('Name the module.', 400);
        if (input.uniqueName) for (let n = 2; mods.some((m) => m.name === name); n++) name = `${kebab(input.name)}-${n}`;
        if (mods.some((m) => m.name === name)) throw new ApiError(`A module named ${name} already exists.`, 409);
        if (!input.displayName.trim()) throw new ApiError('Give the module a display name.', 400);
        let opsIn: DiscoveredOperation[] = input.operations ?? [];
        let endpoint = input.endpoint;
        if (input.type === 'code') throw new ApiError('Code modules need the sandbox, which is not available yet.', 422);
        if (input.http) {
          const built = httpOperation(input.http);
          endpoint = built.origin;
          opsIn = [built.op];
        }
        if (!opsIn.length) throw new ApiError('Choose at least one operation to expose.', 400);
        for (const o of opsIn) if (tools.some((t) => t.name === o.name)) throw new ApiError(`An operation named ${o.name} already exists in another module.`, 409);
        const mid = id('mod');
        const version = '1.0.0';
        const owner = teamOwner() ?? 'Platform';
        const ops: Op[] = opsIn.map((o, i) => {
          const t: Tool = { id: id('tl'), name: o.name, description: o.description, type: toolTypeOf(input.type), system: input.system, access: o.access, requiresReview: o.access !== 'read', enabled: true, calls24h: 0, errorRate: 0, p95Ms: 0, grantedAgentIds: [], sampleInput: sampleInput(o.input), moduleId: mid, module: input.displayName };
          tools.unshift(t);
          return { id: `${mid}_op${i + 1}`, toolId: t.id, name: o.name, method: o.method, path: o.path, input: o.input, maskedOutput: [], binding: null, rateLimitPerMin: 60, requiresApproval: o.access !== 'read', amountMax: undefined, stub: { ok: true } };
        });
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
          // No credential until the builder adds its header as a secret reference.
          auth: { kind: 'none' },
          timeoutMs: 8000,
          egressHosts: (() => {
            try {
              return [new URL(endpoint).hostname];
            } catch {
              return [];
            }
          })(),
          dataClassification: 'confidential',
          reachable: true,
          drift: false,
          updatedAt: new Date().toISOString(),
          version,
          ops,
          approvals: [],
          reviews: [],
          versions: [{ version, major: majorOf(version), status: 'draft', publishedBy: me, note: 'First version', changes: opsIn.map((o) => ({ operation: o.name, kind: 'added' as const, detail: `New ${o.access} operation`, major: true })), pinnedBy: [], reachability: [{ environment: 'test', ok: true, checkedAt: new Date().toISOString() }] }],
          pending: [],
          baseline: null,
        };
        mods.unshift(m);
        return detail(m);
      }),

    createBlankModule: (input) =>
      respond(() => {
        const name = kebab(input.name);
        if (!input.displayName.trim()) throw new ApiError('Give the module a display name.', 400);
        if (!name) throw new ApiError('Give the module a name, e.g. servicenow.', 400);
        if (mods.some((x) => x.name === name)) throw new ApiError(`A module named ${name} already exists.`, 409);
        const m = blankMod(input, teamOwner() ?? 'Platform', new Date().toISOString());
        mods.unshift(m);
        audit(m, 'created', `Created ${m.displayName} as a draft ${m.type} module`);
        return detail(m);
      }),

    updateModuleDetails: (mid, patch) =>
      respond(() => {
        const m = find(mid);
        if (patch.displayName !== undefined && !patch.displayName.trim()) throw new ApiError('Give the module a display name.', 400);
        const diff = [
          ...(patch.displayName !== undefined && patch.displayName.trim() !== m.displayName ? [{ field: 'Display name', before: m.displayName, after: patch.displayName.trim() }] : []),
          ...(patch.description !== undefined && patch.description.trim() !== m.description ? [{ field: 'Description', before: m.description, after: patch.description.trim() }] : []),
        ];
        if (patch.displayName !== undefined) m.displayName = patch.displayName.trim();
        if (patch.description !== undefined) m.description = patch.description.trim();
        for (const o of m.ops) toolOf(o).module = m.displayName;
        touch(m);
        if (diff.length) audit(m, 'edited', `Edited ${diff.map((d) => d.field.toLowerCase()).join(' and ')}`, diff);
        return detail(m);
      }),

    addOperation: (mid, input) =>
      respond(() => {
        const m = find(mid);
        const { op, origin } = httpOperation(input);
        if (!m.endpoint) m.endpoint = origin;
        try {
          const host = new URL(origin).hostname;
          if (!m.egressHosts.includes(host)) m.egressHosts.push(host);
        } catch {
          // httpOperation already rejected anything that is not a URL.
        }
        appendOps(m, [op]);
        audit(m, 'edited', `Added operation ${op.name}`, [{ field: 'Operations', after: op.name }]);
        return detail(m);
      }),

    importOperations: (mid, input) =>
      respond(() => {
        const m = find(mid);
        if (!input.operations.length) throw new ApiError('Choose at least one operation to import.', 400);
        const fresh = input.operations.filter((o) => !m.ops.some((x) => x.name === o.name));
        if (!fresh.length) throw new ApiError('Every chosen operation is already in this module.', 409);
        const listed = discovered(input.source).operations.map((o) => o.name);
        appendOps(m, fresh);
        if (!m.endpoint) m.endpoint = input.source.kind === 'mcp' ? input.source.url : (input.source.specUrl ?? '');
        // The server no longer lists an operation this module already holds: that is drift from what was reviewed.
        const gone = m.ops.filter((o) => input.source.kind === 'mcp' && !listed.includes(o.name) && !fresh.some((x) => x.name === o.name));
        if (gone.length && m.type === 'mcp') m.drift = true;
        audit(m, 'edited', `Imported ${fresh.length === 1 ? '1 operation' : `${fresh.length} operations`}`, [{ field: 'Operations', after: fresh.map((o) => o.name).join(', ') }]);
        return detail(m);
      }),

    setConnection: (mid, connId) =>
      respond(() => {
        const m = find(mid);
        const before = deps.connection(m.connectionId)?.name;
        if (connId === null) {
          if (m.status !== 'draft') throw new ApiError('A module in review or published keeps its connection. Change it to another one instead.', 409);
          Object.assign(m, { connectionId: undefined, catalogId: undefined, auth: { kind: 'none' } });
        } else {
          const conn = deps.connection(connId);
          if (!conn) throw new ApiError('That connection no longer exists. Pick another one.', 400);
          if (conn.status === 'revoked') throw new ApiError(`${conn.name} is revoked. Reconnect it in Connections or pick another one.`, 409);
          const kind: CredentialKind = conn.authMethod === 'api_key' ? 'api_key' : conn.authMethod === 'mtls' ? 'mtls' : 'oauth_client_credentials';
          Object.assign(m, { connectionId: conn.id, catalogId: conn.catalogId, auth: { kind } });
        }
        touch(m);
        audit(m, 'edited', connId ? `Connected through ${deps.connection(connId)?.name}` : 'Detached its connection', [{ field: 'Connection', before, after: connId ? deps.connection(connId)?.name : undefined }]);
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
        if (patch.requiresApproval === false && F.TWO_APPROVER_TOOLS.has(o.name)) throw new ApiError('Operations that need two approvers always need a person’s approval.', 422);
        if (patch.rateLimitPerMin !== undefined && (!Number.isInteger(patch.rateLimitPerMin) || patch.rateLimitPerMin < 1 || patch.rateLimitPerMin > 10_000)) throw new ApiError('Set a rate limit between 1 and 10,000 calls a minute.', 400);
        if (patch.amountMax !== undefined && (t.access !== 'write' || patch.amountMax <= 0)) throw new ApiError('Only write operations take an amount limit, and it must be above zero.', 400);
        if (patch.amountMax !== undefined && !o.input.some((x) => x.name === 'amount')) throw new ApiError(`${o.name} has no amount input, so an amount limit would have nothing to check.`, 422);
        if (patch.binding && !o.input.some((x) => x.name === patch.binding!.arg)) throw new ApiError(`${patch.binding.arg} is not an input of ${o.name}.`, 400);
        const shape = checkedShape(m, o, patch);
        if (!m.baseline) m.baseline = { ops: structuredClone(m.ops), tools: Object.fromEntries(m.ops.map((x) => [x.toolId, { enabled: toolOf(x).enabled, description: toolOf(x).description }])) };
        const changes: OperationChange[] = shapeChanges(o, shape);
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
        if ('stub' in patch) {
          const stub = (patch.stub ?? { ok: true }) as Record<string, unknown>;
          if (JSON.stringify(stub) !== JSON.stringify(o.stub)) {
            changes.push({ operation: o.name, kind: 'settings', detail: 'Mock response edited', major: false });
            o.stub = stub;
          }
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
        if (!m.ops.length) throw new ApiError('Add at least one operation before requesting a security review.', 422);
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
        if (amountRefused(o, args)) return deny('constraint');
        const wouldPause = t.access !== 'read' && o.requiresApproval;
        if (wouldPause && input.target === 'sandbox' && !input.simulateApproval) return deny('approval_token_missing');
        const testApprovalToken = wouldPause && input.simulateApproval ? `test-apt_${Math.random().toString(36).slice(2, 8)}` : undefined;
        // Mirrors tools-service: on the test environment a read reaches the system (the mock answers with the stub), a write answers from the stub and says so.
        const sandbox = input.target === 'sandbox';
        const reached = sandbox && t.access === 'read' ? { stubbed: false, reachedHost: new URL(m.endpoint).hostname } : sandbox ? { stubbed: true } : {};
        // The draft mock and transform run for this test only, as tools-service runs them (c-088).
        const draft = input.draft ?? {};
        const raw = 'stub' in draft && draft.stub !== undefined ? draft.stub : o.stub;
        const template = 'responseTransform' in draft ? draft.responseTransform : o.responseTransform;
        const log: { atMs: number; message: string }[] = [{ atMs: 0, message: "Input checked against the operation's schema" }];
        const live = sandbox && t.access === 'read';
        const typed = input.secretValues ?? {};
        const names = [...new Set([...(o.path ?? '').matchAll(/\{\{([A-Z][A-Z0-9_]*)\}\}/g), ...(o.headers ?? []).flatMap((h) => [...h.value.matchAll(/\{\{([A-Z][A-Z0-9_]*)\}\}/g)])].map((x) => x[1]))];
        if (live) {
          log.push({ atMs: 1, message: `Egress allowed: ${new URL(m.endpoint).hostname}` });
          for (const n of names) log.push({ atMs: 2, message: `Secret ${n} from ${typed[n] ? 'the value typed for this run' : "the tenant's secrets"}` });
          log.push({ atMs: latencyMs - 1, message: `${new URL(m.endpoint).hostname} answered 200` });
        } else log.push({ atMs: 1, message: 'Answered from the mock response' });
        const masking = (text: string) => text.replace(/\{\{[A-Z][A-Z0-9_]*\}\}/g, '[secret]').replace(/\{(\w+)\}/g, (_, k: string) => encodeURIComponent(String(args[k] ?? '')));
        const request = live ? { method: o.method ?? 'GET', url: `${m.endpoint.replace(/\/+$/, '')}${masking(o.path ?? '')}`, headers: (o.headers ?? []).map((h) => ({ key: h.key, value: masking(h.value) })) } : undefined;
        const shaped = template ? renderTransform(template, raw) : { output: raw };
        if (template) log.push({ atMs: latencyMs, message: shaped.error ? 'Transform failed; the raw response is returned' : 'Draft transform applied' });
        return { decision: 'allow' as const, status: 200, latencyMs, bound, wouldPause, testApprovalToken, output: shaped.output, rawResponse: raw, transformError: shaped.error, request, log, masked: o.maskedOutput, callId, ...reached };
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
    secretUsers: () => {
      const out: Record<string, SecretUser[]> = {};
      const ref = /\{\{([A-Z][A-Z0-9_]*)\}\}/g;
      for (const m of mods) {
        const published = new Set((m.baseline?.ops ?? m.ops).flatMap((o) => [...[o.path ?? '', ...(o.headers ?? []).map((h) => h.value)].join(' ').matchAll(ref)].map((x) => `${o.name}:${x[1]}`)));
        for (const o of m.ops) {
          const names = new Set([...[o.path ?? '', ...(o.headers ?? []).map((h) => h.value)].join(' ').matchAll(ref)].map((x) => x[1]));
          for (const n of names) (out[n] ??= []).push({ moduleId: m.id, moduleName: m.displayName, operation: o.name, staged: !published.has(`${o.name}:${n}`) });
        }
      }
      return out;
    },
    hostsInUse: () => {
      const out: Record<string, string[]> = {};
      for (const m of mods) {
        try {
          (out[new URL(m.endpoint).hostname] ??= []).push(m.id);
        } catch {
          // A draft with no endpoint yet calls no host.
        }
      }
      return out;
    },
    recentCalls: (mid, n) => {
      const m = mods.find((x) => x.id === mid);
      if (!m) return [];
      const names = new Set(m.ops.map((o) => o.name));
      return allCalls().filter((c) => c.gateway === 'data' && names.has(c.target)).slice(0, n).map(stripCall);
    },
  };
}
