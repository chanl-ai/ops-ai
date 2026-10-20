import type { AssetRef, AssuranceGate, AssuranceJudge, AssuranceRun, AssuranceRunTrigger, AssuranceStats, AssuranceSuite, AssuranceTab, CaseOutcome, EvidenceBundleRow, GateStep, SuiteDraftCase } from '@/lib/types/assurance';
import type { Agent, Review, Risk, TestCase, ValidationRun, Workflow } from '@/lib/types/domain';
import type { EvalRunTrigger } from '@/lib/types/evals';
import type { EvidenceBundle } from '@/lib/types/model-risk';
import type { SkillTestRun } from '@/lib/types/skills';

import type { AssuranceApi } from '../../assurance-contract';
import type { OpsApi } from '../../contract';
import type { EvalsMock } from '../evals';
import type { FileLinks } from '../files';
import { field, id, list, notFound, respond } from '../runtime';
import { inTeam } from '../teams';
import { EXTRA_RUNS, JUDGES, MIN_AGREEMENT } from './seed';
import type { MockAgent, MockWorkflow } from '../fixtures';

interface SkillSuiteView {
  id: string;
  name: string;
  ownerTeam: string;
  version: number;
  publishedVersion: number | null;
  tests: { id: string; name: string; input: string }[];
  pinnedAgentIds: string[];
  runs: (SkillTestRun & { reviewId?: string })[];
  candidate: SkillTestRun | null;
  live: SkillTestRun | null;
}

export interface AssuranceDeps {
  agents: () => MockAgent[];
  workflows: () => MockWorkflow[];
  reviews: () => Review[];
  tests: () => TestCase[];
  /** The newest stored validation of a workflow, or its live graph scored without storing one. */
  workflowRun: (workflowId: string) => ValidationRun | null;
  evals: EvalsMock;
  /** An `agent_publish` review with its body refreshed while open (agent-publish mock). */
  agentGate: (r: Review) => Review;
  modelRisk: { withGate: (r: Review) => Review; bundlesFor: (refId: string, version: number) => EvidenceBundle[]; tierOf: (refId: string, type: 'agent' | 'workflow') => Risk };
  skills: () => SkillSuiteView[];
  files: FileLinks;
  people: string[];
  me: string;
}

const DAY = 86_400_000;
const TIER_ORDER: Risk[] = ['low', 'medium', 'high', 'critical'];
/** Suite pass rate each tier requires before S5 blocks (spec 04, 5.5); low is advisory. */
const PASS_THRESHOLD: Record<Risk, number | null> = { low: null, medium: 0.9, high: 0.95, critical: 0.98 };
const AGENT_ACTION_KINDS: Review['kind'][] = ['approval', 'exception', 'escalation', 'policy_override'];
const isOpen = (r: Review) => r.status === 'pending' || r.status === 'in_review';

function hash(key: string) {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) h = Math.imul(h ^ key.charCodeAt(i), 16777619);
  return ((h >>> 0) % 10_000) / 10_000;
}
const digestOf = (key: string) => `sha256:${Array.from({ length: 8 }, (_, i) => Math.floor(hash(`${key}:${i}`) * 0xffff).toString(16).padStart(4, '0')).join('')}`;
const rate = (passed: number, total: number) => (total ? passed / total : 0);
const pctText = (x: number) => `${Math.round(x * 100)}%`;
const TRIGGER: Record<EvalRunTrigger, AssuranceRunTrigger> = { manual: 'manual', save: 'version_saved', restore: 'version_saved' };

/**
 * Assurance over the existing stores. Suites, runs, gates and evidence are computed on each read from the agent
 * evals, skill tests, workflow tests, model risk and review stores; this store keeps only the draft cases that
 * review decisions propose and the judges, which nothing else holds.
 */
