import type {
  Connection,
  DocumentRow,
  Item,
  KbHealth,
  KnowledgeBase,
  KnowledgeBaseDetail,
  KnowledgeBaseRow,
  PlaygroundAnswer,
  RetrievalSettings,
  ScoredChunk,
  Source,
  SourceDetail,
  SourceRow,
  SyncRun,
} from '@/lib/types/knowledge';

import { ApiError } from '../../contract';
import type { KnowledgeApi } from '../../knowledge-contract';
import { bulk, id, list, notFound, respond } from '../runtime';
import { guardTeam, inTeam } from '../teams';
import { itemDetail } from './detail';
import { defaultRetrieval, kbs as SEED_KBS, playgroundAnswers, retrievalPresets, suggestedQuestions } from './seed-kbs';
import { buildItems, runs as SEED_RUNS, sources as SEED_SOURCES } from './seed-sources';

const now = () => new Date().toISOString();
const secondsSince = (iso: string) => Math.round((Date.now() - new Date(iso).getTime()) / 1000);
const isStale = (it: Item) => new Date(it.reviewBy).getTime() < Date.now();
const snake = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');

/** One running job advances a step per this many milliseconds, so progress bars move between polls. */
const STEP_MS = 1200;

const CONNECTIONS: Connection[] = [
  { type: 'sharepoint', name: 'SharePoint', status: 'connected', connectedAs: 'northfield.sharepoint.com (app-only)' },
  { type: 'confluence', name: 'Confluence', status: 'needs_reauth', connectedAs: 'northfield.atlassian.net' },
  { type: 'gdrive', name: 'Google Drive', status: 'disconnected' },
  { type: 'github', name: 'GitHub', status: 'connected', connectedAs: 'GitHub app · northfield-bank' },
  { type: 'notion', name: 'Notion', status: 'connected', connectedAs: 'Northfield Product (Notion)' },
  { type: 'zendesk', name: 'Zendesk', status: 'disconnected' },
  { type: 'salesforce', name: 'Salesforce Knowledge', status: 'disconnected' },
];

const OWNERS = ['Financial Crime Ops', 'Compliance', 'Fraud Strategy', 'Fraud Operations', 'Model Risk', 'Card Services', 'Lending Ops', 'Retail Product', 'Branch Network', 'Customer Care', 'James Richardson'];

const STOP = new Set(['what', 'when', 'which', 'where', 'does', 'have', 'with', 'from', 'that', 'this', 'there', 'their', 'about', 'should', 'would', 'could', 'into', 'over', 'under', 'much', 'many', 'long', 'they', 'your', 'ours']);
const terms = (s: string) => new Set(s.toLowerCase().split(/[^a-z0-9$]+/).filter((w) => w.length > 3 && !STOP.has(w)));
const overlap = (q: Set<string>, text: string) => {
  const t = terms(text);
  return [...q].filter((w) => t.has(w)).length;
};

interface Scope {
  /** Sources the knowledge base reads (narrowed by the retrieval scope when one is set). */
  sourceIds: Set<string>;
  /** Searchable documents from those sources. */
  pool: Item[];
  sourceName: (sid: string) => string;
}

const inScope = (scope: Scope, documentId: string) => [...scope.sourceIds].some((sid) => documentId.startsWith(`${sid}_it_`));

