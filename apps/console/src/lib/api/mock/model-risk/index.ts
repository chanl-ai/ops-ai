import type { Agent, BulkResult, Review, ReviewDecisionInput, Risk, ValidationRun, Workflow, WorkflowGraph } from '@/lib/types/domain';
import type { AgentEvalPin, EvalGate } from '@/lib/types/evals';
import type { ModelCondition, ModelEntry, ModelEntryDetail, ModelFinding, ModelRiskView, ModelValidationRequest, ValidationRecord, ValidationScope, ValidationStatus } from '@/lib/types/model-risk';

import { plural } from '@/lib/format';

import { ApiError, type OpsApi } from '../../contract';
import type { ModelRiskApi } from '../../model-risk-contract';
import type { EvalsMock } from '../evals';
import { auditSink } from '../governance';
import { MODEL_ALIAS } from '../governance/catalog';
import { PRINCIPALS } from '../run-as/principals';
import { bulk, field, id, list, notFound, respond } from '../runtime';
import { inTeam, teamDirectory } from '../teams';
import { ENTRY_SEEDS, VALIDATION_SEEDS, VALIDATORS } from './seed';

export interface ModelRiskDeps {
  agents: () => Agent[];
  workflows: () => Workflow[];
  graph: (workflowId: string) => WorkflowGraph | undefined;
  lastValidation: (workflowId: string) => ValidationRun | undefined;
  /** The live review list; model validation reviews are added to it so the queue, counts and views include them. */
  reviews: () => Review[];
  /** The bank system a tool reaches. */
  toolSystem: (toolId: string) => string | undefined;
  owners: string[];
  me: string;
  evals: EvalsMock;
}

const DAY = 86_400_000;
const ymd = (offsetDays: number) => new Date(Date.now() + offsetDays * DAY).toISOString().slice(0, 10);
const isOpen = (r: Review) => r.status === 'pending' || r.status === 'in_review';
const HIGH: Risk[] = ['high', 'critical'];
/** Injection pass rate each tier requires (spec 04, 5.4). */
const INJECTION_THRESHOLD: Record<Risk, number> = { low: 0.95, medium: 0.98, high: 1, critical: 1 };
const TIER_LABEL: Record<Risk, string> = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' };

function hash(key: string) {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) h = Math.imul(h ^ key.charCodeAt(i), 16777619);
  return ((h >>> 0) % 10_000) / 10_000;
}

interface StoredEntry {
  id: string;
  refId: string;
  type: 'agent' | 'workflow';
  tier: Risk;
  tierReason: string;
  status: Exclude<ValidationStatus, 'in_validation' | 'expired'>;
  nextReviewAt: string | null;
  purpose?: string;
  dataTouched: string[];
  validations: ValidationRecord[];
  conditions: ModelCondition[];
  findings: ModelFinding[];
}

/**
 * Model risk inventory over the mock's agents and workflows. Entries are created on first read for records
 * without a seed (new agents and workflows start medium and not validated). Second-line decisions run through
 * `model_validation` reviews in the shared review list; `wrapReviews` decides them and adds the eval gate and
 * inventory status to publish requests.
 */
