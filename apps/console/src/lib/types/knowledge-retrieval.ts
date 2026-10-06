/**
 * How a question becomes chunks and an answer: query modes, rewriting, filters with runtime values, answer
 * shapes, multi-knowledge-base precedence and the trace that explains each result.
 */

/**
 * `keyword` ranks exact terms (codes such as 12.6 or form numbers rank high), `semantic` ranks meaning,
 * `hybrid` weights the two, `table_lookup` matches fields of table rows, and `as_of` answers from the
 * versions in force on a date.
 */
export type QueryMode = 'semantic' | 'keyword' | 'hybrid' | 'table_lookup' | 'as_of';

export type RewriteMode = 'off' | 'rewrite' | 'expand';

export type FilterOp = 'is' | 'is_not' | 'one_of' | 'before' | 'after' | 'exists';

/**
 * One metadata condition. `value` is a literal (`credit_card`, `2026-01-01`, `ON, QC` for one of) or a runtime
 * variable in braces (`{case.product}`); `preview` stands in for the variable outside a live run.
 */
export interface FilterCondition {
  id: string;
  key: string;
  op: FilterOp;
  value: string;
  preview?: string;
}

export interface FilterGroup {
  match: 'all' | 'any';
  conditions: FilterCondition[];
}

/** `chunks` returns passages for a workflow step to use; the other two write an answer. */
export type AnswerShape = 'chunks' | 'answer_with_citations' | 'extractive_quote';

/** Values for runtime variables, keyed by the variable as written (`{case.product}`). */
export type RuntimeValues = Record<string, string>;

export interface ScoreBreakdown {
  keyword: number;
  semantic: number;
  /** The mode's ordering score before rerank: keyword, semantic, or in hybrid the weighted reciprocal rank fusion. */
  fused: number;
  reranked?: number;
  /** Positions in the semantic and keyword lists that hybrid fuses; absent when the list did not include the passage. */
  semanticRank?: number;
  keywordRank?: number;
}

export type CandidateOutcome = 'returned' | 'below_threshold' | 'over_limit' | 'lost_precedence' | 'superseded' | 'not_in_force';

export type CandidateFlag = 'superseded' | 'stale' | 'scheduled' | 'deduplicated' | 'connection_revoked';

export interface TraceCandidate {
  chunkId: string;
  documentId: string;
  documentTitle: string;
  sourceName: string;
  kbName: string;
  location: string;
  version: string;
  effectiveDate: string;
  text: string;
  scores: ScoreBreakdown;
  /** The score the threshold and order use. */
  final: number;
  outcome: CandidateOutcome;
  flags: CandidateFlag[];
  /** The phrasing that scored it highest when the question was rewritten or expanded. */
  matchedQuery?: string;
  /** Plain-language reason for the outcome, such as the precedence rule or the other sources holding the same text. */
  note?: string;
}

export interface PrecedenceDecision {
  rule: string;
  kbName: string;
  winner: string;
  loser: string;
}

export interface ResolvedFilter {
  key: string;
  op: FilterOp;
  value: string;
  /** The value used: the literal, the runtime value, or the preview when no run supplied one. */
  resolved: string;
  from: 'literal' | 'runtime' | 'preview' | 'unset';
}

export interface RetrievalTrace {
  question: string;
  queries: { text: string; kind: 'original' | 'rewritten' | 'expanded' }[];
  mode: QueryMode;
  hybridWeight: number;
  rerank: boolean;
  asOf?: string;
  kbs: { id: string; name: string }[];
  /** Whose saved settings ran, when the caller did not send its own. */
  settingsFrom: string;
  filters: { match: 'all' | 'any'; conditions: ResolvedFilter[]; tagsInclude: string[]; tagsExclude: string[]; removed: number };
  /** Documents that would have matched but the run-as person cannot read. Present only on a run-as preview. */
  hiddenByPermissions?: number;
  runAsName?: string;
  /** Chunks scored after permissions and filters. */
  searched: number;
  candidates: TraceCandidate[];
  threshold: number;
  chunkLimit: number;
  precedence: PrecedenceDecision[];
  timings: { rewriteMs: number; searchMs: number; rerankMs: number; synthesisMs: number };
}

/** A table row returned by `table_lookup`. */
export interface TableRowHit {
  documentId: string;
  documentTitle: string;
  version: string;
  row: number;
  key: string;
  values: Record<string, string>;
  /** Columns the question matched. */
  matched: string[];
  score: number;
}
