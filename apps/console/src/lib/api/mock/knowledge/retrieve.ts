import type { Citation, Item, KnowledgeBase, ParsingSettings, PlaygroundAnswer, PrecedenceRule, RetrievalSettings, RetrieveInput, ScoredChunk, Sensitivity, Source, StructuredValue } from '@/lib/types/knowledge';
import type { IngestSettings } from '@/lib/types/knowledge-ingest';
import type { CandidateFlag, CandidateOutcome, FilterCondition, PrecedenceDecision, ResolvedFilter, RetrievalTrace, RuntimeValues, TableRowHit, TraceCandidate } from '@/lib/types/knowledge-retrieval';
import type { PermissionScope, RunAsPrincipal } from '@/lib/types/run-as';

import { ApiError } from '../../contract';
import { PRINCIPALS } from '../run-as/principals';
import { GENERIC_PARAGRAPHS } from './detail';
import { digestOf, excludedByRules, snakeKey, splitDocument } from './ingest';
import { docByKey, FEATURED } from './seed-documents';

/** The settings a source's current chunks were built with; search reads these, not the unsaved or un-reindexed ones. */
export interface IndexSnapshot {
  ingest: IngestSettings;
  parsing: ParsingSettings;
  aiAllowed: boolean;
  digest: string;
}

interface Deps {
  items: () => Item[];
  sources: () => Source[];
  kbs: () => KnowledgeBase[];
  snapshot: (sourceId: string) => IndexSnapshot | undefined;
}

// ---- text ------------------------------------------------------------------

const STOP = new Set(
  'a an the and or of to in on at for by with from as is are was be been it its this that these those what when which where who whom how does do did can could would should will may might must we our us you your they their them there here have has had not no yes than then into over under about per any each every all some such only also more most much many long very just please tell me i my if so up out get got few several need needed'.split(' '),
);

/** Exact tokens for keyword search: codes like 12.6.1 also index as 12.6, and hyphenated terms as their parts. */
function kwTokens(s: string): string[] {
  const out: string[] = [];
  for (const m of s.toLowerCase().matchAll(/\$?[a-z0-9]+(?:[.\-][a-z0-9]+)*%?/g)) {
    const t = m[0];
    if (STOP.has(t) || (t.length < 2 && !/\d/.test(t))) continue;
    // The english full-text configuration stems "monthly" to "month" and "payments" to "payment".
    const stem = /^(month|year|week|quarter)ly$/.test(t) ? t.slice(0, -2) : /^[a-z]{5,}s$/.test(t) && !t.endsWith('ss') ? t.slice(0, -1) : t;
    out.push(stem);
    if (/^\d+(\.\d+){2,}$/.test(t)) out.push(t.split('.').slice(0, 2).join('.'));
    if (t.includes('-')) for (const p of t.split('-')) if (p.length > 1 && !STOP.has(p)) out.push(p);
  }
  return out;
}

const PHRASES: [RegExp, string][] = [
  [/payment holiday|skip[- ]a[- ]payment/g, 'deferral'],
  [/charged twice|more than once|double charge/g, 'duplicate'],
  [/money back/g, 'refund'],
  [/cut-off|cut off/g, 'cutoff'],
  [/call-back|call back/g, 'callback'],
  [/new-payee/g, 'new payee'],
];

/** Meaning, not spelling: synonyms collapse to one concept and numbers and codes drop out, as they do in an embedding. */
const SYN: Record<string, string> = Object.fromEntries(
  Object.entries({
    hold: 'hold held holding freeze frozen delay delayed',
    wire: 'wire transfer swift remittance',
    payee: 'payee beneficiary recipient',
    new: 'new added recent recently',
    refund: 'refund refunded reimburse reimbursed rebate',
    annual: 'annual yearly',
    fee: 'fee cost price pricing',
    dispute: 'dispute disputed chargeback contest challenge claim',
    duplicate: 'duplicate duplicated twice double',
    defer: 'defer deferral deferred deferring postpone postponed skip holiday',
    payment: 'payment instalment installment repayment',
    keep: 'retention retain retained keep kept store stored storage',
    record: 'record documentation',
    release: 'release released unblock',
    approve: 'approve approval approves authority authorise authorize',
    provisional: 'provisional temporary interim',
    customer: 'customer cardholder borrower client',
    loan: 'loan lending borrowing financing facility',
    origination: 'origination setup arrangement',
    business: 'business company commercial',
    card: 'card visa mastercard',
    fraud: 'fraud scam unauthorised unauthorized stolen',
    callback: 'callback phone telephone verify verification',
    form: 'form declaration affidavit',
    duration: 'long period window days months monthly years time',
    cutoff: 'cutoff deadline',
    start: 'start starts begin begins clock',
    nsf: 'nsf insufficient bounced',
    branch: 'branch location',
  }).flatMap(([concept, words]) => words.split(' ').map((w) => [w, concept])),
);

const stemS = (t: string) => (t.length > 5 && t.endsWith('ing') ? t.slice(0, -3) : t.length > 4 && t.endsWith('ed') ? t.slice(0, -2) : t.length > 4 && t.endsWith('ies') ? `${t.slice(0, -3)}y` : t.length > 3 && t.endsWith('s') && !t.endsWith('ss') ? t.slice(0, -1) : t);

