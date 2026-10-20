/**
 * The Wiki: one copy of every fact agents read, as pages and documents with versions and a verified mark.
 * Knowledge bases are the retrieval layer over it; collections decide who may read a page.
 */

/** Where a page came from. `remembered` is written by an agent and stays unverified until a person marks it. */
export type WikiProvenance = 'external' | 'file' | 'page' | 'remembered';

export type WikiGate = 'open' | 'team' | 'gated';

export interface WikiPage {
  id: string;
  title: string;
  collection: string;
  provenance: WikiProvenance;
  /** The connection, file or agent it came from, e.g. "SharePoint · Lending" or "Mortgage Intake". */
  origin: string;
  version: number;
  /** Date it was last verified; null when never verified. */
  verifiedAt: string | null;
  verifiedBy: string | null;
  owner: string;
  updatedAt: string;
  updatedBy: string;
  /** Knowledge-base answers in the last 30 days that cited it. */
  citedBy: number;
  /** The source it was synced from has changed since this version. */
  drifted: boolean;
}

export interface WikiVersion {
  version: number;
  at: string;
  by: string;
  note: string;
}

export interface WikiPageDetail extends WikiPage {
  excerpt: string;
  versions: WikiVersion[];
  /** Set when drifted: what changed upstream. */
  driftNote?: string;
}

export type WikiView = 'all' | 'needs_verification' | 'remembered' | 'drifted';
export type WikiViewCounts = Record<WikiView, number>;
export type WikiFilters = { collection?: string[]; provenance?: string[] };

export interface WikiCollection {
  id: string;
  name: string;
  pages: number;
  gate: WikiGate;
  /** Who may read it, in words, e.g. "Lending Ops and Compliance". */
  audience: string;
  /** Knowledge bases that index it. */
  knowledgeBases: string[];
}