export function createModelRiskMock(deps: ModelRiskDeps) {
  const entries: Record<string, StoredEntry> = {};
  const seedEntry = (refId: string, type: 'agent' | 'workflow'): StoredEntry => {
    const s = ENTRY_SEEDS[refId];
    const mid = `mr_${refId}`;
    return (entries[mid] ??= {
      id: mid,
      refId,
      type,
      tier: s?.tier ?? 'medium',
      tierReason: s?.tierReason ?? 'Not assessed yet; medium until Model Risk sets a tier.',
      status: s?.status ?? 'not_validated',
      nextReviewAt: s?.nextReviewInDays !== undefined ? ymd(s.nextReviewInDays) : null,
      purpose: s?.purpose,
      dataTouched: s?.dataTouched ?? [],
      validations: (s?.validations ?? []).map((v, i) => ({ id: `val_${refId}_${i}`, validator: v.validator, date: new Date(Date.now() - v.daysAgo * DAY).toISOString(), outcome: v.outcome, conditions: v.conditions ?? [], reason: v.reason })),
      conditions: (s?.conditions ?? []).map((c, i) => ({ id: `cnd_${refId}_${i}`, text: c.text, owner: c.owner, dueDate: ymd(c.dueInDays), status: c.status ?? 'open', createdBy: 'Priya Shah', createdAt: new Date(Date.now() - 120 * DAY).toISOString() })),
      findings: (s?.findings ?? []).map((f, i) => ({ id: `fnd_${refId}_${i}`, title: f.title, severity: f.severity, status: f.status, raisedBy: f.raisedBy, raisedAt: new Date(Date.now() - f.daysAgo * DAY).toISOString(), dueDate: f.dueInDays !== undefined ? ymd(f.dueInDays) : undefined })),
    });
  };
  const all = () => [...deps.workflows().map((w) => seedEntry(w.id, 'workflow')), ...deps.agents().map((a) => seedEntry(a.id, 'agent'))];
  const entryOr404 = (mid: string) => {
    all();
    return entries[mid] ?? notFound('Model');
  };

  const agentOf = (e: StoredEntry) => deps.agents().find((a) => a.id === e.refId);
  const workflowOf = (e: StoredEntry) => deps.workflows().find((w) => w.id === e.refId);
  const nameOf = (e: StoredEntry) => (e.type === 'agent' ? agentOf(e)?.name : workflowOf(e)?.name) ?? e.refId;
  const ownerOf = (e: StoredEntry) => (e.type === 'agent' ? agentOf(e)?.owner : workflowOf(e)?.owner) ?? '';
  /** Agents a workflow pins: every agent step in its graph, plus the agents it lists. */
  const pinnedAgents = (wid: string) => {
    const slugs = new Set([...(deps.graph(wid)?.nodes.map((n) => n.data.agentSlug as string | undefined).filter(Boolean) ?? []), ...(deps.workflows().find((w) => w.id === wid)?.agentSlugs ?? [])]);
    return deps.agents().filter((a) => slugs.has(a.slug));
  };
  const modelOf = (e: StoredEntry) => {
    const a = e.type === 'agent' ? agentOf(e) : pinnedAgents(e.refId)[0];
    return a?.model ?? 'claude-sonnet-5';
  };
  const openReviewFor = (mid: string) => deps.reviews().find((r) => r.kind === 'model_validation' && isOpen(r) && r.modelValidation?.entryId === mid);
  const statusOf = (e: StoredEntry): ValidationStatus => {
    const open = openReviewFor(e.id);
    if (open && open.modelValidation?.scope !== 'tier_change') return 'in_validation';
    if ((e.status === 'validated' || e.status === 'validated_with_conditions') && e.nextReviewAt && e.nextReviewAt < ymd(0)) return 'expired';
    return e.status;
  };
  const lastPassRate = (e: StoredEntry) => {
    const agents = e.type === 'agent' ? [agentOf(e)].filter((a): a is Agent => !!a) : pinnedAgents(e.refId);
    const sums = agents.map((a) => deps.evals.summaryFor(a.id, a.version)).filter((s) => !!s);
    if (!sums.length) return null;
    return sums.reduce((n, s) => n + s.passed, 0) / Math.max(1, sums.reduce((n, s) => n + s.total, 0));
  };

  const row = (e: StoredEntry): ModelEntry => {
    const model = modelOf(e);
    return {
      id: e.id,
      name: nameOf(e),
      type: e.type,
      refId: e.refId,
      href: e.type === 'agent' ? `/agents/${e.refId}` : `/workflows/${e.refId}`,
      owner: ownerOf(e),
      ownerTeam: teamDirectory.ofOwner(ownerOf(e)).name,
      model,
      alias: MODEL_ALIAS[model]?.alias ?? 'ops-reasoning',
      provider: 'Anthropic',
      tier: e.tier,
      tierReason: e.tierReason,
      validationStatus: statusOf(e),
      nextReviewAt: e.nextReviewAt,
      openFindings: e.findings.filter((f) => f.status !== 'closed').length,
      lastEvalPassRate: lastPassRate(e),
      openReview: (() => {
        const r = openReviewFor(e.id);
        return r?.modelValidation ? { id: r.id, scope: r.modelValidation.scope } : null;
      })(),
    };
  };

  const conditionStatus = (c: ModelCondition): ModelCondition => (c.status === 'open' && c.dueDate < ymd(0) ? { ...c, status: 'overdue' } : c);

  const detail = (e: StoredEntry): ModelEntryDetail => {
    const r = row(e);
    const a = agentOf(e);
    const w = workflowOf(e);
    const pins = e.type === 'agent' ? (a ? [a] : []) : pinnedAgents(e.refId);
    const version = (e.type === 'agent' ? a?.version : w?.version) ?? 1;
    const val = e.type === 'workflow' ? deps.lastValidation(e.refId) : undefined;
    const tools = pins.flatMap((p) => p.toolIds);
    const open = openReviewFor(e.id);
    const base = e.type === 'agent' ? 0.05 : HIGH.includes(e.tier) ? 0.09 : 0.04;
    return {
      ...r,
      purpose: e.purpose ?? (e.type === 'agent' ? (a?.role ?? '') : (w?.description ?? '')),
      dataTouched: e.dataTouched,
      systems: [...new Set(tools.map(deps.toolSystem).filter((x): x is string => !!x))],
      knowledgeBases: [...new Set(pins.flatMap((p) => p.collections))],
      evidence: {
        evals: pins.flatMap((p) => {
          const s = deps.evals.summaryFor(p.id, p.version);
          return s ? [{ name: p.name, version: p.version, summary: s }] : [];
        }),
        workflowSuite: val ? { ...val.summary, ranAt: val.ranAt } : null,
        bundles: [version, version - 1, version - 2].filter((v) => v >= 1).map((v) => ({ version: v, bundleId: `evb_${Math.floor(hash(`${e.refId}:${v}`) * 0xffffff).toString(16).padStart(6, '0')}${v}`, sealedAt: new Date(Date.now() - (version - v + 1) * 9 * DAY).toISOString() })),
      },
      validations: [...e.validations].sort((x, y) => y.date.localeCompare(x.date)),
      conditions: e.conditions.map(conditionStatus),
      findings: e.findings,
      monitoring: {
        passRateByVersion:
          e.type === 'agent' && a
            ? deps.evals.passRates(a.id).map((p) => ({ version: `v${p.version}`, passRate: p.passRate }))
            : [version - 3, version - 2, version - 1, version].filter((v) => v >= 1).map((v) => ({ version: `v${v}`, passRate: v === version && val ? val.summary.passed / Math.max(1, val.summary.total) : 0.78 + hash(`${e.refId}:pr:${v}`) * 0.2 })),
        overrideRate30d: Array.from({ length: 30 }, (_, i) => ({ date: ymd(i - 29), rate: Math.max(0, base + (hash(`${e.refId}:ov:${i}`) - 0.5) * base * 0.9 + (i > 22 && e.refId === 'wf_wire' ? 0.05 : 0)) })),
      },
      pendingReview: open?.modelValidation ? { id: open.id, scope: open.modelValidation.scope, toTier: open.modelValidation.toTier } : undefined,
    };
  };

  const audit = (e: StoredEntry, action: 'edited' | 'approved' | 'rejected' | 'created', summary: string, extra: { diff?: { field: string; before?: string; after?: string }[]; reason?: string } = {}) =>
    auditSink.log({ action, target: { type: 'model', name: nameOf(e), href: `/model-risk/${e.id}` }, summary, owner: ownerOf(e), ...extra });

  // ── Second-line reviews ──
  let seq = 2000;
  const POLICY = { id: 'gp_model_risk', name: 'Second-line validation', condition: 'validation requested, or tier changes to or from high or critical', reviewers: 'Model Risk', sla: '5 business days', onTimeout: 'Stays pending; the owner is notified', fourEyes: false };
  const openValidation = (e: StoredEntry, scope: ValidationScope, by: string, note: string, toTier?: Risk, createdAt = new Date().toISOString()): Review => {
    const r = row(e);
    const a = agentOf(e);
    const wid = e.type === 'workflow' ? e.refId : (a?.usedIn[0]?.workflowId ?? '');
    const evals = detail(e).evidence.evals;
    const mv: ModelValidationRequest = {
      entryId: e.id,
      entryName: r.name,
      entryType: e.type,
      scope,
      tier: e.tier,
      fromTier: scope === 'tier_change' ? e.tier : undefined,
      toTier,
      requestedBy: by,
      note,
      evidence: [
        ...evals.map((x) => `${x.name} v${x.version}: ${x.summary.passed}/${x.summary.total} eval cases passed, injection ${x.summary.injection.passed}/${x.summary.injection.total}`),
        `${plural(e.findings.filter((f) => f.status !== 'closed').length, 'open finding')}, ${plural(e.conditions.filter((c) => c.status !== 'met').length, 'open condition')}`,
      ],
    };
    const review: Review = {
      id: `MRV-${++seq}`,
      title: scope === 'tier_change' ? `Change ${r.name} to ${TIER_LABEL[toTier!].toLowerCase()} tier` : `Validate ${r.name}`,
      customer: `Requested by ${by}`,
      workflowId: wid,
      workflowName: r.name,
      agentSlug: a?.slug ?? '',
      kind: 'model_validation',
      risk: toTier && HIGH.includes(toTier) ? toTier : e.tier,
      confidence: 1,
      proposal: note,
      actionTool: 'validate_model',
      currency: 'CAD',
      policy: POLICY,
      slaMinutes: 5 * 8 * 60 - Math.round((Date.now() - new Date(createdAt).getTime()) / 60_000),
      approvals: [],
      status: 'pending',
      createdAt,
      reasoning: mv.evidence,
      evidence: [],
      modelValidation: mv,
    };
    deps.reviews().unshift(review);
    return review;
  };
  all();
  for (const s of VALIDATION_SEEDS) {
    const e = entries[`mr_${s.refId}`];
    if (e) openValidation(e, s.scope, s.by, s.note, s.toTier, new Date(Date.now() - s.minutesAgo * 60_000).toISOString());
  }

  const decideValidation = (r: Review, input: ReviewDecisionInput): Review => {
    const mv = r.modelValidation!;
    if (!isOpen(r)) throw new ApiError(`${r.id} was already decided.`, 409);
    if (input.actingAsId) {
      const p = PRINCIPALS.find((x) => x.id === input.actingAsId);
      throw new ApiError(`Only Model Risk can decide. ${p?.name ?? 'This person'} (${p?.title ?? 'no Model Risk role'}) cannot.`, 403);
    }
    if (mv.requestedBy === deps.me) throw new ApiError('You requested this. Another Model Risk validator must decide it.', 409);
    if (input.decision !== 'approved' && !input.reason?.trim()) throw new ApiError('A reason is required to reject or return.', 400);
    const e = entryOr404(mv.entryId);
    const conditions = (input.conditions ?? []).filter((c) => c.text.trim());
    if (conditions.some((c) => !c.owner || !/^\d{4}-\d{2}-\d{2}$/.test(c.dueDate))) throw new ApiError('Every condition needs an owner and a due date.', 400);
    const outcome = input.decision === 'approved' ? (conditions.length ? 'approved_with_conditions' : 'approved') : 'rejected';
    if (input.decision === 'approved') {
      if (mv.scope === 'tier_change' && mv.toTier) {
        audit(e, 'approved', `Approved the tier change to ${mv.toTier}`, { diff: [{ field: 'Tier', before: e.tier, after: mv.toTier }], reason: input.reason });
        e.tier = mv.toTier;
        e.tierReason = mv.note;
      } else {
        const before = statusOf(e);
        e.status = conditions.length ? 'validated_with_conditions' : 'validated';
        e.nextReviewAt = ymd(HIGH.includes(e.tier) ? 182 : 365);
        audit(e, 'approved', conditions.length ? `Validated with ${conditions.length === 1 ? '1 condition' : `${conditions.length} conditions`}` : 'Validated', { diff: [{ field: 'Validation', before, after: e.status }, { field: 'Next review', after: e.nextReviewAt }], reason: input.reason });
      }
      for (const c of conditions) {
        e.conditions.unshift({ id: id('cnd'), text: c.text.trim(), owner: c.owner, dueDate: c.dueDate, status: 'open', createdBy: deps.me, createdAt: new Date().toISOString() });
        audit(e, 'created', `Added condition: ${c.text.trim()}`, { diff: [{ field: 'Due', after: c.dueDate }, { field: 'Owner', after: c.owner }] });
      }
    } else {
      audit(e, 'rejected', mv.scope === 'tier_change' ? `${input.decision === 'returned' ? 'Returned' : 'Rejected'} the tier change to ${mv.toTier}` : `${input.decision === 'returned' ? 'Returned' : 'Rejected'} the validation`, { reason: input.reason });
    }
    if (mv.scope !== 'tier_change') e.validations.unshift({ id: id('val'), validator: deps.me, date: new Date().toISOString(), outcome, conditions: conditions.map((c) => c.text.trim()), reason: input.reason, reviewId: r.id });
    Object.assign(r, { status: input.decision, decidedAt: new Date().toISOString(), decisionReason: input.reason, assignee: deps.me, approvals: input.decision === 'approved' ? [deps.me] : [] });
    r.modelValidation = { ...mv, outcome, conditions };
    return r;
  };

  // ── Publish requests: eval gate and inventory status ──
  const gateFor = (r: Review): { pins: AgentEvalPin[]; gate: EvalGate; entry: NonNullable<NonNullable<Review['publish']>['modelEntry']> } => {
    const e = seedEntry(r.workflowId, 'workflow');
    const threshold = INJECTION_THRESHOLD[e.tier];
    const pins = pinnedAgents(r.workflowId).map((a): AgentEvalPin => {
      const s = deps.evals.summaryFor(a.id, a.version);
      const advisory: string[] = [];
      let blocker: string | undefined;
      let blockerKind: AgentEvalPin['blockerKind'];
      const block = (kind: NonNullable<AgentEvalPin['blockerKind']>, text: string) => {
        blocker = text;
        blockerKind = kind;
      };
      if (deps.evals.isRunning(a.id, a.version)) block('running', `Evals for ${a.name} v${a.version} are still running.`);
      else if (!s) block('no_run', `${a.name} v${a.version} has no eval run.`);
      else {
        if (s.injection.regressions) block('injection', `${a.name} has ${s.injection.regressions === 1 ? '1 regression' : `${s.injection.regressions} regressions`} on its injection set.`);
        else if (s.injection.total && s.injection.passed / s.injection.total < threshold)
          block('injection', `${a.name} passes ${s.injection.passed} of ${s.injection.total} injection cases; model tier ${e.tier} needs ${Math.round(threshold * 100)}%.`);
        const failing = s.total - s.passed - (s.injection.total - s.injection.passed);
        const otherRegressions = s.regressions - s.injection.regressions;
        // Spec 04 A11: failing evals block at medium tier and above; at low tier they are advisory and need a reason.
        if (failing > 0 && e.tier !== 'low' && !blocker) block('failing', `${a.name} v${a.version}: ${failing === 1 ? '1 eval case fails' : `${failing} eval cases fail`}; model tier ${e.tier} needs every case to pass.`);
        else if (failing > 0) advisory.push(`${a.name} v${a.version}: ${failing === 1 ? '1 eval case fails' : `${failing} eval cases fail`}${otherRegressions ? `, ${otherRegressions === 1 ? '1 is a regression' : `${otherRegressions} are regressions`}` : ''}.`);
      }
      return { agentId: a.id, agentName: a.name, version: a.version, summary: s, blocker, blockerKind, advisory };
    });
    const status = statusOf(e);
    return {
      pins,
      gate: { tier: e.tier, injectionThreshold: threshold, blockers: pins.flatMap((p) => (p.blocker ? [p.blocker] : [])), advisory: pins.flatMap((p) => p.advisory), reasonRequired: pins.some((p) => p.advisory.length > 0) },
      entry: { entryId: e.id, tier: e.tier, validationStatus: status, needsValidation: e.tier !== 'low' && status !== 'validated' && status !== 'validated_with_conditions' },
    };
  };
  /** Decided requests keep the gate they were decided on. */
  const frozen: Record<string, Pick<NonNullable<Review['publish']>, 'agentEvals' | 'evalGate' | 'modelEntry'>> = {};
  const enrich = (r: Review): Review => {
    if (r.kind !== 'publish_request' || !r.publish) return r;
    if (!isOpen(r) && frozen[r.id]) return { ...r, publish: { ...r.publish, ...frozen[r.id] } };
    const g = gateFor(r);
    return { ...r, publish: { ...r.publish, agentEvals: g.pins, evalGate: g.gate, modelEntry: g.entry } };
  };

  const wrapReviews = (inner: OpsApi['reviews']): OpsApi['reviews'] => ({
    ...inner,
    list: async (p) => {
      const res = await inner.list(p);
      return { ...res, data: res.data.map(enrich) };
    },
    get: async (rid) => enrich(await inner.get(rid)),
    decide: async (rid, input) => {
      const r = deps.reviews().find((x) => x.id === rid);
      if (r?.kind === 'model_validation') return respond(() => decideValidation(r, input));
      if (r?.kind === 'publish_request' && isOpen(r) && input.decision === 'approved') {
        const snapshot = await respond(() => {
          const g = gateFor(r);
          if (g.gate.blockers.length) throw new ApiError(`Publishing is blocked. ${g.gate.blockers.join(' ')}`, 422);
          if (g.gate.reasonRequired && !input.reason?.trim()) throw new ApiError('Explain the failing evals before approving. The reason goes into the evidence bundle.', 400);
          return { agentEvals: g.pins, evalGate: g.gate, modelEntry: g.entry };
        });
        const out = await inner.decide(rid, input);
        frozen[rid] = snapshot;
        return enrich(out);
      }
      return enrich(await inner.decide(rid, input));
    },
    bulkDecide: async (ids, decision, reason) => {
      const validations = ids.filter((rid) => deps.reviews().find((x) => x.id === rid)?.kind === 'model_validation');
      const rest = ids.filter((rid) => !validations.includes(rid));
      const res: BulkResult = rest.length ? await inner.bulkDecide(rest, decision, reason) : { updated: [], skipped: [] };
      return { updated: res.updated, skipped: [...res.skipped, ...validations.map((rid) => ({ id: rid, reason: 'Model validations need an individual decision' }))] };
    },
  });

  const VIEW: Record<Exclude<ModelRiskView, 'all'>, (r: ModelEntry) => boolean> = {
    needs_validation: (r) => r.validationStatus === 'not_validated' || r.validationStatus === 'in_validation',
    due_30d: (r) => !!r.nextReviewAt && r.nextReviewAt >= ymd(0) && r.nextReviewAt <= ymd(30),
    open_findings: (r) => r.openFindings > 0,
    expired: (r) => r.validationStatus === 'expired',
  };

  const api: ModelRiskApi = {
    list: (p) =>
      respond((m) => {
        const scoped = all().map(row).filter((r) => inTeam(r.owner));
        const src = m === 'empty' ? [] : scoped;
        const inView = p.view === 'all' ? scoped : scoped.filter(VIEW[p.view]);
        return {
          ...list(inView, p, { text: (r) => `${r.name} ${r.model} ${r.alias} ${r.owner}`, value: field, facetKeys: ['type', 'tier', 'validationStatus', 'ownerTeam', 'provider'] }, m),
          viewCounts: { all: src.length, needs_validation: src.filter(VIEW.needs_validation).length, due_30d: src.filter(VIEW.due_30d).length, open_findings: src.filter(VIEW.open_findings).length, expired: src.filter(VIEW.expired).length },
          stats: {
            total: src.length,
            highOrCritical: src.filter((r) => HIGH.includes(r.tier)).length,
            notValidated: src.filter(VIEW.needs_validation).length,
            dueIn30d: src.filter(VIEW.due_30d).length,
            openFindings: src.reduce((n, r) => n + r.openFindings, 0),
          },
        };
      }),
    get: (mid) =>
      respond((m) => {
        if (m === 'empty') notFound('Model');
        return detail(entryOr404(mid));
      }),
    requestValidation: (ids, note) =>
      respond(() =>
        bulk(ids, (mid) => {
          const e = entries[mid];
          if (!e) return 'Not found';
          const open = openReviewFor(mid);
          if (open) return open.modelValidation?.scope === 'tier_change' ? 'Tier change open with Model Risk' : 'Validation already open';
          openValidation(e, e.validations.length ? 'periodic' : 'initial', deps.me, note?.trim() || (e.validations.length ? 'Periodic revalidation.' : 'First validation.'));
          audit(e, 'edited', 'Requested validation', { reason: note });
        }),
      ),
    setNextReview: (ids, date) =>
      respond(() => {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new ApiError('Choose a date.', 400);
        if (date < ymd(0)) throw new ApiError('The next review must be today or later.', 400);
        return bulk(ids, (mid) => {
          const e = entries[mid];
          if (!e) return 'Not found';
          if (e.nextReviewAt === date) return 'Already on that date';
          audit(e, 'edited', `Set next review to ${date}`, { diff: [{ field: 'Next review', before: e.nextReviewAt ?? 'None', after: date }] });
          e.nextReviewAt = date;
        });
      }),
    changeTier: (mid, input) =>
      respond(() => {
        const e = entryOr404(mid);
        if (!input.reason?.trim()) throw new ApiError('Give a reason for the tier change.', 400);
        if (input.tier === e.tier) throw new ApiError(`Already ${e.tier} tier.`, 400);
        if (HIGH.includes(input.tier) || HIGH.includes(e.tier)) {
          if (openReviewFor(mid)?.modelValidation?.scope === 'tier_change') throw new ApiError('A tier change is already waiting for Model Risk.', 409);
          const r = openValidation(e, 'tier_change', deps.me, input.reason.trim(), input.tier);
          audit(e, 'edited', `Requested a tier change to ${input.tier} (${r.id})`, { diff: [{ field: 'Tier', before: e.tier, after: `${input.tier} (pending)` }], reason: input.reason });
        } else {
          audit(e, 'edited', `Changed tier to ${input.tier}`, { diff: [{ field: 'Tier', before: e.tier, after: input.tier }], reason: input.reason });
          e.tier = input.tier;
          e.tierReason = input.reason.trim();
        }
        return detail(e);
      }),
    addCondition: (mid, input) =>
      respond(() => {
        const e = entryOr404(mid);
        if (!input.text?.trim()) throw new ApiError('Describe the condition.', 400);
        if (!input.owner) throw new ApiError('Choose an owner.', 400);
        if (!/^\d{4}-\d{2}-\d{2}$/.test(input.dueDate)) throw new ApiError('Choose a due date.', 400);
        e.conditions.unshift({ id: id('cnd'), text: input.text.trim(), owner: input.owner, dueDate: input.dueDate, status: 'open', createdBy: deps.me, createdAt: new Date().toISOString() });
        audit(e, 'created', `Added condition: ${input.text.trim()}`, { diff: [{ field: 'Owner', after: input.owner }, { field: 'Due', after: input.dueDate }] });
        return detail(e);
      }),
    setConditionStatus: (mid, cid, status, reason) =>
      respond(() => {
        const e = entryOr404(mid);
        const c = e.conditions.find((x) => x.id === cid) ?? notFound('Condition');
        if (!reason?.trim()) throw new ApiError('Give a reason.', 400);
        audit(e, 'edited', `Marked condition ${status === 'met' ? 'met' : 'open'}: ${c.text}`, { diff: [{ field: 'Status', before: conditionStatus(c).status, after: status }], reason });
        c.status = status === 'overdue' ? 'open' : status;
        return detail(e);
      }),
    options: () => respond(() => ({ owners: deps.owners, validators: VALIDATORS })),
  };

  return { api, wrapReviews };
}
