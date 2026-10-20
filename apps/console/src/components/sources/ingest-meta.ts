import type { IngestPresetId, IngestSettings, IngestStrategy, TableColumn } from '@/lib/types/knowledge-ingest';

export interface StrategyMeta {
  value: IngestStrategy;
  label: string;
  description: string;
  /** Splitting steps are exclusive; the rest add to a split. */
  splitter?: boolean;
  /** Calls a model at ingest, so the knowledge owner approves it. */
  ai?: boolean;
}

export const STRATEGY_META: StrategyMeta[] = [
  { value: 'structure', label: 'Structure', description: 'Split at headings and sections; long sections split at sentences.', splitter: true },
  { value: 'fixed', label: 'Fixed size', description: 'Equal windows of tokens with overlap, ignoring headings.', splitter: true },
  { value: 'topic', label: 'Topic', description: 'A model groups neighbouring sections that cover the same topic.', splitter: true, ai: true },
  { value: 'faq', label: 'FAQ questions', description: 'A model writes questions each section answers; questions are searched, the section is returned.', ai: true },
  { value: 'context_headers', label: 'Context headers', description: 'Starts every chunk with the document title and section path.' },
  { value: 'parent_child', label: 'Parent and child', description: 'Small chunks are searched; a match returns the whole parent section.' },
  { value: 'table_rows', label: 'Table rows', description: 'One record per row; columns are searched, kept as metadata or ignored.' },
  { value: 'clean', label: 'Clean', description: 'Strips HTML, navigation, cookie banners and footers before splitting.' },
];

export const strategyMeta = (s: IngestStrategy) => STRATEGY_META.find((m) => m.value === s)!;

export const RATE_TABLE_COLUMNS: TableColumn[] = [
  { name: 'Product', role: 'searchable', key: true },
  { name: 'Band', role: 'searchable' },
  { name: 'Origination fee', role: 'metadata' },
  { name: 'Minimum', role: 'metadata' },
  { name: 'Maximum', role: 'metadata' },
  { name: 'Secured', role: 'searchable' },
  { name: 'Effective', role: 'metadata' },
  { name: 'Notes', role: 'ignored' },
];

export const INGEST_PRESETS: { id: Exclude<IngestPresetId, 'custom'>; label: string; description: string; strategies: IngestStrategy[]; columns?: TableColumn[] }[] = [
  { id: 'policy_manual', label: 'Policy manual', description: 'Sections with their title and path; small chunks searched, the section returned.', strategies: ['structure', 'context_headers', 'parent_child'] },
  { id: 'help_centre', label: 'Help centre', description: 'Web articles cleaned of page furniture, with generated questions.', strategies: ['clean', 'structure', 'faq'] },
  { id: 'rate_table', label: 'Rate table', description: 'Each row a record keyed by product; fees kept as filterable values.', strategies: ['table_rows'], columns: RATE_TABLE_COLUMNS },
  { id: 'email_templates', label: 'Email templates', description: 'Subject, body and sign-off as sections, each with its title and path.', strategies: ['structure', 'context_headers'] },
];

export const PRESET_LABEL: Record<IngestPresetId, string> = { policy_manual: 'Policy manual', help_centre: 'Help centre', rate_table: 'Rate table', email_templates: 'Email templates', custom: 'Custom' };

/** Applies a preset's strategies (and columns for a rate table), keeping sizes and approval. */
export function applyPreset(i: IngestSettings, id: IngestPresetId): IngestSettings {
  const p = INGEST_PRESETS.find((x) => x.id === id);
  if (!p) return { ...i, preset: 'custom' };
  return { ...i, preset: p.id, strategies: [...p.strategies], columns: p.columns ? p.columns.map((c) => ({ ...c })) : i.columns };
}

/** Why a strategy cannot be added to the current set, or undefined when it can. */
export function strategyBlocker(current: IngestStrategy[], s: IngestStrategy): string | undefined {
  if (current.includes(s)) return undefined;
  const meta = strategyMeta(s);
  const splitter = current.find((x) => strategyMeta(x).splitter);
  if (meta.splitter && splitter) return `Uses ${strategyMeta(splitter).label.toLowerCase()} splitting; choose one way to split.`;
  if (s === 'parent_child' && current.includes('fixed')) return 'Needs sections, so it works with structure or topic splitting.';
  if (s === 'fixed' && current.includes('parent_child')) return 'Parent and child needs sections; remove it to split by fixed size.';
  return undefined;
}

export const isAiStrategy = (st: IngestStrategy) => !!strategyMeta(st).ai;

export const defaultIngest = (): IngestSettings => ({
  preset: 'policy_manual',
  strategies: ['structure', 'context_headers', 'parent_child'],
  size: 512,
  overlap: 50,
  childSize: 40,
  questionsPerSection: 2,
  columns: [],
  model: 'ingest-standard',
  approval: { status: 'not_needed', approvedSteps: [] },
});
