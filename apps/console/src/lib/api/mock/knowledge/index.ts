import type {
  DocumentRow,
  Item,
  KbHealth,
  KnowledgeBase,
  KnowledgeBaseDetail,
  KnowledgeBaseRow,
  PlaygroundAnswer,
  RetrieveInput,
  Source,
  SourceDetail,
  SourceInput,
  SourceRow,
  SyncRun,
} from '@/lib/types/knowledge';
import type { IngestSettings, ItemVersionRow } from '@/lib/types/knowledge-ingest';
import type { ConnectionRef } from '@/lib/types/integrations';

import { ApiError } from '../../contract';
import type { KnowledgeApi } from '../../knowledge-contract';
import type { FileLinks } from '../files';
import { bulk, id, list, notFound, respond } from '../runtime';
import { guardTeam, inTeam } from '../teams';
import { itemDetail } from './detail';
import { aiApproved, aiSteps, applyMapping, chunkCountFor, govern, listSamples, previewSplit, settingsDigest, snakeKey, validateIngest } from './ingest';
import { createRetrieval, type IndexSnapshot } from './retrieve';
import { defaultRetrieval, kbs as SEED_KBS, retrievalPresets, suggestedQuestions } from './seed-kbs';
import { buildItems, runs as SEED_RUNS, sources as SEED_SOURCES } from './seed-sources';

const now = () => new Date().toISOString();
const secondsSince = (iso: string) => Math.round((Date.now() - new Date(iso).getTime()) / 1000);
const isStale = (it: Item) => new Date(it.reviewBy).getTime() < Date.now();
const snake = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');

/** One running job advances a step per this many milliseconds, so progress bars move between polls. */
const STEP_MS = 1200;

const OWNERS = ['Financial Crime Ops', 'Compliance', 'Fraud Strategy', 'Fraud Operations', 'Model Risk', 'Card Services', 'Lending Ops', 'Retail Product', 'Branch Network', 'Customer Care', 'James Richardson'];

/**
 * In-memory knowledge backend. Index refreshes and sync runs advance in the background on every request, so a
 * page that polls while a job runs sees it progress and finish.
 *
 * `agentNames` answers which agents cite a knowledge base; agents store the knowledge base name as a collection.
 */