function concepts(s: string): string[] {
  let x = s.toLowerCase();
  for (const [re, to] of PHRASES) x = x.replace(re, to);
  const out: string[] = [];
  for (const m of x.matchAll(/[a-z]+/g)) {
    const t = m[0];
    if (STOP.has(t) || t.length < 3) continue;
    out.push(SYN[t] ?? SYN[stemS(t)] ?? stemS(t));
  }
  return out;
}

/** Splits at a stop followed by a capital, so 1.00% and 12.6 stay whole. */
const sentencesOf = (s: string) => s.split(/(?<=[.!?])\s+(?=[A-Z“"(])/).map((x) => x.trim()).filter(Boolean);
/** Drops the "Title › Section" line context headers add, for answers and quotes. */
const bodyOf = (text: string) => (text.includes('\n') && text.split('\n')[0].includes('›') ? text.split('\n').slice(1).join(' ') : text);
const round = (n: number) => Math.round(n * 100) / 100;
const jitter = (id: string) => (parseInt(digestOf(id).slice(0, 4), 16) % 100) / 100;

/** Overridable settings in the words the Retrieval tab uses. */
const OVERRIDE_LABEL: Record<string, string> = {
  searchMode: 'search mode',
  hybridWeight: 'semantic weight',
  rerank: 'rerank setting',
  chunkLimit: 'chunk limit',
  threshold: 'relevance threshold',
  asOf: 'as-of date',
  rewrite: 'question rewriting',
  answerShape: 'answer format',
  structuredTables: 'table values setting',
  filters: 'filters',
  scopeSourceIds: 'sources searched',
};

// ---- index -----------------------------------------------------------------

interface IChunk {
  id: string;
  item: Item;
  sourceName: string;
  location: string;
  text: string;
  topic?: string;
  meta: Record<string, string>;
  row?: { index: number; key: string; values: Record<string, string>; searchable: string[] };
  tf: Map<string, number>;
  len: number;
  concepts: Set<string>;
  titleConcepts: Set<string>;
}

const parseRow = (line: string) =>
  Object.fromEntries(
    line
      .split(' | ')
      .map((kv) => [kv.slice(0, kv.indexOf(': ')), kv.slice(kv.indexOf(': ') + 2)])
      .filter(([k]) => k),
  ) as Record<string, string>;

export function createRetrieval(deps: Deps) {
  const cache = new Map<string, IChunk[]>();

  function build(item: Item, snap: IndexSnapshot | undefined, sourceName: string): IChunk[] {
    const key = `${item.id}|${snap?.digest}|${item.digest}|${JSON.stringify(item.metadata)}|${item.owner}|${item.effectiveDate}`;
    const hit = cache.get(key);
    if (hit) return hit;
    const base = { ...item.metadata, owner: item.owner, effective_date: item.effectiveDate, version: item.version };
    const mk = (i: number, location: string, text: string, indexed: string, meta: Record<string, string>, row?: IChunk['row']): IChunk => {
      const toks = kwTokens(indexed);
      const tf = new Map<string, number>();
      toks.forEach((t) => tf.set(t, (tf.get(t) ?? 0) + 1));
      return { id: `${item.id}#${i}`, item, sourceName, location, text, topic: meta.topic, meta, row, tf, len: toks.length, concepts: new Set(concepts(indexed)), titleConcepts: new Set(concepts(`${item.title} ${location}`)) };
    };
    const docKey = FEATURED[item.id];
    const doc = docKey ? docByKey(docKey) : undefined;
    let out: IChunk[];
    if (doc && snap) {
      const res = splitDocument(doc, snap.ingest, snap.parsing, {}, snap.aiAllowed);
      out = res.chunks.map((c) => {
        const row = c.kind === 'row' ? { index: Number(c.sectionPath[0].replace(/\D/g, '')), key: c.sectionPath[1] ?? '', values: parseRow(bodyOf(c.text)), searchable: Object.keys(parseRow(bodyOf(c.indexedText))) } : undefined;
        return mk(c.index, c.sectionPath.join(' › '), c.text, `${item.title}\n${c.indexedText}`, { ...base, ...c.metadata }, row);
      });
    } else {
      const para = GENERIC_PARAGRAPHS[parseInt(item.digest.slice(0, 4), 16) % GENERIC_PARAGRAPHS.length];
      const loc = item.pageCount ? 'p.1 · 1. Purpose' : '1. Purpose';
      out = [mk(0, loc, para, `${item.title}. ${item.path}. ${item.tags.join(' ')}. ${para}`, base)];
    }
    cache.set(key, out);
    return out;
  }

  // ---- query planning ------------------------------------------------------

  const ABBR: [RegExp, string][] = [
    [/\bsb\b/gi, 'small business'],
    [/\bloc\b/gi, 'line of credit'],
    [/\bcdd\b/gi, 'customer due diligence'],
    [/\bkyc\b/gi, 'know your customer'],
    [/\bpep\b/gi, 'politically exposed person'],
  ];
  const DOC_WORDS: [RegExp, string][] = [
    [/\bpostpone\b|\bskip\b|payment holiday/gi, 'defer'],
    [/\binstal?ments?\b/gi, 'payments'],
    [/\bmoney back\b/gi, 'refund'],
    [/\bcharged twice\b/gi, 'duplicate processing'],
    [/\bborrower\b/gi, 'customer'],
    [/\bfrozen\b|\bfreeze\b/gi, 'hold'],
  ];
  const FILLER = /^(hi|hello|hey)[,!.\s]+|^(can|could) you (tell me|explain|check)\s+|^please\s+|^i (want|need) to know\s+/i;

  function rewrite(q: string) {
    let x = q.trim().replace(FILLER, '');
    for (const [re, to] of ABBR) x = x.replace(re, to);
    for (const [re, to] of DOC_WORDS) x = x.replace(re, to);
    return x.replace(/\s+/g, ' ').trim();
  }

  function plan(q: string, s: RetrievalSettings): RetrievalTrace['queries'] {
    const out: RetrievalTrace['queries'] = [{ text: q, kind: 'original' }];
    if (s.rewrite === 'off') return out;
    const r = rewrite(q);
    if (s.rewrite === 'rewrite') return r.toLowerCase() === q.toLowerCase() ? out : [{ text: r, kind: 'rewritten' }];
    const content = kwTokens(r).filter((t) => !/^\d/.test(t));
    const variants = [r, `${content.join(' ')} policy`, `${content.slice(0, 4).join(' ')} procedure and limits`, `rules for ${content.slice(0, 3).join(' ')}`];
    for (const v of variants) {
      if (out.length >= Math.max(2, s.expandCount)) break;
      if (!out.some((o) => o.text.toLowerCase() === v.toLowerCase())) out.push({ text: v, kind: 'expanded' });
    }
    return out;
  }

  // ---- filters -------------------------------------------------------------

  function resolveValue(v: string, runtime: RuntimeValues | undefined, preview?: string): Pick<ResolvedFilter, 'resolved' | 'from'> {
    const t = v.trim();
    if (!/^\{[a-z_.]+\}$/i.test(t)) return { resolved: t, from: 'literal' };
    if (runtime?.[t]) return { resolved: runtime[t], from: 'runtime' };
    if (preview?.trim()) return { resolved: preview.trim(), from: 'preview' };
    return { resolved: '', from: 'unset' };
  }

  function resolveFilter(c: FilterCondition, runtime?: RuntimeValues): ResolvedFilter {
    if (c.op === 'one_of') {
      const parts = c.value.split(',').map((p) => resolveValue(p, runtime, c.preview));
      const used = parts.filter((p) => p.from !== 'unset');
      const from = used.some((p) => p.from === 'runtime') ? 'runtime' : used.some((p) => p.from === 'preview') ? 'preview' : used.length ? 'literal' : 'unset';
      return { key: c.key, op: c.op, value: c.value, resolved: used.map((p) => p.resolved).join(', '), from };
    }
    return { key: c.key, op: c.op, value: c.value, ...resolveValue(c.value, runtime, c.preview) };
  }

  function passes(meta: Record<string, string>, f: ResolvedFilter) {
    if (f.from === 'unset' && f.op !== 'exists') return true;
    const v = (meta[snakeKey(f.key)] ?? meta[f.key] ?? '').toLowerCase();
    const want = f.resolved.toLowerCase();
    switch (f.op) {
      case 'is':
        return v === want;
      case 'is_not':
        return v !== want;
      case 'one_of':
        return want.split(',').map((x) => x.trim()).includes(v);
      case 'before':
        return !!v && v < want;
      case 'after':
        return !!v && v > want;
      case 'exists':
        return !!v;
    }
  }

  // ---- table lookup --------------------------------------------------------

  const amountIn = (q: string) => {
    const m = q.toLowerCase().match(/(over|above|more than|greater than|>|under|below|less than|up to|<=?)?\s*\$?\s?(\d[\d,]*(?:\.\d+)?)\s*(k|m|thousand|million)?\b/);
    if (!m) return undefined;
    const n = Number(m[2].replace(/,/g, '')) * ({ k: 1e3, thousand: 1e3, m: 1e6, million: 1e6 }[m[3] ?? ''] ?? 1);
    if (n < 100) return undefined;
    return /over|above|more|greater|>/.test(m[1] ?? '') ? n + 1 : /under|below|less|</.test(m[1] ?? '') ? n - 1 : n;
  };
  const inBand = (band: string, amount: number) => {
    if (/any/i.test(band)) return true;
    const m = band.match(/(<=|>=|<|>)\s*\$?([\d,]+)/);
    if (!m) return false;
    const b = Number(m[2].replace(/,/g, ''));
    return m[1] === '<=' ? amount <= b : m[1] === '<' ? amount < b : m[1] === '>=' ? amount >= b : amount > b;
  };

  function rowScore(c: IChunk, q: string) {
    const row = c.row!;
    const qt = new Set(kwTokens(q));
    const matched: string[] = [];
    const keyToks = kwTokens(row.key);
    const keyHit = keyToks.length ? Math.pow(keyToks.filter((t) => qt.has(t)).length / keyToks.length, 2) : 0;
    if (keyHit >= 0.5) matched.push(Object.keys(row.values)[0] ?? 'Key');
    const amount = amountIn(q);
    const bandCol = Object.keys(row.values).find((k) => /band|amount|range/i.test(k));
    let band = 0.5;
    if (bandCol && amount !== undefined) {
      band = inBand(row.values[bandCol], amount) ? 1 : 0;
      if (band) matched.push(bandCol);
    }
    const others = row.searchable.filter((k) => k !== bandCol && row.values[k] !== row.key);
    const otherHit = others.filter((k) => kwTokens(row.values[k] ?? '').some((t) => qt.has(t) && !['no', 'any'].includes(t)));
    matched.push(...otherHit);
    const otherScore = others.length ? Math.min(1, otherHit.length) : 0;
    const secured = row.values.Secured && row.values.Secured !== 'No';
    const wantsSecured = /secured|property|collateral|equipment/.test(q.toLowerCase());
    const penalty = secured && !wantsSecured ? 0.12 : 0;
    // A row outside the asked amount band is the wrong row, however well the product matches.
    const raw = Math.max(0, 0.2 + 0.45 * keyHit + 0.25 * band + 0.1 * otherScore - penalty);
    return { score: round(band === 0 ? raw * 0.6 : raw), matched };
  }

  // ---- permissions -----------------------------------------------------------

  const RANK: Record<Sensitivity, number> = { internal: 0, confidential: 1, restricted: 2 };
  const canSee = (p: RunAsPrincipal, s: Source) => (p.collections === null || p.collections.includes(s.collection)) && RANK[s.sensitivity] <= RANK[p.clearance];

  // ---- the query -----------------------------------------------------------

  function retrieve(input: RetrieveInput): PlaygroundAnswer {
    const question = input.question.trim();
    if (!question) throw new ApiError('Ask a question first.', 400);
    const allKbs = deps.kbs();
    const kbs = input.kbIds.map((id) => allKbs.find((k) => k.id === id)).filter((k): k is KnowledgeBase => !!k);
    if (!kbs.length) throw new ApiError('Knowledge base not found.', 404);
    const primary = kbs[0];
    const s: RetrievalSettings = { ...(input.settings ?? primary.retrieval), ...(input.overrides ?? {}) };
    const settingsFrom = input.settings ? 'This request' : `Saved settings of ${primary.name}${kbs.length > 1 ? '; each knowledge base applies its own filters' : ''}${input.overrides && Object.keys(input.overrides).length ? `; this caller changed the ${Object.keys(input.overrides).map((k) => OVERRIDE_LABEL[k] ?? 'other settings').join(', ')}` : ''}`;
    const principal = input.runAsId ? PRINCIPALS.find((p) => p.id === input.runAsId) : undefined;
    if (input.runAsId && !principal) throw new ApiError('That person or role no longer exists. Choose another to run as.', 404);
    const sources = deps.sources();
    const srcById = new Map(sources.map((x) => [x.id, x]));
    const items = deps.items();
    const queries = plan(question, s);
    const qConcepts = Array.from(new Set(queries.flatMap((q) => concepts(q.text))));
    const qTokens = Array.from(new Set(queries.flatMap((q) => kwTokens(q.text))));

    // Pool: each knowledge base's searchable items, its filters and tags, then permissions — all before ranking.
    const seen = new Set<string>();
    const pool: { c: IChunk; kbName: string }[] = [];
    // Chunks set aside by permissions or filters are scored afterwards only to count the documents that would have matched.
    const hiddenPool: IChunk[] = [];
    const filteredPool: IChunk[] = [];
    const resolvedFilters: ResolvedFilter[] = [];
    for (const kb of kbs) {
      const ks = input.settings ? s : { ...kb.retrieval, ...(input.overrides ?? {}) };
      const resolved = ks.filters.conditions.filter((c) => c.key.trim()).map((c) => resolveFilter(c, input.runtime));
      if (kb === primary || !input.settings) resolvedFilters.push(...resolved.filter((r) => !resolvedFilters.some((x) => x.key === r.key && x.op === r.op && x.value === r.value)));
      const scope = kb === primary && ks.scopeSourceIds.length ? new Set(ks.scopeSourceIds) : undefined;
      for (const link of kb.sources) {
        if (scope && !scope.has(link.sourceId)) continue;
        const src = srcById.get(link.sourceId);
        if (!src) continue;
        for (const it of items) {
          if (it.sourceId !== src.id || seen.has(it.id)) continue;
          if ((it.status !== 'indexed' && it.status !== 'partial') || it.duplicateOf) continue;
          if (link.rules.length && excludedByRules(link.rules, it)) continue;
          seen.add(it.id);
          for (const c of build(it, deps.snapshot(src.id), src.name)) {
            if (principal && !canSee(principal, src)) {
              hiddenPool.push(c);
              continue;
            }
            const tagsOk = (!ks.tagsInclude.length || it.tags.some((t) => ks.tagsInclude.includes(t)) || (!it.tags.length && ks.includeUntagged)) && !it.tags.some((t) => ks.tagsExclude.includes(t));
            const metaOk = !resolved.length || (ks.filters.match === 'all' ? resolved.every((f) => passes(c.meta, f)) : resolved.some((f) => passes(c.meta, f)));
            if (!tagsOk || !metaOk) {
              filteredPool.push(c);
              continue;
            }
            pool.push({ c, kbName: kb.name });
          }
        }
      }
    }
    const pooledDocs = new Set(pool.map((p) => p.c.item.id));

    // Statistics over the searchable pool.
    const N = Math.max(pool.length, 1);
    const df = new Map<string, number>();
    const cdf = new Map<string, number>();
    let totalLen = 0;
    for (const { c } of pool) {
      totalLen += c.len;
      for (const t of c.tf.keys()) df.set(t, (df.get(t) ?? 0) + 1);
      for (const x of c.concepts) cdf.set(x, (cdf.get(x) ?? 0) + 1);
    }
    const avgLen = totalLen / N || 1;
    const idf = (t: string) => Math.log(1 + (N - (df.get(t) ?? 0) + 0.5) / ((df.get(t) ?? 0) + 0.5));
    const cw = (x: string) => Math.log(1 + N / (1 + (cdf.get(x) ?? 0)));

    const keywordScore = (c: IChunk, toks: string[]) => {
      const present = toks.filter((t) => df.has(t));
      if (!present.length) return 0;
      const norm = present.reduce((n, t) => n + idf(t), 0);
      const raw = present.reduce((n, t) => {
        const f = c.tf.get(t) ?? 0;
        // Saturates at one match in an average-length chunk, so a short chunk cannot outscore a full match.
        return f ? n + idf(t) * Math.min(1, (f * 2.2) / (f + 1.2 * (0.25 + 0.75 * (c.len / avgLen)))) : n;
      }, 0);
      const r = Math.min(1, raw / norm);
      return r > 0 ? round(0.15 + 0.82 * r) : 0;
    };
    const coverage = (set: Set<string>, qc: string[]) => {
      if (!qc.length) return 0;
      const total = qc.reduce((n, x) => n + cw(x), 0);
      return qc.reduce((n, x) => (set.has(x) ? n + cw(x) : n), 0) / total;
    };
    const semanticScore = (c: IChunk, qc: string[]) => round(Math.min(0.97, 0.1 + 0.07 * jitter(c.id) + 0.8 * Math.pow(coverage(c.concepts, qc), 0.85)));

    // Versions: superseded and not-yet-effective versions are left out, unless as-of picks the one in force then.
    const asOf = s.searchMode === 'as_of' ? s.asOf || new Date().toISOString().slice(0, 10) : undefined;
    const versionOutcome = new Map<string, CandidateOutcome>();
    if (asOf) {
      const fams = new Map<string, Item[]>();
      for (const it of items) {
        if (!pooledDocs.has(it.id)) continue;
        const k = `${it.sourceId}|${it.family}`;
        fams.set(k, [...(fams.get(k) ?? []), it]);
      }
      for (const group of fams.values()) {
        const inForce = group.filter((it) => it.effectiveDate <= asOf).sort((a, b) => b.effectiveDate.localeCompare(a.effectiveDate))[0];
        for (const it of group) if (it !== inForce) versionOutcome.set(it.id, it.effectiveDate > asOf ? 'not_in_force' : 'superseded');
      }
    } else {
      for (const it of items) {
        if (!pooledDocs.has(it.id)) continue;
        if (it.versionStatus === 'superseded') versionOutcome.set(it.id, 'superseded');
        if (it.versionStatus === 'scheduled') versionOutcome.set(it.id, 'not_in_force');
      }
    }

    const tableMode = s.searchMode === 'table_lookup';
    const hybrid = s.searchMode === 'hybrid' || s.searchMode === 'as_of';
    const w = s.searchMode === 'semantic' ? 1 : s.searchMode === 'keyword' ? 0 : s.hybridWeight;
    /** `final` is the calibrated 0–1 relevance the threshold reads; `order` ranks (the fused score in hybrid). */
    type Scored = { c: IChunk; kbName: string; kw: number; sem: number; fused: number; reranked?: number; final: number; order: number; ranks?: { semantic?: number; keyword?: number }; matchedQuery?: string; matched?: string[] };
    const calibrated = (kw: number, sem: number) => (s.searchMode === 'semantic' ? sem : s.searchMode === 'keyword' ? kw : Math.max(kw, sem));
    const scoreChunk = (c: IChunk, kbName: string): Scored | undefined => {
      let best: Scored | undefined;
      for (const q of queries) {
        const matchedQuery = q.kind === 'original' ? undefined : q.text;
        if (tableMode) {
          const r = rowScore(c, q.text);
          const sc: Scored = { c, kbName, kw: keywordScore(c, kwTokens(q.text)), sem: semanticScore(c, concepts(q.text)), fused: r.score, final: r.score, order: r.score, matched: r.matched, matchedQuery };
          if (!best || sc.final > best.final) best = sc;
          continue;
        }
        const kw = keywordScore(c, kwTokens(q.text));
        const sem = semanticScore(c, concepts(q.text));
        const cal = round(calibrated(kw, sem));
        if (!best) best = { c, kbName, kw, sem, fused: cal, final: cal, order: cal, matchedQuery };
        else {
          // Each list keeps the phrasing that scored the chunk best in it.
          if (cal > best.final) best.matchedQuery = matchedQuery;
          best.kw = Math.max(best.kw, kw);
          best.sem = Math.max(best.sem, sem);
          best.final = best.fused = best.order = round(calibrated(best.kw, best.sem));
        }
      }
      return best;
    };
    const scored: Scored[] = [];
    for (const { c, kbName } of pool) {
      if (tableMode && !c.row) continue;
      const x = scoreChunk(c, kbName);
      if (x) scored.push(x);
    }

    // Hybrid: weighted reciprocal rank fusion over the top 50 of each list, ranked among in-force passages only.
    if (hybrid && !tableMode) {
      const ranked = scored.filter((x) => !versionOutcome.has(x.c.item.id));
      const rankBy = (key: 'sem' | 'kw') =>
        new Map(
          ranked
            .filter((x) => x[key] > 0)
            .sort((a, b) => b[key] - a[key] || a.c.id.localeCompare(b.c.id))
            .slice(0, 50)
            .map((x, i) => [x.c.id, i + 1]),
        );
      const semRank = rankBy('sem');
      const kwRank = rankBy('kw');
      for (const x of scored) {
        const rs = semRank.get(x.c.id);
        const rk = kwRank.get(x.c.id);
        x.ranks = { semantic: rs, keyword: rk };
        x.fused = Math.round(((rs ? w / (60 + rs) : 0) + (rk ? (1 - w) / (60 + rk) : 0)) * 1e5) / 1e5;
        x.order = x.fused;
      }
    }
    scored.sort((a, b) => b.order - a.order || b.final - a.final || a.c.id.localeCompare(b.c.id));

    // Rerank the top of the list with a closer read: phrase overlap and whether the section heading is on point.
    if (s.rerank && !tableMode) {
      const qLower = question.toLowerCase();
      const bigrams = (x: string) => {
        const t = kwTokens(x);
        return new Set(t.slice(1).map((v, i) => `${t[i]} ${v}`));
      };
      const qb = bigrams(qLower);
      for (const x of scored.slice(0, 30)) {
        const cb = bigrams(x.c.text);
        const phrase = qb.size ? [...qb].filter((b) => cb.has(b)).length / qb.size : 0;
        const heading = coverage(x.c.titleConcepts, qConcepts);
        const signal = 0.5 * coverage(x.c.concepts, qConcepts) + 0.3 * phrase + 0.2 * heading;
        x.reranked = round(Math.min(0.98, 0.55 * x.final + 0.45 * (0.15 + 0.85 * signal)));
        x.final = x.order = x.reranked;
      }
      scored.sort((a, b) => b.order - a.order || a.c.id.localeCompare(b.c.id));
    }

    const outcome = new Map<string, CandidateOutcome>();
    const notes = new Map<string, string>();
    for (const x of scored) {
      const v = versionOutcome.get(x.c.item.id);
      if (v) {
        outcome.set(x.c.id, v);
        notes.set(x.c.id, v === 'superseded' ? `Superseded${x.c.item.supersededBy ? ` by ${x.c.item.supersededBy}` : ''}${asOf ? ` before ${asOf}` : ''}` : `Not in force${asOf ? ` on ${asOf}` : ' yet'}; effective ${x.c.item.effectiveDate}`);
      } else if (x.final < s.threshold) outcome.set(x.c.id, 'below_threshold');
    }

    // Precedence among the passages that would be returned.
    const rules: { r: PrecedenceRule; kbName: string }[] = kbs.flatMap((k) => k.precedence.map((r) => ({ r, kbName: k.name })));
    const decisions: PrecedenceDecision[] = [];
    const kept: Scored[] = [];
    const titleOf = (x: Scored) => `${x.c.item.title} ${x.c.item.version}`;
    for (const x of scored) {
      if (outcome.has(x.c.id)) continue;
      const rival = x.c.topic ? kept.find((k) => k.c.topic === x.c.topic && k.c.item.id !== x.c.item.id) : undefined;
      if (!rival) {
        kept.push(x);
        continue;
      }
      let loser: Scored | undefined;
      let decided: { r: PrecedenceRule; kbName: string } | undefined;
      for (const rule of rules) {
        if (rule.r.kind === 'class') {
          const a = rival.c.meta.doc_class;
          const b = x.c.meta.doc_class;
          if (a === rule.r.winner && b === rule.r.loser) loser = x;
          else if (b === rule.r.winner && a === rule.r.loser) loser = rival;
        } else if (rival.c.item.effectiveDate !== x.c.item.effectiveDate) loser = rival.c.item.effectiveDate > x.c.item.effectiveDate ? x : rival;
        if (loser) {
          decided = rule;
          break;
        }
      }
      if (!loser || !decided) {
        kept.push(x);
        continue;
      }
      const winner = loser === x ? rival : x;
      decisions.push({ rule: decided.r.label, kbName: decided.kbName, winner: titleOf(winner), loser: titleOf(loser) });
      outcome.set(loser.c.id, 'lost_precedence');
      notes.set(loser.c.id, `${decided.r.label} (${decided.kbName}): ${titleOf(winner)} was used instead`);
      if (loser === rival) kept.splice(kept.indexOf(rival), 1, x);
    }
    kept.sort((a, b) => b.order - a.order);
    kept.forEach((x, i) => outcome.set(x.c.id, i < s.chunkLimit ? 'returned' : 'over_limit'));
    const returned = kept.slice(0, s.chunkLimit);

    // Documents set aside before ranking count only when they would have been returned: above the threshold and
    // inside the chunk limit once ranked with what was returned.
    const wouldMatch = (chunks: IChunk[]) => {
      const best = new Map<string, number>();
      for (const c of chunks) {
        if (pooledDocs.has(c.item.id) || (tableMode && !c.row)) continue;
        const f = scoreChunk(c, '')?.final ?? 0;
        if (f >= s.threshold && f > (best.get(c.item.id) ?? 0)) best.set(c.item.id, f);
      }
      const merged = [...returned.map((x) => ({ doc: '', f: x.final })), ...[...best].map(([doc, f]) => ({ doc, f }))].sort((a, b) => b.f - a.f).slice(0, s.chunkLimit);
      return new Set(merged.map((x) => x.doc).filter(Boolean));
    };
    const filteredDocs = wouldMatch(filteredPool);
    const hiddenDocs = wouldMatch(hiddenPool);
    const hiddenCollections = new Set(hiddenPool.filter((c) => hiddenDocs.has(c.item.id)).map((c) => srcById.get(c.item.sourceId)?.collection).filter((x): x is string => !!x));


    // Trace candidates: everything returned plus what came close or was set aside.
    const today = new Date().toISOString().slice(0, 10);
    const traceList = scored.filter((x) => outcome.get(x.c.id) === 'returned' || x.final >= 0.3 || outcome.get(x.c.id) === 'lost_precedence').slice(0, 30);
    const candidates: TraceCandidate[] = traceList.map((x) => {
      const flags: CandidateFlag[] = [];
      if (x.c.item.versionStatus === 'superseded') flags.push('superseded');
      if (x.c.item.versionStatus === 'scheduled') flags.push('scheduled');
      if (x.c.item.reviewBy < today) flags.push('stale');
      if (x.c.item.alsoIn?.length) flags.push('deduplicated');
      if (srcById.get(x.c.item.sourceId)?.status === 'revoked') flags.push('connection_revoked');
      const o = outcome.get(x.c.id) ?? 'below_threshold';
      return {
        chunkId: x.c.id,
        documentId: x.c.item.id,
        documentTitle: x.c.item.title,
        sourceName: x.c.sourceName,
        kbName: x.kbName,
        location: x.c.location,
        version: x.c.item.version,
        effectiveDate: x.c.item.effectiveDate,
        text: x.c.text,
        scores: { keyword: x.kw, semantic: x.sem, fused: x.fused, reranked: x.reranked, semanticRank: x.ranks?.semantic, keywordRank: x.ranks?.keyword },
        final: x.final,
        outcome: o,
        flags,
        matchedQuery: x.matchedQuery,
        note: notes.get(x.c.id) ?? (x.c.item.alsoIn?.length ? `Same text also in ${x.c.item.alsoIn.map((a) => `${a.title} (${a.sourceName})`).join(', ')}; indexed once` : o === 'below_threshold' ? `Below the ${s.threshold.toFixed(2)} threshold` : o === 'over_limit' ? `Beyond the ${s.chunkLimit}-chunk limit` : x.matched?.length ? `Matched ${x.matched.join(', ')}` : undefined),
      };
    });

    // Answer.
    const bestSentences = (text: string, n: number) => {
      const ss = sentencesOf(bodyOf(text));
      const ranked = ss.map((t, i) => ({ t, i, sc: concepts(t).filter((x) => qConcepts.includes(x)).length + (kwTokens(t).some((k) => qTokens.includes(k) && /\d/.test(k)) ? 1 : 0) })).sort((a, b) => b.sc - a.sc || a.i - b.i);
      return ranked.slice(0, n).sort((a, b) => a.i - b.i).map((x) => x.t);
    };
    const winners = new Set(decisions.map((d) => d.winner));
    // A written answer draws on passages close to the best one; the rest stay in the chunks list.
    const answerFloor = s.answerShape === 'chunks' || !returned.length ? 0 : returned[0].final - 0.2;
    const citeList = returned.filter((x, i, arr) => arr.findIndex((y) => y.c.item.id === x.c.item.id) === i && x.final >= answerFloor).slice(0, s.answerShape === 'chunks' ? s.chunkLimit : 3);
    const citations: Citation[] = citeList.map((x, i) => ({
      n: i + 1,
      documentId: x.c.item.id,
      title: x.c.item.title,
      section: x.c.location,
      version: x.c.item.version,
      snippet: bestSentences(x.c.text, 1)[0] ?? x.c.text.slice(0, 160),
      url: x.c.item.url,
      stale: x.c.item.reviewBy < today || undefined,
      connectionRevoked: srcById.get(x.c.item.sourceId)?.status === 'revoked' || undefined,
      inForceOn: asOf,
      supersededToday: asOf && x.c.item.versionStatus === 'superseded' ? true : undefined,
      precedenceNote: winners.has(titleOf(x)) ? `Followed over ${decisions.filter((d) => d.winner === titleOf(x)).map((d) => `${d.loser} (${d.rule.toLowerCase()})`).join('; ')}` : undefined,
    }));
    const nOf = (x: Scored) => citations.find((c) => c.documentId === x.c.item.id)?.n ?? 1;
    const noAnswer = returned.length === 0;
    const searchableOf = (x: Scored) => x.c.row?.searchable ?? [];
    let rows: TableRowHit[] | undefined;
    let structured: StructuredValue[] | undefined;
    let answer = '';
    if (tableMode) {
      rows = returned.map((x) => ({ documentId: x.c.item.id, documentTitle: x.c.item.title, version: x.c.item.version, row: x.c.row!.index, key: x.c.row!.key, values: x.c.row!.values, matched: x.matched ?? [], score: x.final }));
      const top = rows[0];
      if (top) {
        const metaCols = Object.keys(top.values).filter((k) => !searchableOf(returned[0]).includes(k));
        structured = metaCols.map((k) => ({ label: k, value: top.values[k], from: `${top.documentTitle} · row ${top.row}` }));
      }
    }
    if (!noAnswer && s.answerShape !== 'chunks') {
      if (tableMode && rows) {
        answer = rows
          .slice(0, 2)
          .map((r, i) => {
            const searchable = searchableOf(returned[i]);
            const desc = searchable.filter((k) => k !== Object.keys(r.values)[0] && r.values[k] && r.values[k] !== 'No').map((k) => r.values[k]).join(', ');
            const vals = Object.keys(r.values).filter((k) => !searchable.includes(k)).map((k) => `${k.toLowerCase()} ${r.values[k]}`).join(', ');
            return `${r.key}${desc ? ` (${desc})` : ''}: ${vals} [${nOf(returned[i])}].`;
          })
          .join(' ');
      } else if (s.answerShape === 'extractive_quote') {
        answer = citeList.map((x) => `“${bestSentences(x.c.text, 1)[0]}” — ${x.c.item.title}, ${x.c.location} [${nOf(x)}]`).join('\n');
      } else {
        answer = citeList.map((x) => `${bestSentences(x.c.text, 2).join(' ')} [${nOf(x)}]`).join(' ');
      }
      if (asOf) answer = `As of ${asOf}, the version in force was ${citeList[0].c.item.title} ${citeList[0].c.item.version} (effective ${citeList[0].c.item.effectiveDate}). ${answer}`;
    }

    const searchMs = 60 + Math.round(pool.length / 25) * queries.length;
    const rerankMs = s.rerank && !tableMode ? 140 : 0;
    const rewriteMs = queries.length > 1 || queries[0].kind !== 'original' ? 220 + 60 * (queries.length - 1) : 0;
    const synthesisMs = answer ? 700 + answer.length * 3 : 0;
    const trace: RetrievalTrace = {
      question,
      queries,
      mode: s.searchMode,
      hybridWeight: w,
      rerank: s.rerank && !tableMode,
      asOf,
      kbs: kbs.map((k) => ({ id: k.id, name: k.name })),
      settingsFrom,
      filters: { match: s.filters.match, conditions: resolvedFilters, tagsInclude: s.tagsInclude, tagsExclude: s.tagsExclude, removed: filteredDocs.size },
      // Only a run-as preview learns what the person cannot read; everyone else's trace says nothing about it.
      hiddenByPermissions: principal ? hiddenDocs.size : undefined,
      runAsName: principal?.name,
      searched: pool.length,
      candidates,
      threshold: s.threshold,
      chunkLimit: s.chunkLimit,
      precedence: decisions,
      timings: { rewriteMs, searchMs, rerankMs, synthesisMs },
    };
    const chunks: ScoredChunk[] = candidates
      .filter((c) => c.outcome !== 'superseded' && c.outcome !== 'not_in_force')
      .sort((a, b) => Number(b.outcome === 'returned') - Number(a.outcome === 'returned') || b.final - a.final)
      .slice(0, Math.max(s.chunkLimit + 4, 6))
      .map((c) => ({ chunkId: c.chunkId, documentId: c.documentId, documentTitle: c.documentTitle, sourceName: c.sourceName, score: c.final, location: c.location, text: c.text, rejected: c.outcome !== 'returned', version: c.version }));
    const permissions: PermissionScope | undefined = principal
      ? { runAsId: principal.id, runAsName: principal.name, hiddenDocuments: hiddenDocs.size, hiddenCollections: [...hiddenCollections], blockedTools: [] }
      : undefined;

    return {
      id: `pa_${digestOf(`${question}|${Date.now()}`)}`,
      question,
      matchers: [],
      answer,
      citations: noAnswer ? [] : citations,
      chunks,
      structured: s.structuredTables ? structured : undefined,
      followed: decisions.length ? decisions.map((d) => `${d.winner} over ${d.loser} — ${d.rule}`).join('; ') : returned[0] ? `${titleOf(returned[0])}, the highest-scoring passage` : undefined,
      noAnswer,
      retrievalMs: rewriteMs + searchMs + rerankMs,
      synthesisMs,
      permissions,
      shape: s.answerShape,
      rows,
      trace,
    };
  }

  return { retrieve, clearCache: () => cache.clear() };
}