export function createAssuranceMock(deps: AssuranceDeps) {
  const drafts: (SuiteDraftCase & { suiteId: string })[] = [];

  const agentRef = (a: Agent): AssetRef => ({ kind: 'agent', id: a.id, name: a.name, href: `/agents/${a.id}` });
  const workflowRef = (w: Workflow): AssetRef => ({ kind: 'workflow', id: w.id, name: w.name, href: `/workflows/${w.id}` });
  const skillRef = (s: { id: string; name: string }): AssetRef => ({ kind: 'skill', id: s.id, name: s.name, href: `/skills/${s.id}` });
  const liveAgentVersion = (a: Agent) => {
    const pinned = a.usedIn.filter((u) => u.status === 'live').map((u) => u.pinnedVersion);
    return pinned.length ? Math.max(...pinned) : null;
  };
  /** A reviewer label on about a quarter of cases; reviewers mostly agree with the run. */
  const humanVerdict = (caseId: string, outcome: CaseOutcome): CaseOutcome | null => {
    const h = hash(`label:${caseId}`);
    if (h > 0.25) return null;
    return h < 0.03 ? (outcome === 'pass' ? 'fail' : 'pass') : outcome;
  };
  const draftsOf = (suiteId: string) => drafts.filter((d) => d.suiteId === suiteId).map(({ suiteId: _s, ...d }) => (void _s, d));

  // ── Suites ──
  const agentSuite = (a: MockAgent): AssuranceSuite => {
    const sid = `agent:${a.id}`;
    const run = deps.evals.history().find((r) => r.agentId === a.id);
    const s = run?.summary;
    return {
      id: sid,
      asset: agentRef(a),
      owner: a.owner,
      tier: deps.modelRisk.tierOf(a.id, 'agent'),
      cases: deps.evals.casesOf(a).length,
      draftCases: draftsOf(sid).length,
      passRate: s ? rate(s.passed, s.total) : null,
      livePassRate: s?.live ? rate(s.live.passed, s.live.total) : null,
      regressions: s ? s.regressions : null,
      candidateVersion: run?.draftVersion ?? null,
      liveVersion: run?.compared?.label === 'live' ? run.compared.version : liveAgentVersion(a),
      lastRunAt: run?.finishedAt ?? null,
      failing: !!s && s.passed < s.total,
      results: (run?.results ?? []).map((r) => ({ caseId: r.caseId, name: r.caseName, candidate: r.draft.status, live: r.live?.status ?? null, regression: r.regression, humanVerdict: humanVerdict(r.caseId, r.draft.status) })),
      drafts: draftsOf(sid),
    };
  };
  const skillTier = (s: SkillSuiteView): Risk => {
    const tiers = s.pinnedAgentIds.map((aid) => deps.modelRisk.tierOf(aid, 'agent'));
    return tiers.length ? tiers.reduce((x, y) => (TIER_ORDER.indexOf(y) > TIER_ORDER.indexOf(x) ? y : x)) : 'low';
  };
  const skillSuite = (view: SkillSuiteView): AssuranceSuite => {
    const s = view;
    const sid = `skill:${s.id}`;
    const c = s.candidate;
    const live = s.live && s.publishedVersion !== s.version ? s.live : null;
    return {
      id: sid,
      asset: skillRef(view),
      owner: s.ownerTeam,
      tier: skillTier(view),
      cases: s.tests.length,
      draftCases: draftsOf(sid).length,
      passRate: c ? rate(c.passed, c.total) : null,
      livePassRate: live ? rate(live.passed, live.total) : c && s.publishedVersion === s.version ? rate(c.passed, c.total) : null,
      regressions: c && live ? c.results.filter((r) => r.status === 'fail' && live.results.find((l) => l.caseId === r.caseId)?.status === 'pass').length : c ? 0 : null,
      candidateVersion: c ? s.version : null,
      liveVersion: s.publishedVersion,
      lastRunAt: c?.ranAt ?? null,
      failing: !!c && c.passed < c.total,
      results: (c?.results ?? []).map((r) => {
        const l = live?.results.find((x) => x.caseId === r.caseId)?.status ?? (s.publishedVersion === s.version ? r.status : null);
        return { caseId: r.caseId, name: r.caseName, candidate: r.status, live: l, regression: l === 'pass' && r.status === 'fail', humanVerdict: humanVerdict(r.caseId, r.status) };
      }),
      drafts: draftsOf(sid),
    };
  };
  const workflowSuite = (w: MockWorkflow): AssuranceSuite => {
    const sid = `workflow:${w.id}`;
    const run = deps.workflowRun(w.id);
    const s = run?.summary;
    const compared = run?.results.some((r) => r.live) ?? false;
    return {
      id: sid,
      asset: workflowRef(w),
      owner: w.owner,
      tier: deps.modelRisk.tierOf(w.id, 'workflow'),
      cases: deps.tests().filter((t) => t.workflowId === w.id).length,
      draftCases: draftsOf(sid).length,
      passRate: s && s.total ? rate(s.passed, s.total) : null,
      livePassRate: run && compared ? rate(run.results.filter((r) => r.live?.passed).length, run.results.length) : w.status === 'live' && s?.total ? rate(s.passed, s.total) : null,
      regressions: s && s.total ? s.regressions : null,
      candidateVersion: run ? (run.target === 'draft' ? w.version + 1 : w.version) : null,
      liveVersion: w.status === 'live' ? w.version : null,
      lastRunAt: run?.ranAt ?? null,
      failing: !!s && s.passed < s.total,
      results: (run?.results ?? []).map((r) => {
        const cand: CaseOutcome = r.draft.passed ? 'pass' : 'fail';
        return { caseId: r.caseId, name: r.caseName, candidate: cand, live: r.live ? (r.live.passed ? 'pass' : 'fail') : w.status === 'live' && run?.target === 'live' ? cand : null, regression: r.regression, humanVerdict: humanVerdict(r.caseId, cand) };
      }),
      drafts: draftsOf(sid),
    };
  };
  // Failing suites first, then suites that never ran, so the rows that need someone are on the first page.
  const rank = (x: AssuranceSuite) => (x.failing ? 0 : x.passRate === null ? 1 : 2);
  const suites = (): AssuranceSuite[] =>
    [
      ...deps.workflows().filter((w) => inTeam(w.owner)).map(workflowSuite),
      ...deps.agents().filter((a) => inTeam(a.owner)).map(agentSuite),
      ...deps.skills().filter((s) => inTeam(s.ownerTeam)).map(skillSuite),
    ].sort((x, y) => rank(x) - rank(y));

  // ── Runs ──
  const runs = (): AssuranceRun[] => {
    const agents = deps.agents().filter((a) => inTeam(a.owner));
    const evalRuns = deps.evals.history().flatMap((r): AssuranceRun[] => {
      const a = agents.find((x) => x.id === r.agentId);
      if (!a || !r.summary) return [];
      return [{ id: r.id, asset: agentRef(a), version: r.draftVersion, trigger: TRIGGER[r.trigger], passed: r.summary.passed, total: r.summary.total, passRate: rate(r.summary.passed, r.summary.total), regressions: r.summary.regressions, durationMs: Date.parse(r.finishedAt ?? r.startedAt) - Date.parse(r.startedAt), costUsd: r.summary.costUsd, ranAt: r.finishedAt ?? r.startedAt }];
    });
    const extra = EXTRA_RUNS.flatMap((x): AssuranceRun[] => {
      const a = agents.find((y) => y.id === x.agentId);
      return a ? [{ id: `evr_${x.trigger}_${a.id}`, asset: agentRef(a), version: liveAgentVersion(a) ?? a.version, trigger: x.trigger, passed: x.passed, total: x.total, passRate: rate(x.passed, x.total), regressions: x.regressions, durationMs: x.durationMs, costUsd: x.costUsd, ranAt: new Date(Date.now() - x.daysAgo * DAY).toISOString() }] : [];
    });
    const skillRuns = deps.skills().filter((v) => inTeam(v.ownerTeam)).flatMap((view) =>
      view.runs.map((r): AssuranceRun => ({ id: r.id, asset: skillRef(view), version: r.version, trigger: r.reviewId ? 'publish_request' : 'manual', passed: r.passed, total: r.total, passRate: rate(r.passed, r.total), regressions: 0, durationMs: r.results.reduce((n, x) => n + x.latencyMs, 0), costUsd: Math.round(r.total * 0.012 * 1000) / 1000, ranAt: r.ranAt, reviewId: r.reviewId })),
    );
    const publishRuns = deps.reviews().filter((r) => r.kind === 'publish_request' && r.publish?.validation && inTeam(deps.workflows().find((w) => w.id === r.workflowId)?.owner)).map((r): AssuranceRun => {
      const v = r.publish!.validation!;
      const w = deps.workflows().find((x) => x.id === r.workflowId)!;
      return { id: `val_${r.id}`, asset: workflowRef(w), version: r.publish!.toVersion, trigger: 'publish_request', passed: v.passed, total: v.total, passRate: rate(v.passed, v.total), regressions: v.regressions, durationMs: 4000 + v.total * 1800, costUsd: Math.round(v.total * 0.018 * 1000) / 1000, ranAt: r.createdAt, reviewId: r.id };
    });
    return [...evalRuns, ...extra, ...skillRuns, ...publishRuns].sort((x, y) => y.ranAt.localeCompare(x.ranAt));
  };

  // ── Gates ──
  const gateOf = (raw: Review): AssuranceGate => {
    const r = deps.modelRisk.withGate(raw);
    const p = r.publish!;
    const w = deps.workflows().find((x) => x.id === r.workflowId);
    const tier = deps.modelRisk.tierOf(r.workflowId, 'workflow');
    const v = p.validation;
    const pins = p.agentEvals ?? [];
    const threshold = p.evalGate?.injectionThreshold ?? 1;
    const passBar = PASS_THRESHOLD[tier];
    const modeAt = (blockingFrom: 'always' | 'medium'): GateStep['mode'] => (blockingFrom === 'always' || tier !== 'low' ? 'blocking' : 'advisory');
    const pendingPins = pins.filter((x) => x.blockerKind === 'running' || x.blockerKind === 'no_run');
    const injection = pins.filter((x) => x.blockerKind === 'injection');
    const failingPins = pins.filter((x) => x.blockerKind === 'failing' || x.advisory.length);
    const steps: GateStep[] = [
      { step: 'structural', label: 'Structural check', mode: 'blocking', result: !v ? 'pending' : v.checksFailing ? 'fail' : 'pass', detail: !v ? 'No validation run on this version yet' : v.checksFailing ? `${v.checksFailing} structural ${v.checksFailing === 1 ? 'error' : 'errors'} in the graph` : 'Every step resolves to an agent or tool' },
      { step: 'evidence_integrity', label: 'Evidence integrity', mode: 'blocking', result: !v ? 'fail' : !v.total ? 'fail' : pendingPins.length ? 'pending' : 'pass', detail: !v ? 'No completed run for this version' : !v.total ? 'The suite has no cases, so the run proves nothing' : pendingPins.length ? pendingPins.map((x) => x.blocker).join(' ') : `${v.total} workflow cases and ${pins.length} pinned agent ${pins.length === 1 ? 'run' : 'runs'} on the candidate` },
      { step: 'injection', label: 'Injection threshold', mode: 'blocking', result: pendingPins.length ? 'pending' : injection.length ? 'fail' : 'pass', detail: injection.length ? injection.map((x) => x.blocker).join(' ') : `Every pinned agent at or above ${pctText(threshold)} with no injection regression` },
      {
        step: 'pass_rate',
        label: 'Suite pass rate',
        mode: modeAt('medium'),
        result: !v ? 'pending' : (passBar !== null && rate(v.passed, v.total) < passBar) || (passBar === null && v.passed < v.total) || failingPins.length ? 'fail' : 'pass',
        detail: !v ? 'Waiting for a run' : `${v.passed} of ${v.total} workflow cases pass${passBar !== null ? `; tier ${tier} needs ${pctText(passBar)}` : '; failures need the approver’s reason'}${failingPins.length ? `. ${[...failingPins.map((x) => x.blocker).filter(Boolean), ...failingPins.flatMap((x) => x.advisory)].join(' ')}` : ''}`,
      },
      { step: 'regressions', label: 'Regressions against live', mode: modeAt('medium'), result: !v ? 'pending' : v.regressions ? 'fail' : 'pass', detail: !v ? 'Waiting for a run' : v.regressions ? `${v.regressions} ${v.regressions === 1 ? 'case passes' : 'cases pass'} on live and ${v.regressions === 1 ? 'fails' : 'fail'} on the candidate` : 'No case got worse than live' },
    ];
    return {
      reviewId: r.id,
      asset: w ? workflowRef(w) : { kind: 'workflow', id: r.workflowId, name: r.workflowName, href: `/workflows/${r.workflowId}` },
      fromVersion: p.fromVersion,
      toVersion: p.toVersion,
      tier,
      requestedBy: p.requestedBy,
      requestedAt: r.createdAt,
      reviewStatus: r.status as AssuranceGate['reviewStatus'],
      steps,
      blocked: isOpen(r) && steps.some((s) => s.mode === 'blocking' && s.result === 'fail'),
    };
  };
  /** Agent publishes have no workflow suite: integrity, injection, pass rate and regressions come from the agent's run. */
  const agentGateOf = (raw: Review): AssuranceGate => {
    const r = deps.agentGate(raw);
    const p = r.agentPublish!;
    const a = deps.agents().find((x) => x.id === p.agentId);
    const c = p.candidate;
    const running = p.blockers.some((b) => b.includes('still running'));
    const injection = p.blockers.find((b) => b.includes('injection'));
    const advisory = p.tier === 'low';
    const steps: GateStep[] = [
      { step: 'evidence_integrity', label: 'Evidence integrity', mode: 'blocking', result: c ? 'pass' : running ? 'pending' : 'fail', detail: c ? `${c.total} eval cases ran on v${p.version}` : running ? `Evals for v${p.version} are still running` : `v${p.version} has no eval run` },
      { step: 'injection', label: 'Injection threshold', mode: 'blocking', result: !c ? 'pending' : injection ? 'fail' : 'pass', detail: injection ?? (c ? `${c.injection.passed} of ${c.injection.total} injection cases pass` : 'Waiting for a run') },
      { step: 'pass_rate', label: 'Suite pass rate', mode: advisory ? 'advisory' : 'blocking', result: !c ? 'pending' : p.failing ? 'fail' : 'pass', detail: !c ? 'Waiting for a run' : p.failing ? `${p.failing === 1 ? '1 case fails' : `${p.failing} cases fail`} outside the injection set${advisory ? '; the approver gives a reason' : `; tier ${p.tier} needs every case to pass`}` : 'Every case passes' },
      { step: 'regressions', label: 'Regressions against published', mode: advisory ? 'advisory' : 'blocking', result: !c ? 'pending' : c.regressions ? 'fail' : 'pass', detail: !c ? 'Waiting for a run' : c.regressions ? `${c.regressions === 1 ? '1 case passes' : `${c.regressions} cases pass`} on the published version and fails on v${p.version}` : 'No case got worse than the published version' },
    ];
    return {
      reviewId: r.id,
      asset: a ? agentRef(a) : { kind: 'agent', id: p.agentId, name: p.agentName, href: `/agents/${p.agentId}` },
      fromVersion: p.fromVersion,
      toVersion: p.version,
      tier: p.tier,
      requestedBy: p.requestedBy,
      requestedAt: r.createdAt,
      reviewStatus: r.status as AssuranceGate['reviewStatus'],
      steps,
      blocked: isOpen(r) && p.blockers.length > 0,
    };
  };
  const gates = () =>
    [
      ...deps.reviews().filter((r) => r.kind === 'publish_request' && r.publish && inTeam(deps.workflows().find((w) => w.id === r.workflowId)?.owner)).map(gateOf),
      ...deps.reviews().filter((r) => r.kind === 'agent_publish' && r.agentPublish && inTeam(deps.agents().find((a) => a.id === r.agentPublish!.agentId)?.owner)).map(agentGateOf),
    ]
      .sort((x, y) => Number(y.reviewStatus === 'pending' || y.reviewStatus === 'in_review') - Number(x.reviewStatus === 'pending' || x.reviewStatus === 'in_review') || y.requestedAt.localeCompare(x.requestedAt));

  // ── Evidence ──
  const approversFor = (workflowId: string | null, refId: string, version: number) => {
    const approved = workflowId ? deps.reviews().find((r) => r.kind === 'publish_request' && r.workflowId === workflowId && r.status === 'approved' && r.publish?.toVersion === version) : undefined;
    if (approved?.approvals.length) return approved.approvals;
    const i = Math.floor(hash(`${refId}:${version}:appr`) * deps.people.length);
    return [deps.people[i], deps.people[(i + 2) % deps.people.length]];
  };
  type Live = { ref: AssetRef; refId: string; version: number; workflowId: string | null };
  const liveVersions = (): Live[] => [
    ...deps.workflows().filter((w) => inTeam(w.owner) && w.status === 'live').map((w) => ({ ref: workflowRef(w), refId: w.id, version: w.version, workflowId: w.id })),
    ...deps.agents().filter((a) => inTeam(a.owner)).flatMap((a) => {
      const v = liveAgentVersion(a);
      return v === null ? [] : [{ ref: agentRef(a), refId: a.id, version: v, workflowId: null }];
    }),
  ];
  const evidence = (): EvidenceBundleRow[] => {
    const live = liveVersions();
    const assets: { ref: AssetRef; refId: string; version: number; workflowId: string | null }[] = [
      ...deps.workflows().filter((w) => inTeam(w.owner)).map((w) => ({ ref: workflowRef(w), refId: w.id, version: w.version, workflowId: w.id })),
      ...deps.agents().filter((a) => inTeam(a.owner)).map((a) => ({ ref: agentRef(a), refId: a.id, version: a.version, workflowId: null })),
    ];
    return assets
      .flatMap((x) =>
        deps.modelRisk.bundlesFor(x.refId, x.version).map((b) => ({ id: b.bundleId, asset: x.ref, version: b.version, digest: digestOf(b.bundleId), approvers: approversFor(x.workflowId, x.refId, b.version), sealedAt: b.sealedAt, live: live.some((l) => l.refId === x.refId && l.version === b.version) })),
      )
      .sort((x, y) => y.sealedAt.localeCompare(x.sealedAt));
  };
  const liveUnsealed = () => liveVersions().filter((l) => !deps.modelRisk.bundlesFor(l.refId, l.version).some((b) => b.version === l.version)).length;

  // ── Judges ──
  const judges = (): AssuranceJudge[] =>
    JUDGES.map((j) => ({ ...j, minAgreement: MIN_AGREEMENT, lastRecalibratedAt: new Date(Date.now() - j.recalibratedDaysAgo * DAY).toISOString(), disagreements: j.disagreements.map((d, i) => ({ id: `${j.id}_d${i}`, criterion: j.criterion, ...d })) })).sort((x, y) => x.agreement - y.agreement);

  const stats = (s: AssuranceSuite[], g: AssuranceGate[], j: AssuranceJudge[]): AssuranceStats => {
    const low = j[0];
    return { failingSuites: s.filter((x) => x.failing).length, gatesBlocked: g.filter((x) => x.blocked).length, liveUnsealed: liveUnsealed(), lowestJudge: low ? { name: low.name, agreement: low.agreement } : null };
  };

  const OPTS = {
    suites: { text: (r: AssuranceSuite) => `${r.asset.name} ${r.owner}`, value: (r: AssuranceSuite, k: string) => (k === 'kind' ? r.asset.kind : k === 'result' ? (r.passRate === null ? 'not_run' : r.failing ? 'failing' : 'passing') : field(r, k)), facetKeys: ['kind', 'tier', 'result'] },
    runs: { text: (r: AssuranceRun) => `${r.asset.name} v${r.version} ${r.id}`, value: (r: AssuranceRun, k: string) => (k === 'kind' ? r.asset.kind : field(r, k)), facetKeys: ['kind', 'trigger'] },
    gates: { text: (r: AssuranceGate) => `${r.asset.name} ${r.reviewId} ${r.requestedBy}`, value: (r: AssuranceGate, k: string) => (k === 'result' ? (r.blocked ? 'blocked' : r.reviewStatus === 'pending' || r.reviewStatus === 'in_review' ? 'ready' : 'decided') : field(r, k)), facetKeys: ['tier', 'result'] },
    evidence: { text: (r: EvidenceBundleRow) => `${r.asset.name} v${r.version} ${r.digest} ${r.approvers.join(' ')}`, value: (r: EvidenceBundleRow, k: string) => (k === 'kind' ? r.asset.kind : field(r, k)), facetKeys: ['kind'] },
    judges: { text: (r: AssuranceJudge) => `${r.name} ${r.criterion} ${r.model}`, value: field, facetKeys: [] as string[] },
  };

  const api: AssuranceApi = {
    list: (p) =>
      respond((m) => {
        const s = suites();
        const g = gates();
        const j = judges();
        const r = runs();
        const e = evidence();
        const empty = m === 'empty';
        const rows = { suites: s, runs: r, gates: g, evidence: e, judges: j } as const;
        const tab = p.tab as AssuranceTab;
        const result = list(rows[tab] as never[], p, OPTS[tab] as never, m);
        return {
          ...result,
          stats: empty ? { failingSuites: 0, gatesBlocked: 0, liveUnsealed: 0, lowestJudge: null } : stats(s, g, j),
          tabCounts: empty ? { suites: 0, runs: 0, gates: 0, evidence: 0, judges: 0 } : { suites: s.length, runs: r.length, gates: g.length, evidence: e.length, judges: j.length },
        } as never;
      }),
    exportBundle: (bid) =>
      respond(() => {
        const b = evidence().find((x) => x.id === bid) ?? notFound('Evidence bundle');
        const owner = deps.workflows().find((w) => w.id === b.asset.id)?.owner ?? deps.agents().find((a) => a.id === b.asset.id)?.owner ?? 'Platform';
        const manifest = { bundle: b.id, digest: b.digest, asset: { kind: b.asset.kind, id: b.asset.id, name: b.asset.name }, version: b.version, approvers: b.approvers, sealedAt: b.sealedAt, exportedBy: deps.me, exportedAt: new Date().toISOString() };
        const text = JSON.stringify(manifest, null, 2);
        return deps.files.writeExport({ name: `evidence-${b.asset.id}-v${b.version}.json`, size: text.length, team: owner, text, ref: { type: 'evidence', id: b.id, name: `${b.asset.name} v${b.version} evidence`, href: '/assurance?tab=evidence' } });
      }),
  };

  // ── Reviews: which suite a decision can add a case to, and the draft it adds ──
  const testTarget = (r: Review): AssetRef | undefined => {
    if (r.kind === 'agent_publish' && r.agentPublish) {
      const a = deps.agents().find((x) => x.id === r.agentPublish!.agentId);
      return a && agentRef(a);
    }
    if (r.kind === 'skill_publish' && r.skillPublish) return skillRef({ id: r.skillPublish.skillId, name: r.skillPublish.skillName });
    if (r.kind === 'publish_request') {
      const w = deps.workflows().find((x) => x.id === r.workflowId);
      return w && workflowRef(w);
    }
    if (AGENT_ACTION_KINDS.includes(r.kind)) {
      const a = deps.agents().find((x) => x.slug === r.agentSlug);
      if (a) return agentRef(a);
      const w = deps.workflows().find((x) => x.id === r.workflowId);
      return w && workflowRef(w);
    }
    return undefined;
  };
  const withTarget = (r: Review): Review => {
    const t = testTarget(r);
    return t ? { ...r, testTarget: t } : r;
  };
  const wrapReviews = (inner: OpsApi['reviews']): OpsApi['reviews'] => ({
    ...inner,
    list: async (p) => {
      const res = await inner.list(p);
      return { ...res, data: res.data.map(withTarget) };
    },
    get: async (rid) => withTarget(await inner.get(rid)),
    decide: async (rid, input) => {
      const out = await inner.decide(rid, input);
      const t = testTarget(out);
      // The case is added only once the decision has stuck, so a refused decision never leaves a stray draft.
      if (input.addTestCase && input.decision !== 'approved' && t) {
        drafts.unshift({
          id: id('dc'),
          suiteId: `${t.kind}:${t.id}`,
          name: out.title,
          input: out.kind === 'publish_request' ? (out.publish?.note ?? out.proposal) : `${out.customer}: ${out.proposal}`,
          source: 'review',
          status: 'draft',
          reviewId: out.id,
          reason: input.reason ?? '',
          createdBy: deps.me,
          createdAt: new Date().toISOString(),
        });
      }
      return withTarget(out);
    },
  });

  return { api, wrapReviews };
}
