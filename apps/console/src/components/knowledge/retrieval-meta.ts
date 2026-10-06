import type { AnswerShape, CandidateOutcome, FilterOp, QueryMode, RewriteMode } from '@/lib/types/knowledge-retrieval';

export const QUERY_MODES: { value: QueryMode; label: string; description: string }[] = [
  { value: 'hybrid', label: 'Hybrid', description: 'Weighted mix of meaning and exact terms.' },
  { value: 'semantic', label: 'Semantic', description: 'Matches meaning and synonyms; ignores codes.' },
  { value: 'keyword', label: 'Keyword', description: 'Exact terms; codes like 12.6 or NF-2207 rank high.' },
  { value: 'table_lookup', label: 'Table lookup', description: 'Matches fields of table rows and amount bands; returns rows.' },
  { value: 'as_of', label: 'As of a date', description: 'Only versions in force on the date.' },
];
export const MODE_LABEL = Object.fromEntries(QUERY_MODES.map((m) => [m.value, m.label])) as Record<QueryMode, string>;

export const ANSWER_SHAPES: { value: AnswerShape; label: string; description: string }[] = [
  { value: 'answer_with_citations', label: 'Answer with citations', description: 'A written answer; each claim cites its passage.' },
  { value: 'extractive_quote', label: 'Quotes', description: 'The exact sentences, quoted, with where they come from.' },
  { value: 'chunks', label: 'Chunks only', description: 'No writing; the passages go to a workflow step.' },
];
export const SHAPE_LABEL = Object.fromEntries(ANSWER_SHAPES.map((m) => [m.value, m.label])) as Record<AnswerShape, string>;

export const REWRITE_LABEL: Record<RewriteMode, string> = { off: 'Off', rewrite: 'Rewrite the question', expand: 'Expand to several phrasings' };

export const FILTER_OPS: { value: FilterOp; label: string }[] = [
  { value: 'is', label: 'is' },
  { value: 'is_not', label: 'is not' },
  { value: 'one_of', label: 'is one of' },
  { value: 'before', label: 'before' },
  { value: 'after', label: 'after' },
  { value: 'exists', label: 'exists' },
];
export const OP_LABEL = Object.fromEntries(FILTER_OPS.map((o) => [o.value, o.label])) as Record<FilterOp, string>;

/** Variables a workflow run or chat supplies; the default stands in when previewing. */
export const RUNTIME_VARIABLES: { name: string; label: string; example: string }[] = [
  { name: '{case.product}', label: 'Case product', example: 'credit_card' },
  { name: '{case.region}', label: 'Case region', example: 'ON' },
  { name: '{user.team}', label: 'Signed-in user’s team', example: 'Card Services' },
  { name: '{case.opened_at}', label: 'Case opened on', example: '2026-09-15' },
];

export const isRuntime = (v: string) => /^\{[a-z_.]+\}$/i.test(v.trim());
/** Runtime variables a filter value mentions, including inside a one-of list. */
export const variablesIn = (v: string) => v.split(',').map((x) => x.trim()).filter(isRuntime);

export const OUTCOME_LABEL: Record<CandidateOutcome, string> = {
  returned: 'Returned',
  below_threshold: 'Below threshold',
  over_limit: 'Over chunk limit',
  lost_precedence: 'Lost on precedence',
  superseded: 'Superseded',
  not_in_force: 'Not in force',
};
