import type { ListParams } from './query';

/** Where a proposed knowledge edit came from; `generated_faq` is an FAQ draft a source's FAQ step wrote. */
export type ChangeOrigin = 'curation' | 'agent_fix' | 'source_sync' | 'generated_faq';
/** A draft is `pending` until decided; `source_changed` when its section changed after it was drafted or approved. */
export type ChangeStatus = 'pending' | 'approved' | 'rejected' | 'applied' | 'superseded' | 'source_changed';
export type TrustState = 'verified' | 'changed' | 'unverified' | 'draft' | 'source_changed';

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
 * A proposed edit to one passage of a knowledge document. Nothing reaches agents until the document's owner
 * approves it.
 */
export interface KnowledgeChange {
  id: string;
  summary: string;
  origin: ChangeOrigin;
  /** Person, agent or source that proposed it. */
  proposedBy: string;
  rationale: string;
  documentId: string;
  documentTitle: string;
  sourceId: string;
  sourceName: string;
  section: string;
  kbs: { id: string; name: string }[];
  fromVersion: string;
  toVersion: string;
  before: string;
  after: string;
  trust: TrustState;
  freshness: 'fresh' | 'stale' | 'no_schedule';
  reviewBy: string;
  conflict?: ChangeConflict;
  citedBy: ChangeCitation[];
  /** Owner group or person who may decide. */
  owner: string;
  /** Computed for the current user and team. */
  canDecide: boolean;
  status: ChangeStatus;
  createdAt: string;
  decidedAt?: string;
  decidedBy?: string;
  decisionReason?: string;
  /** Set on approval: the citing workflows' tests that were queued. */
  retest?: { tests: number; workflows: string[] };
  /** Set on an FAQ draft. */
  faq?: FaqDraft | null;
}

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
