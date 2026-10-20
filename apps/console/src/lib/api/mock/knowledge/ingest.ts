import type { Item, KnowledgeBase, MetadataMapping, ParsingSettings, Rule, Source } from '@/lib/types/knowledge';
import type { IngestSettings, IngestStrategy, PreviewChunk, SampleDocument, SplitCounts, SplitPreview, SplitPreviewInput, TableColumn } from '@/lib/types/knowledge-ingest';

import { ApiError } from '../../contract';
import { docByKey, FEATURED, SAMPLES, SEED_DOCUMENTS, type SeedDocument } from './seed-documents';

/** Steps that call a model at ingest and so need the knowledge owner's approval. */
export const AI_STRATEGIES: IngestStrategy[] = ['topic', 'faq'];
const SPLITTERS: IngestStrategy[] = ['structure', 'fixed', 'topic'];
export const DEFAULT_INGEST_MODEL = 'ingest-standard';

export const tokensOf = (s: string) => Math.ceil(s.split(/\s+/).filter(Boolean).length * 1.3);
const sentences = (s: string) => s.split(/(?<=[.!?])\s+(?=[A-Z“"(])/).map((x) => x.trim()).filter(Boolean);
export const snakeKey = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');

/** FNV-1a, enough for a stable content digest in the mock. */
export function digestOf(s: string) {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, '0');
}

export const docText = (d: SeedDocument) =>
  [d.title, ...d.sections.map((s) => `${s.heading}\n${s.body}`), ...(d.table ? [d.table.columns.join(' | '), ...d.table.rows.map((r) => r.join(' | '))] : [])].join('\n');

/** The AI steps a source's settings would run, as approval names them. */
export function aiSteps(ingest: IngestSettings, mapping: MetadataMapping[]) {
  return [...ingest.strategies.filter((s) => AI_STRATEGIES.includes(s)), ...mapping.filter((m) => m.from.startsWith('ai:')).map((m) => `extract ${m.key}`)];
}

export const aiApproved = (src: Pick<Source, 'ingest' | 'metadataMapping'>) => aiSteps(src.ingest, src.metadataMapping).every((s) => src.ingest.approval.approvedSteps.includes(s));

/** Rejects combinations that cannot run together, in the words the settings form uses. */
export function validateIngest(i: IngestSettings) {
  const splitters = i.strategies.filter((s) => SPLITTERS.includes(s));
  if (splitters.length > 1) throw new ApiError('Choose one way to split the text: structure, fixed size or topic.', 422);
  if (i.strategies.includes('parent_child') && i.strategies.includes('fixed')) throw new ApiError('Parent and child chunks need sections, so they work with structure or topic splitting, not fixed size.', 422);
  if (i.strategies.includes('table_rows') && i.columns.length && !i.columns.some((c) => c.role === 'searchable')) throw new ApiError('Mark at least one table column as searchable.', 422);
  if (i.strategies.includes('table_rows') && i.columns.filter((c) => c.key).length > 1) throw new ApiError('A table has one key column.', 422);
  if (i.size < 100 || i.size > 2000) throw new ApiError('Chunk size is 100 to 2,000 tokens.', 422);
  if (i.overlap < 0 || i.overlap >= i.size) throw new ApiError('Overlap is 0 and less than the chunk size.', 422);
}

// ---- splitting -------------------------------------------------------------

interface Piece {
  path: string[];
  text: string;
  topic?: string;
  questions?: string[];
}

function groupSentences(text: string, maxTokens: number, overlapTokens: number) {
  const out: string[] = [];
  let cur: string[] = [];
  for (const s of sentences(text)) {
    if (cur.length && tokensOf([...cur, s].join(' ')) > maxTokens) {
      out.push(cur.join(' '));
      const carry = overlapTokens > 0 ? cur.slice(-1).filter((x) => tokensOf(x) <= overlapTokens * 2) : [];
      cur = [...carry];
    }
    cur.push(s);
  }
  if (cur.length) out.push(cur.join(' '));
  return out;
}

const plainHeading = (h: string) => h.replace(/^(\d+(\.\d+)*\.?|Q:)\s*/, '').replace(/\s*\(.*\)$/, '').toLowerCase();

function generatedQuestions(doc: SeedDocument, heading: string, n: number) {
  const h = plainHeading(heading);
  return [`What does “${doc.title}” say about ${h}?`, `Which rules cover ${h}?`, `Who does the ${h} section apply to?`].slice(0, n);
}

function rowColumns(doc: SeedDocument, columns: TableColumn[]): TableColumn[] {
  const cols = doc.table!.columns;
  const set = columns.filter((c) => cols.includes(c.name));
  if (set.length) return cols.map((name) => set.find((c) => c.name === name) ?? { name, role: 'ignored' });
  return cols.map((name, i) => ({ name, role: 'searchable', key: i === 0 }));
}

/**
 * Splits one document with the given settings. The same function builds the preview and the index, so what the
 * preview shows is what a re-index produces.
 */
export function splitDocument(doc: SeedDocument, ingest: IngestSettings, parsing: Pick<ParsingSettings, 'tables'>, baseMeta: Record<string, string>, aiAllowed: boolean): { chunks: PreviewChunk[]; counts: SplitCounts; notes: string[] } {
  const notes: string[] = [];
  let strategies = [...ingest.strategies];
  if (!aiAllowed && strategies.some((s) => AI_STRATEGIES.includes(s))) {
    notes.push('Topic and FAQ steps wait for the knowledge owner’s approval, so this split leaves them out.');
    strategies = strategies.filter((s) => !AI_STRATEGIES.includes(s));
  }
  const has = (s: IngestStrategy) => strategies.includes(s);
  const clean = has('clean');
  let removedChars = 0;
  let modelCalls = 0;

  const sections: Piece[] = doc.sections.map((s) => ({ path: [s.heading], text: s.body, topic: s.topic, questions: s.questions }));
  if (doc.boilerplate?.length) {
    if (clean) {
      removedChars = doc.boilerplate.join(' ').length;
      notes.push(`Removed ${removedChars} characters of navigation, banners and footer.`);
    } else {
      sections[0] = { ...sections[0], text: `${doc.boilerplate[0]} ${sections[0].text}` };
      const last = sections.length - 1;
      sections[last] = { ...sections[last], text: `${sections[last].text} ${doc.boilerplate.slice(1).join(' ')}` };
    }
  }
  const rowsAsChunks = !!doc.table && has('table_rows');
  if (doc.table && !rowsAsChunks) {
    const t = doc.table;
    const text = parsing.tables ? t.rows.map((r) => t.columns.map((c, i) => `${c}: ${r[i]}`).join(' | ')).join('. ') : t.rows.map((r) => r.join(' ')).join(' ');
    sections.push({ path: ['Table'], text });
    notes.push(parsing.tables ? 'The table is split as text, so a lookup cannot match its fields. Use table rows for this document.' : 'Table extraction is off, so the table is flattened to text without column names.');
  }
  if (has('table_rows') && !doc.table) notes.push('This document has no table, so table rows does not apply to it.');

  // Split the text.
  let pieces: Piece[] = [];
  const splitter = SPLITTERS.find((s) => has(s));
  if (!splitter && !rowsAsChunks) notes.push('No splitting step chosen, so the text is split by structure.');
  if (splitter === 'fixed') {
    const words = sections.flatMap((s) => s.text.split(/\s+/).map((w) => ({ w, s })));
    const win = Math.max(20, Math.round(ingest.size / 1.3));
    const step = Math.max(10, Math.round((ingest.size - ingest.overlap) / 1.3));
    for (let i = 0; i < words.length; i += step) {
      const slice = words.slice(i, i + win);
      pieces.push({ path: [slice[0].s.path[0]], text: slice.map((x) => x.w).join(' '), topic: slice[0].s.topic });
      if (i + win >= words.length) break;
    }
  } else if (splitter === 'topic') {
    modelCalls += 1;
    const theme = (p: Piece) => (p.topic ?? plainHeading(p.path[0])).split('_')[0];
    for (const sec of sections) {
      const prev = pieces[pieces.length - 1];
      if (prev && theme(prev) === theme(sec) && tokensOf(prev.text + sec.text) <= ingest.size) {
        prev.text = `${prev.text} ${sec.text}`;
        prev.questions = [...(prev.questions ?? []), ...(sec.questions ?? [])];
      } else pieces.push({ ...sec, path: [`Topic: ${plainHeading(sec.path[0])}`] });
    }
    notes.push(`A model grouped ${sections.length} sections into ${pieces.length} topics.`);
  } else if (sections.length) {
    for (const s of sections) {
      const parts = groupSentences(s.text, ingest.size, ingest.overlap);
      parts.forEach((p, i) => pieces.push({ ...s, path: parts.length > 1 ? [`${s.path[0]} (part ${i + 1})`] : s.path, text: p }));
    }
  }
  if (rowsAsChunks && doc.table && pieces.every((p) => tokensOf(p.text) < 25)) pieces = pieces.filter((p) => tokensOf(p.text) >= 25);

  const chunks: PreviewChunk[] = pieces.map((p, i) => {
    const sectionPath = p.path;
    const prefix = has('context_headers') ? `${doc.title} › ${sectionPath.join(' › ')}\n` : '';
    const text = `${prefix}${p.text}`;
    const questions = has('faq') ? (p.questions?.length ? p.questions : generatedQuestions(doc, p.path[0], ingest.questionsPerSection)).slice(0, ingest.questionsPerSection) : undefined;
    if (questions) modelCalls += 1;
    const children = has('parent_child') && splitter !== 'fixed' ? groupSentences(p.text, ingest.childSize, 0) : undefined;
    return {
      index: i,
      kind: children ? 'parent' : 'chunk',
      text,
      indexedText: [text, ...(questions ?? []), ...(children ?? [])].join('\n'),
      sectionPath,
      questions,
      children,
      metadata: { ...baseMeta, ...(p.topic ? { topic: p.topic } : {}) },
      tokens: tokensOf(text),
    };
  });

  if (rowsAsChunks && doc.table) {
    const cols = rowColumns(doc, ingest.columns);
    const key = cols.find((c) => c.key) ?? cols.find((c) => c.role === 'searchable') ?? cols[0];
    doc.table.rows.forEach((r, ri) => {
      const val = (c: TableColumn) => r[doc.table!.columns.indexOf(c.name)] ?? '';
      const kept = cols.filter((c) => c.role !== 'ignored' && val(c));
      const text = kept.map((c) => `${c.name}: ${val(c)}`).join(' | ');
      const meta = Object.fromEntries(cols.filter((c) => c.role === 'metadata' && val(c)).map((c) => [snakeKey(c.name), val(c)]));
      const prefix = has('context_headers') ? `${doc.title} › Row ${ri + 2}\n` : '';
      chunks.push({
        index: chunks.length,
        kind: 'row',
        text: `${prefix}${text}`,
        indexedText: `${prefix}${cols.filter((c) => c.role === 'searchable').map((c) => `${c.name}: ${val(c)}`).join(' | ')}`,
        sectionPath: [`Row ${ri + 2}`, val(key)],
        metadata: { ...baseMeta, ...meta, row_key: val(key) },
        tokens: tokensOf(text),
      });
    });
    const ignored = cols.filter((c) => c.role === 'ignored').map((c) => c.name);
    notes.push(`${doc.table.rows.length} rows became records keyed by ${key.name}.${ignored.length ? ` Ignored: ${ignored.join(', ')}.` : ''}`);
  }
  if (has('parent_child')) notes.push('Small child chunks are indexed; a match returns the whole parent section.');
  if (has('context_headers')) notes.push('Each chunk starts with the document title and section path.');

  const questions = chunks.reduce((n, c) => n + (c.questions?.length ?? 0), 0);
  return {
    chunks,
    counts: {
      chunks: chunks.length,
      indexedUnits: chunks.reduce((n, c) => n + (c.children?.length ?? 1) + (c.questions?.length ?? 0), 0),
      questions,
      tokens: chunks.reduce((n, c) => n + c.tokens, 0),
      modelCalls,
      removedChars,
    },
    notes,
  };
}

// ---- metadata --------------------------------------------------------------

/** What "extract with AI" returns for a named field; deterministic so the demo is stable. */
export function extractWithAi(key: string, item: Pick<Item, 'title' | 'effectiveDate' | 'metadata'>): string | undefined {
  const t = item.title.toLowerCase();
  if (key === 'product')
    return /credit card/.test(t) ? 'credit_card' : /debit/.test(t) ? 'debit_card' : /wire|e-transfer/.test(t) ? 'wire' : /mortgage/.test(t) ? 'mortgage' : /small business/.test(t) ? 'small_business_loan' : /loan|lending|deferral|hardship|collections|eligibility|rate card|fee schedule/.test(t) ? 'personal_loan' : /card|chargeback|dispute/.test(t) ? 'cards' : undefined;
  if (key === 'jurisdiction') return /ontario/.test(t) ? 'ON' : /quebec/.test(t) ? 'QC' : /\bbc\b/.test(t) ? 'BC' : /alberta/.test(t) ? 'AB' : 'CA';
  if (key === 'effective_date') return item.effectiveDate;
  if (key === 'doc_class') return item.metadata.doc_class;
  return undefined;
}

/** Applies a source's mapping to an item at sync; AI extraction runs only once approved. */
export function applyMapping(item: Item, src: Source, aiAllowed: boolean) {
  for (const m of src.metadataMapping) {
    if (m.from.startsWith('static:')) item.metadata[m.key] = m.from.slice(7);
    else if (m.from.startsWith('ai:') && aiAllowed) {
      const v = extractWithAi(m.from.slice(3) || m.key, item);
      if (v) item.metadata[m.key] = v;
    }
  }
}

/** A required key's value on an item: governance fields first, then mapped metadata. */
export function fieldValue(item: Item, key: string): string | undefined {
  const k = snakeKey(key);
  if (k === 'owner') return item.owner || undefined;
  if (k === 'effective_date' || k === 'effective') return item.effectiveDate || undefined;
  if (k === 'version') return item.version || undefined;
  const v = item.metadata[k] ?? item.metadata[key];
  return v?.trim() ? v : undefined;
}

// ---- chunk counts ----------------------------------------------------------

const isTable = (mime: string) => mime.includes('spreadsheet') || mime === 'text/csv';

/** Chunk count for an item with no full body, from its size and the strategy. */
export function estimateChunkCount(item: Pick<Item, 'id' | 'sizeBytes' | 'mimeType'>, ingest: IngestSettings) {
  const tokens = Math.min(30_000, Math.max(400, Math.round(item.sizeBytes / 55)));
  if (isTable(item.mimeType) && ingest.strategies.includes('table_rows')) return 20 + (parseInt(digestOf(item.id).slice(0, 4), 16) % 180);
  let n = Math.max(1, Math.ceil(tokens / Math.max(60, ingest.size - ingest.overlap)));
  if (ingest.strategies.includes('topic')) n = Math.max(1, Math.round(n * 0.7));
  return Math.min(n, 120);
}

/** Chunks an item would have with these settings: real splits for full bodies, an estimate otherwise. */
export function chunkCountFor(item: Item, src: Pick<Source, 'ingest' | 'parsing' | 'metadataMapping'>) {
  const key = FEATURED[item.id];
  const doc = key ? docByKey(key) : undefined;
  return doc ? splitDocument(doc, src.ingest, src.parsing, {}, aiApproved(src)).counts.chunks : estimateChunkCount(item, src.ingest);
}

/** Changes whenever a re-index would build different chunks, including an AI step being approved. */
export const settingsDigest = (src: Pick<Source, 'ingest' | 'parsing' | 'metadataMapping'>) => {
  const { strategies, size, overlap, childSize, questionsPerSection, columns } = src.ingest;
  return digestOf(JSON.stringify({ strategies: [...strategies].sort(), size, overlap, childSize, questionsPerSection, columns, parsing: src.parsing, mapping: src.metadataMapping, ai: aiApproved(src) }));
};

// ---- rules -----------------------------------------------------------------

const globToRegex = (g: string) => new RegExp(`^${g.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*\*\/?/g, '§').replace(/\*/g, '[^/]*').replace(/§/g, '.*').replace(/\?/g, '.')}$`, 'i');
const sizeOf = (v: string) => {
  const m = v.trim().match(/^([\d.]+)\s*(kb|mb|gb)?$/i);
  return m ? Number(m[1]) * ({ kb: 1e3, mb: 1e6, gb: 1e9 }[(m[2] ?? 'mb').toLowerCase() as 'kb' | 'mb' | 'gb'] ?? 1e6) : NaN;
};

export function ruleMatches(r: Rule, it: Pick<Item, 'path' | 'title' | 'mimeType' | 'modifiedAt' | 'sizeBytes'>) {
  const v = r.value.trim();
  if (!v) return false;
  switch (r.field) {
    case 'path':
      return globToRegex(v).test(it.path) || globToRegex(`**/${v}`).test(it.path);
    case 'title':
      return it.title.toLowerCase().includes(v.toLowerCase());
    case 'mime':
      return it.mimeType.toLowerCase().includes(v.toLowerCase());
    case 'modifiedAfter':
      return !Number.isNaN(Date.parse(v)) && new Date(it.modifiedAt) > new Date(v);
    case 'sizeUnder':
      return it.sizeBytes < sizeOf(v);
  }
}

const FIELD_WORDS: Record<Rule['field'], string> = { path: 'path matches', title: 'title contains', mime: 'type is', modifiedAfter: 'modified after', sizeUnder: 'size under' };
export const ruleLabel = (r: Rule) => `${r.kind === 'include' ? 'Include' : 'Exclude'} ${FIELD_WORDS[r.field]} ${r.value}`;

/** Why the rules leave an item out, or undefined when they admit it. Exclude rules win; with any include rule, an item must match one. */
export function excludedByRules(rules: Rule[], it: Item) {
  const ex = rules.find((r) => r.kind === 'exclude' && ruleMatches(r, it));
  if (ex) return `Excluded by rule: ${ruleLabel(ex).replace(/^Exclude /, '')}`;
  const inc = rules.filter((r) => r.kind === 'include' && r.value.trim());
  if (inc.length && !inc.some((r) => ruleMatches(r, it))) return `Not matched by any include rule (${inc.map((r) => ruleLabel(r).replace(/^Include /, '')).join('; ')})`;
  return undefined;
}

/** Versions of one document share a family: the title without year, version or "superseded" markers. */
export const familyOf = (title: string) =>
  title
    .toLowerCase()
    .replace(/\s*\((20\d\d|superseded)\)/g, '')
    .replace(/\bv\d+(\.\d+)?\b/g, '')
    .replace(/\s+/g, ' ')
    .trim();

// ---- governance ------------------------------------------------------------

/**
 * Recomputes what the index may serve after anything that changes it: rules, versions, duplicates and held
 * items. Runs on load and after every source, item or knowledge base write.
 */
export function govern(items: Item[], sources: Source[], kbs: KnowledgeBase[]) {
  const srcById = new Map(sources.map((s) => [s.id, s]));
  const today = new Date().toISOString().slice(0, 10);

  // Rules.
  for (const it of items) {
    const src = srcById.get(it.sourceId);
    if (!src || it.status === 'deleted') continue;
    const why = excludedByRules(src.rules, it);
    if (why) Object.assign(it, { status: 'excluded', excludedBy: why });
    else if (it.status === 'excluded' && it.excludedBy) Object.assign(it, { status: 'pending', excludedBy: undefined });
  }

  // Versions within a source.
  const families = new Map<string, Item[]>();
  for (const it of items) {
    if (it.status === 'excluded' || it.status === 'deleted') continue;
    const k = `${it.sourceId}|${it.family}`;
    families.set(k, [...(families.get(k) ?? []), it]);
  }
  for (const group of families.values()) {
    group.sort((a, b) => b.effectiveDate.localeCompare(a.effectiveDate));
    let current: Item | undefined;
    for (const it of group) {
      if (it.effectiveDate > today) Object.assign(it, { versionStatus: 'scheduled', supersededBy: undefined });
      else if (!current) {
        current = it;
        Object.assign(it, { versionStatus: 'current', supersededBy: undefined });
      } else Object.assign(it, { versionStatus: 'superseded', supersededBy: current.version });
    }
  }

  // Identical content is indexed once; the first item holding it is the one searched.
  const byDigest = new Map<string, Item>();
  for (const it of items) {
    it.duplicateOf = undefined;
    it.alsoIn = undefined;
  }
  for (const it of items) {
    if (it.status === 'excluded' || it.status === 'deleted' || it.status === 'failed') continue;
    const first = byDigest.get(it.digest);
    if (!first) {
      byDigest.set(it.digest, it);
      continue;
    }
    const name = (sid: string) => srcById.get(sid)?.name ?? sid;
    it.duplicateOf = { itemId: first.id, title: first.title, sourceName: name(first.sourceId) };
    first.alsoIn = [...(first.alsoIn ?? []), { itemId: it.id, title: it.title, sourceName: name(it.sourceId) }];
  }

  // Held for required metadata.
  for (const it of items) {
    if (it.status !== 'indexed' && it.status !== 'held') continue;
    const readers = kbs.filter((k) => k.sources.some((l) => l.sourceId === it.sourceId));
    const missingBy = readers.map((k) => ({ k, missing: k.metadataProfile.required.filter((key) => !fieldValue(it, key)) })).filter((x) => x.missing.length);
    if (missingBy.length) {
      it.status = 'held';
      it.held = { missing: Array.from(new Set(missingBy.flatMap((x) => x.missing))), kbNames: missingBy.map((x) => x.k.name) };
      // A held item produces no index units, so it reports no chunks (spec 5.15.8).
      it.chunkCount = 0;
    } else {
      const src = srcById.get(it.sourceId);
      if (it.status === 'held' && src) it.chunkCount = chunkCountFor(it, src);
      it.status = 'indexed';
      it.held = undefined;
    }
  }

  for (const s of sources) {
    const own = items.filter((it) => it.sourceId === s.id);
    if (!own.length) continue;
    s.itemsIndexed = own.filter((it) => it.status === 'indexed' || it.status === 'partial').length;
    s.itemsFailed = own.filter((it) => it.status === 'failed').length;
  }
}

// ---- samples and preview ---------------------------------------------------

export function listSamples(sources: Source[], sourceId?: string): SampleDocument[] {
  const rows = SAMPLES.map((s) => {
    const doc = docByKey(s.key)!;
    return { s, doc };
  });
  const own = sourceId ? rows.filter((r) => r.s.sourceId === sourceId) : [];
  const ordered = [...own, ...rows.filter((r) => !own.includes(r))];
  return ordered.map(({ s, doc }) => ({
    id: s.key,
    title: s.version ? `${doc.title} ${s.version}` : doc.title,
    sourceName: sources.find((x) => x.id === s.sourceId)?.name ?? s.sourceName,
    format: doc.format,
    version: s.version,
    effectiveDate: s.effectiveDate,
    columns: doc.table?.columns,
  }));
}

/** Values a sample shows for `field:` mappings, as the connected app would supply them. */
const SAMPLE_FIELDS = (doc: SeedDocument): Record<string, string> => ({
  Dept: 'Card Services',
  Owner: doc.docClass === 'playbook' ? 'Fraud Strategy' : 'Card Services',
  Space: 'FRAUD',
  Label: 'fraud-strategy',
  'Effective date': '2026-07-01',
  'Filename prefix': doc.title.split(' — ')[0],
  'URL path segment 2': doc.metadata?.product ?? 'overview',
  'Path segment 2': 'models',
  'Product line': doc.metadata?.product ?? '',
});

export function previewSplit(input: SplitPreviewInput): SplitPreview {
  const doc = SEED_DOCUMENTS.find((d) => d.key === input.sampleId);
  if (!doc) throw new ApiError('That sample document no longer exists. Choose another.', 404);
  validateIngest(input.ingest);
  const fields = SAMPLE_FIELDS(doc);
  const meta: Record<string, string> = { doc_class: doc.docClass };
  for (const m of input.metadataMapping ?? []) {
    if (!m.key.trim()) continue;
    if (m.from.startsWith('static:')) meta[m.key] = m.from.slice(7);
    else if (m.from.startsWith('field:')) meta[m.key] = fields[m.from.slice(6)] ?? '';
    else if (m.from.startsWith('ai:')) meta[m.key] = extractWithAi(m.from.slice(3) || m.key, { title: doc.title, effectiveDate: '2026-07-01', metadata: { doc_class: doc.docClass } }) ?? '';
  }
  // The preview runs AI steps so they can be judged before anyone approves them.
  const res = splitDocument(doc, input.ingest, input.parsing, meta, true);
  const aiExtract = (input.metadataMapping ?? []).filter((m) => m.from.startsWith('ai:')).length;
  if (aiExtract) res.counts.modelCalls += 1;
  return { sampleId: doc.key, title: doc.title, strategies: input.ingest.strategies, ...res };
}