export function createKnowledgeMock(deps: { agentNames: (kbName: string) => string[]; agentOwners: (kbName: string) => string[]; currentUser: string; connection: (id?: string) => ConnectionRef | undefined; files: () => FileLinks }): {
  api: KnowledgeApi;
  /** Sources reading through a connection, for its Used by tab. */
  sourcesUsing: (connId: string) => Source[];
  /** A revoke stops the connection's sources; a reconnect resumes them. */
  reflectConnection: (connId: string, revoked: boolean) => void;
  kbNames: () => string[];
  /** Synchronous search, for seeding chat threads with real answers and traces. */
  retrieveNow: (input: RetrieveInput) => PlaygroundAnswer;
} {
  const kbs: KnowledgeBase[] = structuredClone(SEED_KBS);
  const sources: Source[] = structuredClone(SEED_SOURCES);
  let items: Item[] = buildItems();
  const runs: SyncRun[] = structuredClone(SEED_RUNS);
  let lastTick = Date.now();

  // What each source's chunks were last built with. Search and the item page read this, so a saved strategy
  // change shows as "re-index needed" until a sync rebuilds the chunks.
  const snapshots = new Map<string, IndexSnapshot>();
  const reindexed = (src: Source) => {
    const snap: IndexSnapshot = { ingest: structuredClone(src.ingest), parsing: { ...src.parsing }, aiAllowed: aiApproved(src), digest: settingsDigest(src) };
    snapshots.set(src.id, snap);
    src.indexedSettingsDigest = snap.digest;
  };
  for (const src of sources) {
    reindexed(src);
    for (const it of items) if (it.sourceId === src.id && it.status !== 'failed') it.chunkCount = chunkCountFor(it, src);
  }
  govern(items, sources, kbs);
  const engine = createRetrieval({ items: () => items, sources: () => sources, kbs: () => kbs, snapshot: (sid) => snapshots.get(sid) });
  const regovern = () => govern(items, sources, kbs);

  /** The knowledge owner approves AI ingest steps; adding a step after approval asks again. */
  const reconcileApproval = (src: Source, previous: IngestSettings['approval']) => {
    const steps = aiSteps(src.ingest, src.metadataMapping);
    const approvedSteps = previous.approvedSteps;
    if (!steps.length) src.ingest.approval = { ...previous, status: 'not_needed' };
    else if (steps.every((x) => approvedSteps.includes(x))) src.ingest.approval = { ...previous, status: 'approved' };
    else src.ingest.approval = { status: 'pending', approvedSteps, requestedBy: deps.currentUser };
  };

  /** The requester cannot approve their own AI step (spec 5.14.13); approving runs the steps on every item at the next re-index. */
  const selfApproval = (src: Source) => src.ingest.approval.requestedBy === deps.currentUser;
  const approvalView = (src: Source) => {
    const waiting = aiSteps(src.ingest, src.metadataMapping).filter((x) => !src.ingest.approval.approvedSteps.includes(x));
    // A draft has no items yet, so its estimate uses what the scope would fetch.
    const n = items.filter((i) => i.sourceId === src.id && i.status !== 'excluded' && i.status !== 'failed').length || src.itemsPending;
    // About six sections per document; FAQ and topic call the model once per section, extraction once per item.
    const calls = waiting.reduce((t, x) => t + (x.startsWith('extract ') ? n : n * 6), 0);
    return {
      canApprove: !selfApproval(src),
      blockedReason: selfApproval(src) ? 'You requested this change; another knowledge owner must approve.' : undefined,
      modelCalls: calls,
      estimatedCost: `$${(calls * 0.0021).toFixed(2)}`,
      items: n,
    };
  };

  /** What a source with this type and config would fetch; the preview and the held preview read the same rows. */
  const previewRows = (input: Pick<SourceInput, 'type' | 'config'>) => {
    const c = input.config as { startUrl?: string; urls?: string; fileNames?: string[]; scopeCount?: number };
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
    return rows;
  };

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
    connection: deps.connection(s.connectionId),
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
        k.healthReasons = [`Index refresh running: ${done} of ${k.indexing.total} ${k.indexing.total === 1 ? 'item' : 'items'}`];
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
      r.log.push(`${now().slice(11, 19)} ${r.phases[phaseIdx].name}: ${done} of ${total} ${total === 1 ? 'item' : 'items'}`);
      const pending = items.filter((it) => it.sourceId === r.sourceId && (it.status === 'pending' || it.status === 'processing'));
      if (done < total) {
        r.progress.done = done;
        const n = Math.ceil((done / total) * pending.length);
        pending.slice(0, n).forEach((it) => (it.status = 'processing'));
        continue;
      }
      // A manual run over freshly added items fails one of them, so the retry path is reachable in the demo.
      const failedItem = r.trigger === 'manual' && pending.length >= 3 && !r.errors.length ? pending[pending.length - 1] : undefined;
      const src0 = sources.find((x) => x.id === r.sourceId);
      // Every run re-chunks what it touches with the source's current settings; a full run touches everything.
      for (const it of items) {
        if (it.sourceId !== r.sourceId) continue;
        const touched = it.status === 'pending' || it.status === 'processing' || r.trigger === 'full' || (r.trigger === 'retry' && it.status === 'failed');
        if (src0 && touched && it.status !== 'excluded') applyMapping(it, src0, aiApproved(src0));
        const chunkCount = src0 ? chunkCountFor(it, src0) : it.chunkCount;
        if (failedItem && it.id === failedItem.id) Object.assign(it, { status: 'failed', errorClass: 'parse', error: 'PDF is encrypted; upload an unlocked copy', chunkCount: 0, processedAt: now() });
        else if (it.status === 'pending' || it.status === 'processing') Object.assign(it, { status: 'indexed', chunkCount, processedAt: now(), error: undefined, errorClass: undefined });
        else if (r.trigger === 'retry' && it.status === 'failed') Object.assign(it, { status: 'indexed', chunkCount, processedAt: now(), error: undefined, errorClass: undefined });
        else if (r.trigger === 'full' && (it.status === 'indexed' || it.status === 'held' || it.status === 'partial')) Object.assign(it, { chunkCount: it.status === 'held' ? 0 : chunkCount, processedAt: now() });
      }
      if (src0 && (r.trigger === 'full' || r.trigger === 'manual' || r.trigger === 'schedule' || r.trigger === 'webhook')) {
        const before = src0.indexedSettingsDigest;
        reindexed(src0);
        const strategies = src0.ingest.strategies.filter((x) => aiApproved(src0) || (x !== 'topic' && x !== 'faq'));
        r.log.push(`chunk: rebuilt with ${strategies.join(', ')}${before !== src0.indexedSettingsDigest ? ' (settings changed since the last index)' : ''}`);
        if (!aiApproved(src0)) r.log.push('chunk: AI steps skipped until the knowledge owner approves them');
      }
      regovern();
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
    let finished = false;
    for (const it of items) {
      if (it.status !== 'processing' || runningRun(it.sourceId)) continue;
      const src = sources.find((x) => x.id === it.sourceId);
      Object.assign(it, { status: 'indexed', chunkCount: src ? chunkCountFor(it, src) : it.chunkCount, processedAt: now() });
      finished = true;
    }
    if (finished) regovern();
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
    k.healthReasons = [`Index refresh running: 0 of ${k.stats.documents} ${k.stats.documents === 1 ? 'item' : 'items'}`];
    k.indexing = { done: 0, total: Math.max(k.stats.documents, 1), taskId: id('task') };
    k.jobs.unshift({ id: id('job'), startedAt: now(), durationSec: 0, processed: 0, failed: 0, status: 'running', trigger });
  }

  function startSync(src: Source, opts: { full?: boolean; retry?: boolean } = {}): SyncRun {
    const total = opts.retry
      ? Math.max(src.itemsFailed, 1)
      : opts.full
        ? Math.max(src.itemsIndexed + src.itemsFailed, 12)
        : src.itemsIndexed === 0 && src.itemsPending > 0
          ? src.itemsPending
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
    Object.assign(src, { status: src.status === 'draft' ? 'active' : src.status, lastRunStatus: 'running' });
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
            metadataKeys: Array.from(new Set(['owner', 'effective_date', 'version', 'topic', ...items.filter((i) => ids.has(i.sourceId)).flatMap((i) => Object.keys(i.metadata))])).sort(),
            suggestedQuestions: suggestedQuestions[k.id] ?? suggestedQuestions.kb_all,
            heldCount: items.filter((i) => ids.has(i.sourceId) && i.status === 'held').length,
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
            precedence: [{ id: 'p1', label: 'Newer effective date beats older', kind: 'newer', winner: '', loser: '' }],
            metadataProfile: { required: ['owner'] },
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
          regovern();
          return k;
        }),
      update: (kid, patch) =>
        run(() => {
          const k = kbOr404(kid);
          const { retrieval, ...rest } = patch;
          if (rest.name && kbs.some((x) => x.id !== kid && x.name.toLowerCase() === rest.name!.toLowerCase())) throw new ApiError('A knowledge base with this name already exists.', 409);
          if (rest.metadataProfile) rest.metadataProfile = { required: Array.from(new Set(rest.metadataProfile.required.map(snakeKey).filter(Boolean))) };
          Object.assign(k, rest);
          if (retrieval) k.retrieval = { ...k.retrieval, ...retrieval };
          if (rest.metadataProfile) regovern();
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
          regovern();
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
          regovern();
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
          guardTeam(kbOwners(k), 'knowledge base');
          const { alsoKbIds, ...rest } = input;
          return engine.retrieve({ ...rest, kbIds: [kid, ...(alsoKbIds ?? []).filter((x) => x !== kid)] });
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
            connection: deps.connection(s.connectionId),
            readers: kbs.filter((k) => k.sources.some((l) => l.sourceId === sid)).map(({ id: kid, name, slug, color, health }) => ({ id: kid, name, slug, color, health })),
            running: runningRun(sid),
            recentRuns: srcRuns.slice(0, 5),
            errorGroups: [...groups.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([message, count]) => ({ message, count })),
            itemCount: items.filter((i) => i.sourceId === sid).length,
            reindexNeeded: s.status !== 'draft' && settingsDigest({ ...s }) !== s.indexedSettingsDigest,
            requiredMetadata: Array.from(new Set(kbs.filter((k) => k.sources.some((l) => l.sourceId === sid)).flatMap((k) => k.metadataProfile.required))).filter((k) => !['owner', 'effective_date', 'version'].includes(k)),
            aiStepsWaiting: aiSteps(s.ingest, s.metadataMapping).filter((x) => !s.ingest.approval.approvedSteps.includes(x)),
            approval: s.ingest.approval.status === 'pending' ? approvalView(sourceOr404(sid)) : undefined,
            governance: {
              excluded: items.filter((i) => i.sourceId === sid && i.status === 'excluded').length,
              held: items.filter((i) => i.sourceId === sid && i.status === 'held').length,
              duplicates: items.filter((i) => i.sourceId === sid && i.duplicateOf).length,
              superseded: items.filter((i) => i.sourceId === sid && i.versionStatus === 'superseded').length,
            },
          };
        }),
      create: (input, opts) =>
        run(() => {
          if (sources.some((s) => s.name.trim().toLowerCase() === input.name.trim().toLowerCase())) throw new ApiError('A source with this name already exists.', 409);
          const conn = deps.connection(input.connectionId);
          if (input.connectionId && !conn) throw new ApiError('That connection no longer exists. Pick another one.', 400);
          if (conn?.status === 'revoked') throw new ApiError(`${conn.name} is revoked. Reconnect it in Integrations or pick another connection.`, 409);
          validateIngest(input.ingest);
          if (input.type === 'file' && input.status !== 'draft' && !input.fileIds?.length) throw new ApiError('Upload at least one file.', 400);
          const { fileIds, ...rest } = input;
          const sid = id('src');
          // Linking first refuses a quarantined or still-scanning file before the source exists.
          for (const fid of fileIds ?? []) deps.files().link(fid, { type: 'source', id: sid, name: input.name.trim(), href: `/sources/${sid}` }, ['knowledge_source']);
          const s: Source = {
            ...rest,
            config: { ...rest.config, fileIds },
            id: sid,
            connectionId: conn?.id,
            connectionLabel: conn?.name,
            owner: deps.currentUser,
            status: input.status ?? 'active',
            itemsIndexed: 0,
            itemsFailed: 0,
            itemsPending: input.itemsPending ?? 0,
            usedByKbIds: [],
            createdAt: now(),
          };
          reconcileApproval(s, { status: 'not_needed', approvedSteps: [] });
          s.indexedSettingsDigest = settingsDigest(s);
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
          if (patch.ingest) validateIngest(patch.ingest);
          const approval = s.ingest.approval;
          Object.assign(s, patch);
          // Approval is the server's to keep; a client cannot send itself approved.
          reconcileApproval(s, approval);
          regovern();
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
          const c = input.config as { startUrl?: string };
          if (input.type === 'crawl' && /\/\/(10\.|192\.168\.|127\.)/.test(c.startUrl ?? '')) {
            return { ok: false, message: 'URL resolves to a private IP range. Crawls must target a public host.', rows: [] };
          }
          const rows = previewRows(input);
          const n = rows.length;
          return { ok: true, message: `Connection OK · ${n} item${n === 1 ? '' : 's'} would be fetched`, rows };
        }),
      previewHeld: (input) =>
        run(() => {
          const rows = previewRows(input);
          const mapped = new Map(input.metadataMapping.filter((m) => m.key.trim()).map((m) => [snakeKey(m.key), m.from]));
          // Owner and effective date always come with a new item; a source column is absent on some items, and AI extraction waits for approval.
          const has = (key: string, i: number) => {
            const k = snakeKey(key);
            if (k === 'owner' || k === 'effective_date' || k === 'version') return true;
            const from = mapped.get(k);
            if (!from) return false;
            if (from.startsWith('static:')) return !!from.slice(7).trim();
            if (from.startsWith('field:')) return i % 3 !== 2;
            return false;
          };
          const byKb = input.kbIds
            .map((kid) => kbs.find((k) => k.id === kid))
            .filter((k): k is KnowledgeBase => !!k)
            .map((k) => {
              const required = k.metadataProfile.required;
              const missingPer = rows.map((_, i) => required.filter((key) => !has(key, i)));
              return { kbId: k.id, kbName: k.name, required, held: missingPer.filter((x) => x.length).length, missing: Array.from(new Set(missingPer.flat())) };
            });
          return { items: rows.length, byKb };
        }),
      samples: (sid) => run(() => listSamples(sources, sid)),
      previewSplit: (input) => run(() => previewSplit(input)),
      approveIngest: (sid) =>
        run(() => {
          const s = sourceOr404(sid);
          const steps = aiSteps(s.ingest, s.metadataMapping);
          if (!steps.length) throw new ApiError('This source has no AI ingestion steps to approve.', 409);
          if (selfApproval(s)) throw new ApiError('You requested this change; another knowledge owner must approve.', 403);
          s.ingest.approval = { status: 'approved', approvedSteps: Array.from(new Set([...s.ingest.approval.approvedSteps, ...steps])), requestedBy: s.ingest.approval.requestedBy, decidedBy: deps.currentUser, decidedAt: now() };
          return s;
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
          const versions: ItemVersionRow[] = items
            .filter((x) => x.sourceId === it.sourceId && x.family === it.family && x.status !== 'excluded')
            .sort((a, b) => b.effectiveDate.localeCompare(a.effectiveDate))
            .map((x) => ({ itemId: x.id, title: x.title, version: x.version, effectiveDate: x.effectiveDate, status: x.versionStatus, digest: x.digest, sourceName: src?.name ?? x.sourceId, supersededBy: x.supersededBy }));
          return { ...it, sourceName: src?.name ?? it.sourceId, sourceType: src?.type ?? 'file', detail: { ...itemDetail(it, snapshots.get(it.sourceId)), versions } };
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
            regovern();
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
      setMetadata: (iid, values) =>
        run(() => {
          const it = itemOr404(iid);
          for (const [k, raw] of Object.entries(values)) {
            const v = raw.trim();
            if (!v) continue;
            const key = snakeKey(k);
            if (key === 'owner') it.owner = v;
            else if (key === 'effective_date') {
              if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) throw new ApiError('Effective date is a date such as 2026-07-01.', 422);
              it.effectiveDate = v;
            } else it.metadata = { ...it.metadata, [key]: v };
          }
          regovern();
          return it;
        }),
    },

    retrieve: (input) => run(() => engine.retrieve(input)),

    lookups: () =>
      run(() => ({
        owners: OWNERS,
        tags: Array.from(new Set(sources.flatMap((s) => s.tags))).sort(),
        collections: Array.from(new Set(sources.map((s) => s.collection))).sort(),
      })),
  };

  return {
    api,
    kbNames: () => kbs.map((k) => k.name),
    retrieveNow: (input) => engine.retrieve(input),
    sourcesUsing: (connId) => sources.filter((s) => s.connectionId === connId),
    reflectConnection: (connId, revoked) => {
      for (const s of sources) {
        if (s.connectionId !== connId || s.status === 'draft') continue;
        if (revoked) s.status = 'revoked';
        else if (s.status === 'revoked') s.status = 'active';
      }
    },
  };
}
