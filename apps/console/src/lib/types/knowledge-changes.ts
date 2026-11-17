import type { OpsAI } from '@chanl-ai/ops-ai';

import type { ListParams } from './query';

type Kb = OpsAI['raw']['kb'];
type Reply<K extends keyof Kb> = Awaited<ReturnType<Kb[K]>>;

type ServedChange = Reply<'changes_get_change'>;
export type ChangeOrigin = ServedChange['origin'];
export type ChangeStatus = ServedChange['status'];
export type TrustState = ServedChange['trust'];

/** An FAQ draft: the pair, the passage it quotes, and the words of its answer the passage never uses. */
export interface FaqDraft {
  question: string;
  answer: string;
  quote: string;
  sectionPath: string[];
  /** Words of the answer its passage lacks (common words aside): a sign the answer says more than its source. */
  addsWords?: string[];
}

/** Another document that says something different about the same thing. */
export interface ChangeConflict {
  documentId: string;
  documentTitle: string;
  sourceName: string;
  passage: string;
  /** How it was settled; absent until the owner resolves it. */
  resolution?: 'supersede_other' | 'keep_both';
}

/** A workflow whose runs cited the changed passage; its tests re-run when the change is approved. */
export interface ChangeCitation {
  workflowId: string;
  workflowName: string;
  citations30d: number;
  tests: number;
}

/**
 * A proposed edit to one passage of a knowledge document, as kb-service answers it; nothing reaches agents until the
 * document's owner approves it. kb-service types `citedBy` and `faq` as free-form objects, and does not return `conflict`,
 * `decisionReason` or `retest` yet; the console reads those three, so they stay here as view-only fields.
 */
export type KnowledgeChange = Omit<ServedChange, 'citedBy' | 'faq'> & {
  citedBy: ChangeCitation[];
  /** Set on an FAQ draft. */
  faq?: FaqDraft | null;
  conflict?: ChangeConflict;
  decisionReason?: string;
  /** Set on approval: the citing workflows' tests that were queued. */
  retest?: { tests: number; workflows: string[] };
};

export type ChangeView = 'open' | 'mine' | 'resolved' | 'all';
export type ChangeFilters = { origin?: string[]; kbId?: string[]; owner?: string[] };
export type ChangeListParams = ListParams<ChangeFilters> & { view: ChangeView; kbId?: string };

export interface ChangeViewCounts {
  mine: number;
  open: number;
  conflicts: number;
  resolved: number;
}

/** Approve or reject FAQ drafts, one or many, as `POST /v1/knowledge-changes/decide` takes it. */
export interface ChangeDecisionInput {
  ids: string[];
  decision: 'approve' | 'reject';
}