/** Term-overlap retrieval over the scoped documents: rank documents by title, path and tags, then take each one's best chunk. */
function searchPool(question: string, scope: Scope): PlaygroundAnswer {
  const q = terms(question);
  const ranked = scope.pool
    .filter((it) => (it.status === 'indexed' || it.status === 'partial') && it.chunkCount > 0)
    .map((it) => ({ it, score: overlap(q, `${it.title} ${it.path} ${it.tags.join(' ')} ${Object.values(it.metadata).join(' ')}`) }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score || a.it.title.localeCompare(b.it.title))
    .slice(0, 5);
  const chunks: ScoredChunk[] = ranked.map(({ it, score }, i) => {
    const detail = itemDetail(it);
    const best = detail.chunks.reduce((b, c) => (overlap(q, c.text) > overlap(q, b.text) ? c : b), detail.chunks[0]);
    // Three matching terms count as a full match; questions carry filler words a title never repeats.
    const s = Math.min(0.95, 0.5 + 0.42 * Math.min(1, score / Math.min(Math.max(q.size, 1), 3)) + (best && overlap(q, best.text) ? 0.03 : 0) - i * 0.02);
    return { chunkId: `c${i + 1}`, documentId: it.id, documentTitle: it.title, sourceName: scope.sourceName(it.sourceId), score: Math.round(s * 100) / 100, location: best?.location ?? '', text: best?.text ?? '', rejected: false, version: it.version };
  });
  const top = chunks.slice(0, 2);
  const answer = top.length
    ? `The closest match is ${top[0].documentTitle} (${top[0].location}) [1]: ${top[0].text.split('. ')[0].replace(/\.$/, '')}.` +
      (top[1] ? ` ${top[1].documentTitle} covers the same point [2]: ${top[1].text.split('. ')[0].replace(/\.$/, '')}.` : '')
    : '';
  return {
    id: 'pa_search',
    question,
    matchers: [],
    answer,
    followed: 'Highest-scoring document after precedence rules',
    citations: top.map((c, i) => ({ n: i + 1, documentId: c.documentId, title: c.documentTitle, section: c.location, version: c.version, snippet: c.text.split('. ')[0] })),
    chunks,
    noAnswer: chunks.length === 0,
    retrievalMs: 320 + chunks.length * 40,
    synthesisMs: 1_400,
  };
}

/**
 * Answers from the knowledge base's own sources only. A canned answer is used when its matchers fit the question
 * and its documents come from those sources; anything else is retrieved by term overlap. Threshold and chunk
 * limit are applied last.
 */
function findAnswer(question: string, settings: RetrievalSettings, scope: Scope): PlaygroundAnswer {
  const q = question.toLowerCase();
  let best: PlaygroundAnswer | undefined;
  let bestScore = 0;
  for (const a of playgroundAnswers) {
    if (!a.noAnswer && !a.chunks.some((c) => inScope(scope, c.documentId))) continue;
    const score = a.matchers.filter((m) => q.includes(m.toLowerCase())).length;
    if (score > bestScore) {
      best = a;
      bestScore = score;
    }
  }
  const base = best ? { ...best, chunks: best.chunks.filter((c) => inScope(scope, c.documentId)), citations: best.citations.filter((c) => inScope(scope, c.documentId)) } : searchPool(question, scope);
  const chunks = base.chunks.map((c) => ({ ...c, rejected: c.score < settings.threshold })).slice(0, Math.max(settings.chunkLimit, 2));
  const accepted = chunks.filter((c) => !c.rejected);
  const noAnswer = !!base.noAnswer || accepted.length === 0;
  return {
    ...base,
    id: `${base.id}_${Date.now().toString(36)}`,
    question,
    chunks,
    noAnswer,
    answer: noAnswer || !settings.synthesis ? '' : base.answer,
    citations: noAnswer ? [] : base.citations.filter((ci) => accepted.some((c) => c.documentId === ci.documentId)),
    synthesisMs: settings.synthesis && !noAnswer ? base.synthesisMs : 0,
  };
}

/**
 * In-memory knowledge backend. Index refreshes and sync runs advance in the background on every request, so a
 * page that polls while a job runs sees it progress and finish.
 *
 * `agentNames` answers which agents cite a knowledge base; agents store the knowledge base name as a collection.
 */
export function createKnowledgeMock(deps: { agentNames: (kbName: string) => string[]; agentOwners: (kbName: string) => string[]; currentUser: string }): { api: KnowledgeApi; kbNames: () => string[] } {
  const kbs: KnowledgeBase[] = structuredClone(SEED_KBS);
  const sources: Source[] = structuredClone(SEED_SOURCES);
  let items: Item[] = buildItems();
  const runs: SyncRun[] = structuredClone(SEED_RUNS);
  const connections: Connection[] = structuredClone(CONNECTIONS);
  let lastTick = Date.now();

  const kbOr404 = (kid: string) => kbs.find((k) => k.id === kid) ?? notFound('Knowledge base');
  const sourceOr404 = (sid: string) => sources.find((s) => s.id === sid) ?? notFound('Source');
  const itemOr404 = (iid: string) => items.find((i) => i.id === iid) ?? notFound('Item');
  /** A knowledge base belongs to the teams that own its sources or the agents citing it. */
  const kbOwners = (k: KnowledgeBase) => [...k.sources.map((l) => sources.find((s) => s.id === l.sourceId)?.owner), ...deps.agentOwners(k.name)];
  const runningRun = (sid: string) => runs.find((r) => r.sourceId === sid && r.status === 'running');

  /** Documents, chunks, stale and failed counts are sums over the documents the knowledge base reads, so the overview and the Documents tab agree. */
  const deriveStats = (k: KnowledgeBase) => {
    const ids = new Set(k.sources.map((l) => l.sourceId));
    const docs = items.filter((it) => ids.has(it.sourceId) && it.status !== 'excluded' && it.status !== 'deleted');
    Object.assign(k.stats, {
      documents: docs.length,
      chunks: docs.reduce((n, it) => n + it.chunkCount, 0),
      stale: docs.filter(isStale).length,
      failures: docs.filter((it) => it.status === 'failed').length,
    });
    return k;
  };
  const kbRow = (k: KnowledgeBase): KnowledgeBaseRow => ({
    ...deriveStats(k),
    sourceNames: k.sources.map((l) => sources.find((s) => s.id === l.sourceId)?.name ?? l.sourceId),
    agentNames: deps.agentNames(k.name),
  });
  // Seeded health reasons quote counts; restate them from the derived numbers.
  for (const k of kbs) {
    deriveStats(k);
    const n = (x: number, one: string, many: string) => `${x} ${x === 1 ? one : many}`;
    k.healthReasons = k.healthReasons
      .map((r) => r.replace(/^\d+ items? failed to parse/, n(k.stats.failures, 'item', 'items') + ' failed to parse').replace(/^\d+ items? older than/, n(k.stats.stale, 'item', 'items') + ' older than'))
      .filter((r) => !/^0 items (failed|older)/.test(r));
  }
  const sourceRow = (s: Source): SourceRow => ({
    ...s,
    usedBy: kbs.filter((k) => k.sources.some((l) => l.sourceId === s.id)).map((k) => ({ id: k.id, name: k.name })),
    running: !!runningRun(s.id),
  });
  const accessOf = (k: KnowledgeBase) =>
    [k.access.members.mode === 'all' ? 'members' : 'selected', k.access.anyApiKey ? 'api' : '', k.access.mcp.enabled ? 'mcp' : '', k.access.publicLink.enabled ? 'public' : ''].filter(Boolean);

  // ---- background jobs ------------------------------------------------------

  function step() {
    for (const k of kbs) {
      if (!k.indexing) continue;
      const done = Math.min(k.indexing.total, k.indexing.done + Math.max(1, Math.ceil(k.indexing.total / 14)));
      const job = k.jobs[0]?.status === 'running' ? k.jobs[0] : undefined;
      if (done < k.indexing.total) {
        k.indexing.done = done;
        k.healthReasons = [`Index refresh running: ${done} of ${k.indexing.total} items`];
        if (job) job.processed = done;
        continue;
      }
      const failures = k.stats.failures;
      const health: KbHealth = failures > 0 || k.stats.stale > k.stats.documents * 0.1 ? 'degraded' : 'healthy';
      if (job) Object.assign(job, { status: failures > 0 ? 'partial' : 'success', processed: k.indexing.total, failed: failures, durationSec: secondsSince(job.startedAt) });
      k.indexing = undefined;
      k.health = health;
      k.healthReasons =
        health === 'healthy'
          ? ['Last refresh succeeded just now', 'No failed or stale items']
          : [failures > 0 ? `${failures} items failed to parse` : '', k.stats.stale > 0 ? `${k.stats.stale} items older than the freshness threshold` : ''].filter(Boolean);
      k.lastRefreshedAt = now();
      k.stats.chunks = k.stats.chunks || Math.round(k.stats.documents * 15.4);
    }

    for (const r of runs) {
      if (r.status !== 'running' || !r.progress) continue;
      const total = r.progress.total;
      const done = Math.min(total, r.progress.done + Math.max(1, Math.ceil(total / 12)));
      const phaseIdx = Math.min(5, Math.floor((done / total) * 6));
      r.phases = r.phases.map((p, i) => ({ ...p, status: i < phaseIdx ? 'done' : i === phaseIdx ? 'running' : 'skipped', durationMs: i <= phaseIdx ? p.durationMs + 900 : 0 }));
      r.log.push(`${now().slice(11, 19)} ${r.phases[phaseIdx].name}: ${done} of ${total} items`);
      const pending = items.filter((it) => it.sourceId === r.sourceId && (it.status === 'pending' || it.status === 'processing'));
      if (done < total) {
        r.progress.done = done;
        const n = Math.ceil((done / total) * pending.length);
        pending.slice(0, n).forEach((it) => (it.status = 'processing'));
        continue;
      }
      // A manual run over freshly added items fails one of them, so the retry path is reachable in the demo.
      const failedItem = r.trigger === 'manual' && pending.length >= 3 && !r.errors.length ? pending[pending.length - 1] : undefined;
      for (const it of items) {
        if (it.sourceId !== r.sourceId) continue;
        if (failedItem && it.id === failedItem.id) Object.assign(it, { status: 'failed', errorClass: 'parse', error: 'PDF is encrypted; upload an unlocked copy', chunkCount: 0, processedAt: now() });
        else if (it.status === 'pending' || it.status === 'processing') Object.assign(it, { status: 'indexed', chunkCount: it.chunkCount || 6 + Math.floor(Math.random() * 20), processedAt: now(), error: undefined, errorClass: undefined });
        else if (r.trigger === 'retry' && it.status === 'failed') Object.assign(it, { status: 'indexed', chunkCount: 6, processedAt: now(), error: undefined, errorClass: undefined });
      }
      const srcItems = items.filter((it) => it.sourceId === r.sourceId);
      const failed = srcItems.filter((it) => it.status === 'failed').length;
      const indexed = srcItems.filter((it) => it.status === 'indexed').length;
      const status = failed > 0 ? 'partial' : 'success';
      const src = sources.find((x) => x.id === r.sourceId);
      if (src) Object.assign(src, { itemsIndexed: indexed || src.itemsIndexed, itemsFailed: failed, itemsPending: 0, lastSyncAt: now(), lastRunStatus: status, lastRunDurationSec: secondsSince(r.startedAt), cursor: `cursor:${Date.now().toString(36)}` });
      Object.assign(r, {
        status,
        progress: undefined,
        durationSec: secondsSince(r.startedAt),
        cursorAfter: `cursor:${Date.now().toString(36)}`,
        counts: { ...r.counts, listed: r.counts.listed || total, upserted: done - (failedItem ? 1 : 0), failed: failedItem ? 1 : r.trigger === 'retry' ? 0 : failed },
        phases: r.phases.map((p) => ({ ...p, status: 'done' })),
        errors: failedItem ? [{ itemId: failedItem.id, itemTitle: failedItem.title, phase: 'parse', errorClass: 'parse', message: 'PDF is encrypted; upload an unlocked copy' }] : r.trigger === 'retry' ? [] : r.errors,
      });
      r.log.push(`done: ${status}`);
    }

    // Items reprocessed outside a run finish on their own.
    for (const it of items) if (it.status === 'processing' && !runningRun(it.sourceId)) Object.assign(it, { status: 'indexed', chunkCount: it.chunkCount || 8, processedAt: now() });
  }

  /** Catches background jobs up with the wall clock before every read or write. */
  function advance() {
    const steps = Math.min(20, Math.floor((Date.now() - lastTick) / STEP_MS));
    if (steps > 0) lastTick += steps * STEP_MS;
    for (let i = 0; i < steps; i++) step();
  }

  const run = <T,>(fn: Parameters<typeof respond<T>>[0]) =>
    respond<T>((m) => {
      advance();
      return fn(m);
    });

  // ---- actions shared by single and bulk endpoints ------------------------

  function startRefresh(k: KnowledgeBase, trigger = 'manual refresh') {
    k.health = 'indexing';
    k.healthReasons = [`Index refresh running: 0 of ${k.stats.documents} items`];
    k.indexing = { done: 0, total: Math.max(k.stats.documents, 1), taskId: id('task') };
    k.jobs.unshift({ id: id('job'), startedAt: now(), durationSec: 0, processed: 0, failed: 0, status: 'running', trigger });
  }

  function startSync(src: Source, opts: { full?: boolean; retry?: boolean } = {}): SyncRun {
    const total = opts.retry
      ? Math.max(src.itemsFailed, 1)
      : opts.full
        ? Math.max(src.itemsIndexed + src.itemsFailed, 12)
        : Math.max(Math.round((src.itemsIndexed + src.itemsFailed) * 0.06), src.itemsIndexed === 0 ? 12 : 4);
    const r: SyncRun = {
      id: id('run'),
      sourceId: src.id,
      trigger: opts.retry ? 'retry' : opts.full ? 'full' : 'manual',
      startedAt: now(),
      durationSec: 0,
      status: 'running',
      cursorBefore: src.cursor,
      counts: { listed: src.itemsIndexed + src.itemsFailed || total, unchanged: 0, upserted: 0, deleted: 0, failed: 0, skipped: 0 },
      phases: (['list', 'fetch', 'parse', 'chunk', 'embed', 'upsert'] as const).map((name, i) => ({ name, durationMs: 0, status: i === 0 ? 'running' : 'skipped' })),
      errors: [],
      log: [`${now().slice(11, 19)} list: starting ${opts.full ? 'full' : 'incremental'} listing`],
      progress: { done: 0, total, failed: 0 },
    };
    runs.unshift(r);
    Object.assign(src, { status: src.status === 'draft' ? 'active' : src.status, lastRunStatus: 'running', reprocessPending: false });
    return r;
  }

  const syncBlocker = (src: Source) => (src.status === 'revoked' ? 'Connection revoked' : runningRun(src.id) ? 'Already syncing' : undefined);

  function removeKb(kid: string) {
    const i = kbs.findIndex((k) => k.id === kid);
    if (i < 0) return false;
    kbs.splice(i, 1);
    sources.forEach((s) => (s.usedByKbIds = s.usedByKbIds.filter((x) => x !== kid)));
    return true;
  }

  function removeSource(sid: string) {
    const i = sources.findIndex((s) => s.id === sid);
    if (i < 0) return false;
    sources.splice(i, 1);
    items = items.filter((it) => it.sourceId !== sid);
    for (let j = runs.length - 1; j >= 0; j--) if (runs[j].sourceId === sid) runs.splice(j, 1);
    kbs.forEach((k) => (k.sources = k.sources.filter((l) => l.sourceId !== sid)));
    return true;
  }

  function attach(k: KnowledgeBase, sid: string) {
    const src = sourceOr404(sid);
    if (k.sources.some((l) => l.sourceId === sid)) return;
    k.sources.push({ sourceId: sid, itemsContributed: src.itemsIndexed, rules: [] });
    k.stats.documents += src.itemsIndexed;
    src.usedByKbIds = Array.from(new Set([...src.usedByKbIds, k.id]));
  }

  const api: KnowledgeApi = {
    kbs: {
      list: (p) =>
        run((m) =>
          list(kbs.filter((k) => inTeam(kbOwners(k))).map(kbRow), p, {
            text: (k) => `${k.name} ${k.description} ${k.slug}`,
            value: (k, key) => (key === 'access' ? accessOf(k) : String((k as unknown as Record<string, unknown>)[key])),
            facetKeys: ['health', 'access'],
          }, m),
        ),
      get: (kid) =>
        run((): KnowledgeBaseDetail => {
          const k = kbOr404(kid);
          guardTeam(kbOwners(k), 'knowledge base');
          const ids = new Set(k.sources.map((l) => l.sourceId));
          return {
            ...kbRow(k),
            attached: k.sources.flatMap((l) => {
              const source = sources.find((s) => s.id === l.sourceId);
              return source ? [{ ...l, source }] : [];
            }),
            metadataKeys: Array.from(new Set(items.filter((i) => ids.has(i.sourceId)).flatMap((i) => Object.keys(i.metadata)))),
            suggestedQuestions: suggestedQuestions[k.id] ?? suggestedQuestions.kb_all,
          };
        }),
      create: (input) =>
        run(() => {
          if (kbs.some((k) => k.name.trim().toLowerCase() === input.name.trim().toLowerCase())) throw new ApiError('A knowledge base with this name already exists.', 409);
          const srcs = sources.filter((s) => input.sourceIds.includes(s.id));
          const documents = srcs.reduce((n, s) => n + s.itemsIndexed, 0);
          const slug = snake(input.name);
          const k: KnowledgeBase = {
            id: id('kb'),
            name: input.name,
            slug,
            description: input.description,
            color: input.color,
            sources: srcs.map((s) => ({ sourceId: s.id, itemsContributed: s.itemsIndexed, rules: [] })),
            collections: input.collections.length ? input.collections : Array.from(new Set(srcs.map((s) => s.collection))),
            precedence: [{ id: 'p1', label: 'Newer effective date beats older', winner: 'Newer version', loser: 'Superseded version' }],
            retrieval: { ...defaultRetrieval, ...retrievalPresets[input.preset] },
            access: {
              members: { mode: 'all', principals: [] },
              anyApiKey: false,
              mcp: { enabled: true, toolName: `search_${slug}` },
              publicLink: { enabled: false, slug: slug.replace(/_/g, '-'), answerStyle: 'chat', rateLimit: 300, showSourceLinks: true },
              documentPermissions: srcs.some((s) => s.permissions.mode !== 'workspace') ? 'respect' : 'workspace',
            },
            automation: 'suggest',
            stats: { documents, chunks: 0, failures: 0, stale: 0, queries7d: 0, queriesChange7d: 0, noAnswerRate: 0, medianLatencyMs: 0 },
            health: 'never',
            healthReasons: ['Never indexed'],
            jobs: [],
            createdAt: now(),
          };
          if (documents > 0) startRefresh(k, 'initial build');
          kbs.unshift(k);
          srcs.forEach((s) => s.usedByKbIds.push(k.id));
          return k;
        }),
      update: (kid, patch) =>
        run(() => {
          const k = kbOr404(kid);
          const { retrieval, ...rest } = patch;
          if (rest.name && kbs.some((x) => x.id !== kid && x.name.toLowerCase() === rest.name!.toLowerCase())) throw new ApiError('A knowledge base with this name already exists.', 409);
          Object.assign(k, rest);
          if (retrieval) k.retrieval = { ...k.retrieval, ...retrieval };
          return k;
        }),
      remove: (kid) =>
        run(() => {
          if (!removeKb(kid)) notFound('Knowledge base');
        }),
      duplicate: (kid) =>
        run(() => {
          const src = kbOr404(kid);
          const copy: KnowledgeBase = {
            ...structuredClone(src),
            id: id('kb'),
            name: `${src.name} (copy)`,
            slug: `${src.slug}_copy`,
            stats: { ...src.stats, chunks: 0, queries7d: 0, queriesChange7d: 0 },
            health: 'never',
            healthReasons: ['Never indexed; settings and source links copied'],
            indexing: undefined,
            jobs: [],
            lastRefreshedAt: undefined,
            createdAt: now(),
          };
          copy.access.mcp.toolName = `${src.access.mcp.toolName}_copy`;
          copy.access.publicLink = { ...copy.access.publicLink, enabled: false, slug: `${src.access.publicLink.slug}-copy` };
          kbs.unshift(copy);
          copy.sources.forEach((l) => sources.find((s) => s.id === l.sourceId)?.usedByKbIds.push(copy.id));
          return copy;
        }),
      refresh: (kid) =>
        run(() => {
          const k = kbOr404(kid);
          if (k.indexing) throw new ApiError('A refresh is already running.', 409);
          startRefresh(k);
          return k;
        }),
      cancelJob: (kid) =>
        run(() => {
          const k = kbOr404(kid);
          if (!k.indexing) return k;
          k.indexing = undefined;
          k.health = 'degraded';
          k.healthReasons = ['Last index refresh was cancelled'];
          const job = k.jobs[0];
          if (job?.status === 'running') Object.assign(job, { status: 'failed', trigger: `${job.trigger} (cancelled)`, durationSec: secondsSince(job.startedAt) });
          return k;
        }),
      retryFailed: (kid) =>
        run(() => {
          const k = kbOr404(kid);
          const ids = new Set(k.sources.map((l) => l.sourceId));
          items.forEach((it) => {
            if (it.status === 'failed' && ids.has(it.sourceId)) Object.assign(it, { status: 'indexed', error: undefined, errorClass: undefined, chunkCount: 6 });
          });
          k.stats.failures = 0;
          k.health = k.stats.stale > k.stats.documents * 0.1 ? 'degraded' : 'healthy';
          k.healthReasons = k.stats.stale > 0 ? [`${k.stats.stale} items older than the freshness threshold`] : ['Last refresh succeeded and no failed items'];
          return k;
        }),
      attachSources: (kid, sourceIds) =>
        run(() => {
          const k = kbOr404(kid);
          sourceIds.forEach((sid) => attach(k, sid));
          return k;
        }),
      detachSource: (kid, sid) =>
        run(() => {
          const k = kbOr404(kid);
          const link = k.sources.find((l) => l.sourceId === sid);
          if (!link) notFound('Attached source');
          if (k.sources.length === 1 && k.access.publicLink.enabled) throw new ApiError('A knowledge base with a public link must keep at least one source.', 409);
          k.sources = k.sources.filter((l) => l.sourceId !== sid);
          k.stats.documents = Math.max(0, k.stats.documents - link!.itemsContributed);
          const src = sources.find((s) => s.id === sid);
          if (src) src.usedByKbIds = src.usedByKbIds.filter((x) => x !== kid);
          return k;
        }),
      setSourceRules: (kid, sid, rules) =>
        run(() => {
          const k = kbOr404(kid);
          const link = k.sources.find((l) => l.sourceId === sid) ?? notFound('Attached source');
          link.rules = rules;
          return k;
        }),
      documents: (kid, p) =>
        run((m) => {
          const k = kbOr404(kid);
          const ids = new Set(k.sources.map((l) => l.sourceId));
          const rows: DocumentRow[] = items
            .filter((it) => ids.has(it.sourceId) && it.status !== 'excluded')
            .map((it) => ({ ...it, sourceName: sources.find((s) => s.id === it.sourceId)?.name ?? it.sourceId, freshness: isStale(it) ? 'stale' : 'fresh' }));
          return list(rows, p, {
            text: (d) => `${d.title} ${d.path}`,
            value: (d, key) => (key === 'tags' ? d.tags : String((d as unknown as Record<string, unknown>)[key])),
            facetKeys: ['sourceId', 'status', 'freshness', 'sensitivity', 'tags'],
          }, m);
        }),
      query: (kid, input) =>
        run(() => {
          const k = kbOr404(kid);
          const scoped = input.settings.scopeSourceIds?.length ? k.sources.filter((l) => input.settings.scopeSourceIds.includes(l.sourceId)) : k.sources;
          const sourceIds = new Set(scoped.map((l) => l.sourceId));
          return findAnswer(input.question, input.settings, {
            sourceIds,
            pool: items.filter((it) => sourceIds.has(it.sourceId)),
            sourceName: (sid) => sources.find((s) => s.id === sid)?.name ?? sid,
          });
        }),
      bulkRefresh: (ids) =>
        run(() =>
          bulk(ids, (kid) => {
            const k = kbs.find((x) => x.id === kid);
            if (!k) return 'Not found';
            if (k.indexing) return 'Already refreshing';
            if (!k.sources.length) return 'Reads no sources';
            startRefresh(k);
          }),
        ),
      bulkRemove: (ids) =>
        run(() =>
          bulk(ids, (kid) => {
            const k = kbs.find((x) => x.id === kid);
            if (!k) return 'Not found';
            const agents = deps.agentNames(k.name);
            if (agents.length) return `Cited by ${agents.length === 1 ? 'an agent' : `${agents.length} agents`}`;
            removeKb(kid);
          }),
        ),
    },

    sources: {
      list: (p) =>
        run((m) => {
          // Revoked and failed first, then partial, then the rest in seed order.
          const rank = (s: Source) => (s.status === 'revoked' || s.lastRunStatus === 'failed' ? 0 : s.lastRunStatus === 'partial' ? 1 : 2);
          const rows = sources.filter((s) => inTeam(s.owner)).sort((a, b) => rank(a) - rank(b)).map(sourceRow);
          return list(rows, p, {
            text: (s) => `${s.name} ${s.connectionLabel ?? ''} ${s.scopeSummary}`,
            value: (s, key) => (key === 'usedBy' ? s.usedBy.map((u) => u.id) : key === 'schedule' ? s.schedule.kind : String((s as unknown as Record<string, unknown>)[key])),
            facetKeys: ['type', 'status', 'schedule', 'usedBy'],
          }, m);
        }),
      get: (sid) =>
        run((): SourceDetail => {
          const s = sourceOr404(sid);
          guardTeam(s.owner, 'source');
          const srcRuns = runs.filter((r) => r.sourceId === sid).sort((a, b) => b.startedAt.localeCompare(a.startedAt));
          const groups = new Map<string, number>();
          items.forEach((i) => {
            if (i.sourceId === sid && i.status === 'failed') groups.set(i.error ?? 'Unknown error', (groups.get(i.error ?? 'Unknown error') ?? 0) + 1);
          });
          return {
            ...s,
            readers: kbs.filter((k) => k.sources.some((l) => l.sourceId === sid)).map(({ id: kid, name, slug, color, health }) => ({ id: kid, name, slug, color, health })),
            running: runningRun(sid),
            recentRuns: srcRuns.slice(0, 5),
            errorGroups: [...groups.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([message, count]) => ({ message, count })),
            itemCount: items.filter((i) => i.sourceId === sid).length,
          };
        }),
      create: (input, opts) =>
        run(() => {
          if (sources.some((s) => s.name.trim().toLowerCase() === input.name.trim().toLowerCase())) throw new ApiError('A source with this name already exists.', 409);
          const conn = connections.find((c) => c.type === input.type);
          const s: Source = {
            ...input,
            id: id('src'),
            connectionId: conn ? `int_${conn.type}` : undefined,
            connectionLabel: conn?.connectedAs,
            owner: deps.currentUser,
            status: input.status ?? 'active',
            itemsIndexed: 0,
            itemsFailed: 0,
            itemsPending: input.itemsPending ?? 0,
            usedByKbIds: [],
            createdAt: now(),
          };
          sources.unshift(s);
          opts?.kbIds?.forEach((kid) => {
            const k = kbs.find((x) => x.id === kid);
            if (k) attach(k, s.id);
          });
          if (opts?.sync && s.status !== 'draft') startSync(s);
          return s;
        }),
      update: (sid, patch) =>
        run(() => {
          const s = sourceOr404(sid);
          if (patch.name && sources.some((x) => x.id !== sid && x.name.toLowerCase() === patch.name!.toLowerCase())) throw new ApiError('A source with this name already exists.', 409);
          Object.assign(s, patch);
          return s;
        }),
      remove: (sid) =>
        run(() => {
          if (!removeSource(sid)) notFound('Source');
        }),
      sync: (sid, opts) =>
        run(() => {
          const s = sourceOr404(sid);
          const blocked = syncBlocker(s);
          if (blocked) throw new ApiError(blocked, 409);
          return startSync(s, opts);
        }),
      cancelRun: (sid) =>
        run(() => {
          const r = runningRun(sid);
          if (!r) return;
          Object.assign(r, { status: 'failed', progress: undefined, durationSec: secondsSince(r.startedAt) });
          r.log.push('cancelled by user');
          const s = sources.find((x) => x.id === sid);
          if (s) s.lastRunStatus = 'failed';
        }),
      setPaused: (sid, paused) =>
        run(() => {
          const s = sourceOr404(sid);
          if (s.status === 'draft' || s.status === 'revoked') throw new ApiError(`A ${s.status === 'draft' ? 'draft' : 'revoked'} source has no schedule to ${paused ? 'pause' : 'resume'}.`, 409);
          s.status = paused ? 'paused' : 'active';
          return s;
        }),
      reprocess: (sid) =>
        run(() => {
          const s = sourceOr404(sid);
          const blocked = syncBlocker(s);
          if (blocked) throw new ApiError(blocked, 409);
          return startSync(s, { full: true });
        }),
      items: (sid, p) =>
        run((m) => {
          sourceOr404(sid);
          return list(items.filter((i) => i.sourceId === sid), p, {
            text: (i) => `${i.title} ${i.path} ${i.url ?? ''}`,
            value: (i, key) => (key === 'mime' ? i.mimeType : key === 'errorClass' ? (i.errorClass ?? 'none') : String((i as unknown as Record<string, unknown>)[key])),
            facetKeys: ['status', 'mime', 'errorClass'],
          }, m);
        }),
      runs: (sid, p) =>
        run((m) => {
          sourceOr404(sid);
          const rows = runs.filter((r) => r.sourceId === sid).sort((a, b) => b.startedAt.localeCompare(a.startedAt));
          return list(rows, p, { text: (r) => r.id, value: (r, key) => String((r as unknown as Record<string, unknown>)[key]), facetKeys: ['status', 'trigger'] }, m);
        }),
      run: (rid) => run(() => runs.find((r) => r.id === rid) ?? notFound('Sync run')),
      preview: (input) =>
        run(() => {
          const c = input.config as { startUrl?: string; urls?: string; fileNames?: string[]; scopeCount?: number };
          if (input.type === 'crawl' && /\/\/(10\.|192\.168\.|127\.)/.test(c.startUrl ?? '')) {
            return { ok: false, message: 'URL resolves to a private IP range. Crawls must target a public host.', rows: [] };
          }
          const urls = (c.urls ?? '').split('\n').map((u) => u.trim()).filter(Boolean);
          const n = input.type === 'file' ? (c.fileNames?.length ?? 0) : input.type === 'url' ? urls.length : input.type === 'crawl' ? 24 : input.type === 'text' ? 1 : Math.min(c.scopeCount ?? 0, 50);
          const pick = <T,>(xs: T[], i: number) => xs[i % xs.length];
          const rows = Array.from({ length: n }, (_, i) => ({
            title:
              input.type === 'file' ? c.fileNames![i]
              : input.type === 'url' ? urls[i]
              : input.type === 'crawl' ? `Pricing · ${pick(['overview', 'chequing', 'savings', 'mortgages', 'fees'], i)}`
              : input.type === 'sharepoint' ? pick(['Customer due diligence standard', 'Sanctions screening procedure', 'Suspicious transaction reporting', 'Beneficial ownership verification', 'Risk rating methodology'], i)
              : `${input.type} item ${i + 1}`,
            path: input.type === 'sharepoint' ? `Documents/${i % 7 === 3 ? 'Archive' : 'Policies'}/file-${i}.pdf` : input.type === 'crawl' ? `/pricing/${pick(['', 'chequing', 'savings', 'mortgages', 'fees'], i)}` : `item-${i}`,
            size: 20_000 + ((i * 7919) % 900_000),
            modified: new Date(Date.now() - i * 3 * 86400_000).toISOString().slice(0, 10),
          }));
          return { ok: true, message: `Connection OK · ${n} item${n === 1 ? '' : 's'} would be fetched`, rows };
        }),
      connections: () => run(() => connections),
      connect: (type) =>
        run(() => {
          const c = connections.find((x) => x.type === type) ?? notFound('Connection');
          c.status = 'connected';
          c.connectedAs = c.connectedAs ?? `${c.name} · Northfield Bank`;
          sources.filter((s) => s.type === type && s.status === 'revoked').forEach((s) => (s.status = 'active'));
          return c;
        }),
      bulkSync: (ids) =>
        run(() =>
          bulk(ids, (sid) => {
            const s = sources.find((x) => x.id === sid);
            if (!s) return 'Not found';
            if (s.status === 'draft') return 'Draft, finish setting it up first';
            const blocked = syncBlocker(s);
            if (blocked) return blocked;
            startSync(s);
          }),
        ),
      bulkSetPaused: (ids, paused) =>
        run(() =>
          bulk(ids, (sid) => {
            const s = sources.find((x) => x.id === sid);
            if (!s) return 'Not found';
            if (s.status === 'draft') return 'Draft has no schedule';
            if (s.status === 'revoked') return 'Connection revoked';
            if (s.status === (paused ? 'paused' : 'active')) return paused ? 'Already paused' : 'Already running on schedule';
            s.status = paused ? 'paused' : 'active';
          }),
        ),
      bulkRemove: (ids) => run(() => bulk(ids, (sid) => (removeSource(sid) ? undefined : 'Not found'))),
    },

    items: {
      get: (iid) =>
        run(() => {
          const it = itemOr404(iid);
          const src = sources.find((s) => s.id === it.sourceId);
          return { ...it, sourceName: src?.name ?? it.sourceId, sourceType: src?.type ?? 'file', detail: itemDetail(it) };
        }),
      reprocess: (ids) =>
        run(() =>
          bulk(ids, (iid) => {
            const it = items.find((x) => x.id === iid);
            if (!it) return 'Not found';
            if (it.status === 'excluded' || it.status === 'deleted') return it.status === 'excluded' ? 'Excluded' : 'Deleted at source';
            Object.assign(it, { status: 'processing', error: undefined, errorClass: undefined, processedAt: now() });
          }),
        ),
      exclude: (ids) =>
        run(() =>
          bulk(ids, (iid) => {
            const it = items.find((x) => x.id === iid);
            if (!it) return 'Not found';
            if (it.status === 'excluded') return 'Already excluded';
            const src = sources.find((s) => s.id === it.sourceId);
            if (src) {
              src.rules.push({ id: id('rule'), kind: 'exclude', field: 'path', value: it.path });
              if (it.status === 'indexed') src.itemsIndexed = Math.max(0, src.itemsIndexed - 1);
              if (it.status === 'failed') src.itemsFailed = Math.max(0, src.itemsFailed - 1);
            }
            Object.assign(it, { status: 'excluded', chunkCount: 0 });
          }),
        ),
      verify: (iid, verified) =>
        run(() => {
          const it = itemOr404(iid);
          it.verified = verified;
          if (verified) it.reviewBy = new Date(Date.now() + 90 * 86400_000).toISOString().slice(0, 10);
          return it;
        }),
      setTags: (iid, tags) =>
        run(() => {
          const it = itemOr404(iid);
          it.tags = tags;
          return it;
        }),
      setOwner: (iid, owner) =>
        run(() => {
          const it = itemOr404(iid);
          it.owner = owner;
          return it;
        }),
      addTag: (ids, tag) =>
        run(() =>
          bulk(ids, (iid) => {
            const it = items.find((x) => x.id === iid);
            if (!it) return 'Not found';
            if (it.tags.includes(tag)) return `Already tagged ${tag}`;
            it.tags = [...it.tags, tag];
          }),
        ),
    },

    lookups: () =>
      run(() => ({
        owners: OWNERS,
        tags: Array.from(new Set(sources.flatMap((s) => s.tags))).sort(),
        collections: Array.from(new Set(sources.map((s) => s.collection))).sort(),
      })),
  };

  return { api, kbNames: () => kbs.map((k) => k.name) };
}
