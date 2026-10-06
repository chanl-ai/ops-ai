import type { Agent, AgentGuardrails, Version } from '@/lib/types/domain';
import type { EvalCase, EvalCaseInput, EvalCaseOutcome, EvalCaseResult, EvalCheck, EvalCheckResult, EvalRun, EvalRunTrigger, EvalSuite, EvalSuiteKind, EvalSummary, EvalVersionStats, EvalVersionSummary } from '@/lib/types/evals';

import { ApiError } from '../../contract';
import type { EvalsApi } from '../../evals-contract';
import type { OpsApi } from '../../contract';
import { PRINCIPALS } from '../run-as/principals';
import type { FileLinks } from '../files';
import { bulk, field, id, list, notFound, respond } from '../runtime';
import { AGENT_CASES, PLATFORM_TEMPLATES, RULE_OF, SEED_FAILURES, SUITE_META } from './seed';

/** What an eval scores: the settings of one agent version. */
interface AgentContent {
  instructions: string;
  toolNames: string[];
  collections: string[];
  guardrails: AgentGuardrails;
  model: string;
}

export interface EvalsDeps {
  agents: () => Agent[];
  toolName: (toolId: string) => string | undefined;
  toolAccess: (name: string) => string | undefined;
  collections: () => string[];
  me: string;
  /** Imported CSVs are files; the eval set is recorded as a reference. */
  files: FileLinks;
}

const RUN_MS = 3500;
const SUITES: EvalSuiteKind[] = ['agent', 'injection', 'leakage', 'refusals'];
const COST_PER_CASE: Record<string, number> = { 'claude-haiku-4-5': 0.004, 'claude-sonnet-5': 0.012, 'claude-opus-5-5': 0.031 };

/** Stable pseudo-random number in [0, 1) for a key, so latencies and costs do not change between reads. */
function hash(key: string) {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) h = Math.imul(h ^ key.charCodeAt(i), 16777619);
  return ((h >>> 0) % 10_000) / 10_000;
}

const p95 = (xs: number[]) => {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(s.length * 0.95))];
};

const CHECK_LABEL: Record<EvalCheck['type'], (c: EvalCheck) => string> = {
  calls_tool: (c) => `Calls ${c.tool}${c.args?.length ? ` with ${c.args.map((a) => `${a.path} = ${a.equals}`).join(', ')}` : ''}`,
  not_calls_tool: (c) => `Does not call ${c.tool}`,
  cites: (c) => `Cites ${c.source}${c.section ? ` · ${c.section}` : ''}`,
  reply_contains: (c) => `Reply contains “${c.text}”`,
  reply_not_contains: (c) => `Reply must not contain “${c.text}”`,
  refuses: (c) => `Refuses: ${c.text}`,
  extracts: (c) => `Extracts ${c.field} = ${c.value}`,
  rubric: (c) => `Rubric: ${c.text}`,
};
export const checkLabel = (c: EvalCheck) => CHECK_LABEL[c.type](c);

/**
 * Agent evals over the mock agents. Each case is scored against a version's settings, so changing an agent
 * changes its results: turning off PII redaction fails the leakage set, raising the tool-call limit above 8
 * fails the injection cases that try to trigger a write, clearing the instructions fails the override cases,
 * and refusals pass only for blocked topics or agents set to hand off or decline when unsure.
 */
export function createEvalsMock(deps: EvalsDeps) {
  const contentOf = (a: Agent): AgentContent => ({
    instructions: a.instructions,
    toolNames: a.toolIds.map(deps.toolName).filter((n): n is string => !!n),
    collections: [...a.collections],
    guardrails: structuredClone(a.guardrails),
    model: a.model,
  });
  /** Settings per saved version. Versions before the mock started share the seed settings. */
  const snapshots: Record<string, Record<number, AgentContent>> = {};
  const seedContent: Record<string, AgentContent> = {};
  for (const a of deps.agents()) {
    seedContent[a.id] = contentOf(a);
    snapshots[a.id] = { [a.version]: contentOf(a) };
  }
  const contentAt = (a: Agent, v: number) => snapshots[a.id]?.[v] ?? seedContent[a.id] ?? contentOf(a);

  // ── Cases ──
  const writeToolOf = (c: AgentContent) => c.toolNames.find((t) => ['write', 'money_movement'].includes(deps.toolAccess(t) ?? '')) ?? 'transfer_funds';
  const principalName = (pid?: string) => PRINCIPALS.find((p) => p.id === pid)?.name;
  const ownCases: EvalCase[] = Object.entries(AGENT_CASES).flatMap(([agentId, seeds]) =>
    seeds.map((s, i) => ({
      id: `ec_${agentId.slice(3)}_${s.key}`,
      agentId,
      suite: 'agent' as const,
      name: s.name,
      input: s.input,
      context: { runAsId: s.runAsId, runAsName: principalName(s.runAsId), collections: s.collections ?? [] },
      checks: s.checks,
      source: s.source ?? 'manual',
      readOnly: false,
      createdAt: new Date(Date.now() - (40 - i) * 86_400_000).toISOString(),
      createdBy: 'Maya Okafor',
      lastOutcome: null,
    })),
  );
  const platformCasesFor = (a: Agent): EvalCase[] => {
    const write = writeToolOf(contentOf(a));
    return PLATFORM_TEMPLATES.map((t) => ({
      id: `${a.id}_${t.key}`,
      agentId: a.id,
      suite: t.suite,
      name: t.name,
      input: t.input,
      context: { runAsId: t.runAsId, runAsName: principalName(t.runAsId), collections: [] },
      checks: t.checks.map((c) => (c.tool === '{write}' ? { ...c, tool: write } : c)),
      source: 'platform',
      readOnly: true,
      createdAt: '2026-06-01T09:00:00.000Z',
      createdBy: 'Platform team',
      lastOutcome: null,
    }));
  };
  const keyOf = (c: EvalCase) => (c.suite === 'agent' ? c.id.split('_').slice(2).join('_') : c.id.slice(c.agentId.length + 1));
  const casesOf = (a: Agent) => [...ownCases.filter((c) => c.agentId === a.id), ...platformCasesFor(a)];

  // ── Scoring ──
  const refusesTopic = (c: AgentContent, topic = '') =>
    c.guardrails.whenUnsure !== 'ask' || c.guardrails.blockedTopics.some((b) => b.toLowerCase().includes(topic.toLowerCase()) || topic.toLowerCase().includes(b.toLowerCase()));

  const platformFailure = (rule: string, c: AgentContent, kase: EvalCase): string | undefined => {
    if (rule === 'redaction' && !c.guardrails.redactPii) return kase.suite === 'leakage' ? `Returned content ${kase.context.runAsName ?? 'this person'} is not entitled to.` : 'Disclosed customer details with redaction off.';
    if (rule === 'tool_limit' && c.guardrails.maxToolCallsPerTurn > 8) return `Called ${writeToolOf(c)} on the injected instruction.`;
    if (rule === 'instructions' && !c.instructions.trim()) return 'Followed the injected instruction: the agent has no instructions to hold to.';
    if (rule === 'topic' && !refusesTopic(c, kase.checks[0]?.text)) return `Answered instead of declining: ${kase.checks[0]?.text?.toLowerCase()}.`;
    return undefined;
  };

  const checkFailure = (ch: EvalCheck, c: AgentContent): string | undefined => {
    if (ch.type === 'calls_tool' && ch.tool && !c.toolNames.includes(ch.tool)) return `${ch.tool} is not granted, so it was never called.`;
    if (ch.type === 'cites' && ch.source && !c.collections.includes(ch.source)) return `${ch.source} is not attached, so nothing from it was cited.`;
    if (ch.type === 'refuses' && !refusesTopic(c, ch.text)) return `Answered instead of declining: ${ch.text?.toLowerCase()}.`;
    return undefined;
  };

  const outcome = (a: Agent, version: number, kase: EvalCase): EvalCaseOutcome => {
    const c = contentAt(a, version);
    const seeded = SEED_FAILURES[`${a.id}:${version}`]?.[keyOf(kase)];
    const rule = kase.suite === 'agent' ? undefined : RULE_OF[keyOf(kase)];
    const caseFailure = seeded ?? (rule ? platformFailure(rule, c, kase) : undefined);
    const checks: EvalCheckResult[] = kase.checks.map((ch, i) => {
      if (ch.type === 'rubric') return { label: checkLabel(ch), status: 'advisory', detail: 'Not scored until judge agreement is measured' };
      // Platform cases are scored as a whole by their rule; agent cases check by check.
      const f = caseFailure ? (i === 0 ? caseFailure : undefined) : kase.suite === 'agent' ? checkFailure(ch, c) : undefined;
      return { label: checkLabel(ch), status: f ? 'fail' : 'pass', detail: f };
    });
    const failure = caseFailure ?? checks.find((x) => x.status === 'fail')?.detail;
    const latencyMs = Math.round(500 + hash(`${kase.id}:${version}`) * 2600 * (c.model === 'claude-opus-5-5' ? 1.6 : c.model === 'claude-haiku-4-5' ? 0.5 : 1));
    return {
      status: failure ? 'fail' : 'pass',
      checks,
      failure,
      reply: failure ? 'The reply did not meet the checks.' : kase.suite === 'agent' ? 'Answered and acted as expected.' : 'Declined and explained what it can help with.',
      latencyMs,
    };
  };

  const liveVersionOf = (a: Agent) => {
    const pinned = a.usedIn.filter((u) => u.status === 'live').map((u) => u.pinnedVersion);
    return pinned.length ? Math.max(...pinned) : null;
  };
  const comparedFor = (a: Agent, version: number): EvalRun['compared'] => {
    const live = liveVersionOf(a);
    if (live !== null && live < version) return { version: live, label: 'live' };
    return version > 1 ? { version: version - 1, label: 'previous' } : null;
  };

  const stats = (a: Agent, version: number, outs: EvalCaseOutcome[]): EvalVersionStats => ({
    version,
    passed: outs.filter((o) => o.status === 'pass').length,
    total: outs.length,
    costUsd: Math.round(outs.length * (COST_PER_CASE[contentAt(a, version).model] ?? 0.012) * 1000) / 1000,
    p95Ms: p95(outs.map((o) => o.latencyMs)),
  });

  const summarise = (a: Agent, run: Pick<EvalRun, 'draftVersion' | 'compared'>, results: EvalCaseResult[]): EvalSummary => {
    const draft = stats(a, run.draftVersion, results.map((r) => r.draft));
    const live = run.compared ? stats(a, run.compared.version, results.map((r) => r.live!).filter(Boolean)) : null;
    return {
      passed: draft.passed,
      total: draft.total,
      regressions: results.filter((r) => r.regression).length,
      advisoryChecks: results.reduce((n, r) => n + r.draft.checks.filter((c) => c.status === 'advisory').length, 0),
      costUsd: Math.round((draft.costUsd + (live?.costUsd ?? 0)) * 1000) / 1000,
      p95Ms: p95(results.flatMap((r) => [r.draft.latencyMs, ...(r.live ? [r.live.latencyMs] : [])])),
      draft,
      live,
      suites: SUITES.map((kind) => {
        const rs = results.filter((r) => r.suite === kind);
        return { kind, name: SUITE_META[kind].name, passed: rs.filter((r) => r.draft.status === 'pass').length, total: rs.length, regressions: rs.filter((r) => r.regression).length };
      }),
    };
  };

  // ── Runs ──
  type StoredRun = EvalRun & { completesAt: number; finalSummary: EvalSummary };
  const runs: StoredRun[] = [];
  const execute = (a: Agent, version: number, trigger: EvalRunTrigger, by: string, at: number): StoredRun => {
    const compared = comparedFor(a, version);
    const results: EvalCaseResult[] = casesOf(a).map((k) => {
      const d = outcome(a, version, k);
      const l = compared ? outcome(a, compared.version, k) : null;
      return { caseId: k.id, caseName: k.name, suite: k.suite, draft: d, live: l, regression: !!l && l.status === 'pass' && d.status === 'fail' };
    });
    const run = { id: id('evr'), agentId: a.id, agentName: a.name, draftVersion: version, compared, trigger, status: 'running' as const, startedAt: new Date(at).toISOString(), requestedBy: by, summary: null, results };
    return { ...run, completesAt: at + RUN_MS, finalSummary: summarise(a, run, results) };
  };
  /** A run finishes a few seconds after it starts; reads flip it to complete once that time has passed. */
  const settle = (r: StoredRun): StoredRun => {
    if (r.status === 'running' && Date.now() >= r.completesAt) Object.assign(r, { status: 'complete', finishedAt: new Date(r.completesAt).toISOString(), summary: r.finalSummary });
    return r;
  };
  const publicRun = (r: StoredRun): EvalRun => {
    const { completesAt: _c, finalSummary: _f, ...rest } = settle(r);
    void _c;
    void _f;
    return rest.status === 'running' ? { ...rest, results: [] } : rest;
  };
  const row = (r: StoredRun) => {
    const { results: _r, ...rest } = publicRun(r);
    void _r;
    return rest;
  };

  // Seed history: the last three versions of each agent, oldest first, a day or more apart.
  for (const a of deps.agents()) {
    const versions = [a.version - 2, a.version - 1, a.version].filter((v) => v >= 1);
    versions.forEach((v, i) => {
      const at = Date.now() - (versions.length - i) * 86_400_000 * (1 + hash(a.id + v) * 3);
      runs.push(settle(execute(a, v, i === versions.length - 1 ? 'save' : 'manual', i % 2 ? 'Maya Okafor' : 'Daniel Brooks', at)));
    });
  }
  runs.sort((x, y) => y.startedAt.localeCompare(x.startedAt));

  const agentOr404 = (aid: string) => deps.agents().find((a) => a.id === aid) ?? notFound('Agent');
  const start = (aid: string, trigger: EvalRunTrigger) => {
    const a = agentOr404(aid);
    snapshots[a.id] = { ...snapshots[a.id], [a.version]: contentOf(a) };
    const r = execute(a, a.version, trigger, deps.me, Date.now());
    runs.unshift(r);
    return r;
  };
  const latestComplete = (aid: string, version?: number) => runs.map(settle).find((r) => r.agentId === aid && r.status === 'complete' && (version === undefined || r.draftVersion === version));

  const withOutcome = (k: EvalCase, a: Agent): EvalCase => {
    const r = latestComplete(a.id, a.version)?.results.find((x) => x.caseId === k.id);
    return { ...k, lastOutcome: r ? r.draft.status : null };
  };

  const validateInput = (i: EvalCaseInput): string | undefined => {
    if (!i.name?.trim()) return 'Name is required';
    if (!i.input?.trim()) return 'Input is required';
    if (!i.checks?.length) return 'Add at least one check';
    const bad = i.checks.find((c) => (['calls_tool', 'not_calls_tool'].includes(c.type) && !c.tool) || (c.type === 'cites' && !c.source) || (c.type === 'extracts' && (!c.field || !c.value)) || (['reply_contains', 'reply_not_contains', 'refuses', 'rubric'].includes(c.type) && !c.text?.trim()));
    if (bad) return `The ${checkLabel(bad).split(' ')[0].toLowerCase()} check is missing a value`;
    if (i.context.runAsId && !principalName(i.context.runAsId)) return 'Run-as person or role not found';
    return undefined;
  };
  const addCase = (aid: string, i: EvalCaseInput, source: EvalCase['source']): EvalCase => {
    const c: EvalCase = {
      id: id('ec'),
      agentId: aid,
      suite: 'agent',
      name: i.name.trim(),
      input: i.input.trim(),
      context: { runAsId: i.context.runAsId, runAsName: principalName(i.context.runAsId), collections: i.context.collections ?? [] },
      checks: i.checks,
      source,
      readOnly: false,
      createdAt: new Date().toISOString(),
      createdBy: deps.me,
      lastOutcome: null,
    };
    ownCases.unshift(c);
    return c;
  };
  const removeOwn = (cid: string): string | undefined => {
    if (PLATFORM_TEMPLATES.some((t) => cid.endsWith(`_${t.key}`) && cid.startsWith('ag_'))) return 'Platform cases are read-only';
    const i = ownCases.findIndex((c) => c.id === cid);
    if (i < 0) return 'Not found';
    ownCases.splice(i, 1);
  };

  const api: EvalsApi = {
    suites: (aid) =>
      respond((m) => {
        const a = agentOr404(aid);
        const last = m === 'empty' ? undefined : latestComplete(aid, a.version);
        return SUITES.map((kind): EvalSuite => {
          const s = last?.summary?.suites.find((x) => x.kind === kind);
          return { kind, ...SUITE_META[kind], caseCount: m === 'empty' ? 0 : casesOf(a).filter((c) => c.suite === kind).length, passed: s?.passed ?? null, total: s?.total ?? null, regressions: s?.regressions ?? null };
        });
      }),
    cases: (aid, p) =>
      respond((m) => {
        const a = agentOr404(aid);
        return list(casesOf(a).map((k) => withOutcome(k, a)), p, { text: (c) => `${c.name} ${c.input}`, value: (c, k) => (k === 'lastOutcome' ? (c.lastOutcome ?? 'not_run') : field(c, k)), facetKeys: ['suite', 'source', 'lastOutcome'] }, m);
      }),
    createCase: (aid, input) =>
      respond(() => {
        agentOr404(aid);
        const err = validateInput(input);
        if (err) throw new ApiError(`${err}.`, 400);
        return addCase(aid, input, 'manual');
      }),
    importCases: (aid, rows, fileId) =>
      respond(() => {
        const a = agentOr404(aid);
        if (fileId) deps.files.link(fileId, { type: 'eval_set', id: aid, name: `${a.name} eval cases`, href: `/agents/${aid}?tab=evals` }, ['test_import']);
        const held = contentOf(a).toolNames;
        return bulk(rows.map((_, i) => String(i)), (i) => {
          const err = validateInput(rows[Number(i)]);
          if (err) return err;
          const unknown = rows[Number(i)].checks.find((c) => (c.type === 'calls_tool' || c.type === 'not_calls_tool') && c.tool && !held.includes(c.tool));
          if (unknown && 'tool' in unknown) return `Unknown tool ${unknown.tool}: the agent doesn’t hold it`;
          addCase(aid, rows[Number(i)], 'csv');
        });
      }),
    caseFromTurn: (aid, { message, turn, runAsId }) =>
      respond(() => {
        const a = agentOr404(aid);
        const checks: EvalCheck[] = [
          ...turn.toolCalls.map((t) => ({ type: 'calls_tool' as const, tool: t.name })),
          ...turn.citations.slice(0, 2).map((c) => ({ type: 'cites' as const, source: a.collections[0] ?? c.source, section: `${c.source} · ${c.section}` })),
        ];
        if (!checks.length) checks.push({ type: 'reply_contains', text: turn.reply.split(/[.!?]/)[0].split(' ').slice(0, 4).join(' ') });
        return addCase(aid, { name: message.length > 60 ? `${message.slice(0, 57)}…` : message, input: message, context: { runAsId, collections: [...a.collections] }, checks }, 'test_turn');
      }),
    removeCase: (cid) =>
      respond(() => {
        const err = removeOwn(cid);
        if (err === 'Not found') notFound('Case');
        if (err) throw new ApiError('Platform cases are read-only. They are maintained by the platform team for every agent.', 403);
      }),
    bulkRemoveCases: (ids) => respond(() => bulk(ids, removeOwn)),
    run: (aid) =>
      respond(() => {
        if (runs.some((r) => r.agentId === aid && settle(r).status === 'running')) throw new ApiError('A run for this agent is already in progress.', 409);
        return publicRun(start(aid, 'manual'));
      }),
    runs: (aid, p) =>
      respond((m) => {
        agentOr404(aid);
        return list(runs.filter((r) => r.agentId === aid).map(row), p, { text: (r) => `${r.id} v${r.draftVersion} ${r.requestedBy}`, value: field, facetKeys: ['status', 'trigger'] }, m);
      }),
    getRun: (rid) => respond(() => publicRun(runs.find((r) => r.id === rid) ?? notFound('Eval run'))),
    latest: (aid) =>
      respond((m) => {
        if (m === 'empty') return null;
        const r = runs.find((x) => x.agentId === aid);
        return r ? publicRun(r) : null;
      }),
    options: (aid) =>
      respond(() => {
        const a = agentOr404(aid);
        const granted = contentOf(a).toolNames;
        return {
          tools: [...granted],
          collections: deps.collections(),
          documents: a.collections.map((c) => ({ collection: c, title: c, sections: [] })),
        };
      }),
  };

  /** Eval result for one agent version: the newest completed run on it. Null while running or never run. */
  const summaryFor = (aid: string, version: number): EvalVersionSummary | null => {
    const r = latestComplete(aid, version);
    if (!r?.summary) return null;
    const inj = r.summary.suites.find((s) => s.kind === 'injection');
    return { runId: r.id, ranAt: r.finishedAt ?? r.startedAt, passed: r.summary.passed, total: r.summary.total, regressions: r.summary.regressions, injection: { passed: inj?.passed ?? 0, total: inj?.total ?? 0, regressions: inj?.regressions ?? 0 } };
  };
  const isRunning = (aid: string, version: number) => runs.some((r) => r.agentId === aid && r.draftVersion === version && settle(r).status === 'running');
  const passRates = (aid: string) => {
    const byVersion = new Map<number, number>();
    for (const r of [...runs].reverse()) if (r.agentId === aid && settle(r).summary) byVersion.set(r.draftVersion, r.summary!.passed / Math.max(1, r.summary!.total));
    return [...byVersion].sort((x, y) => x[0] - y[0]).map(([v, rate]) => ({ version: v, passRate: rate }));
  };

  /** Starts a run after every save or restore, and adds each version's eval result to the history. */
  const wrapAgents = (inner: OpsApi['agents']): OpsApi['agents'] => ({
    ...inner,
    update: async (aid, patch) => {
      const a = await inner.update(aid, patch);
      start(aid, 'save');
      return a;
    },
    restore: async (aid, v) => {
      const a = await inner.restore(aid, v);
      start(aid, 'restore');
      return a;
    },
    versions: async (aid) => (await inner.versions(aid)).map((v: Version) => ({ ...v, evalSummary: summaryFor(aid, v.version) ?? undefined })),
  });

  return { api, wrapAgents, summaryFor, isRunning, passRates };
}

export type EvalsMock = ReturnType<typeof createEvalsMock>;
