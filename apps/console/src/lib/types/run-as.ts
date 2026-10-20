import type { Sensitivity } from './knowledge';

/**
 * A staff member or role a test can run as. Answers and tool results are limited to what this principal
 * may see and do, so a tester sees what that person would get in production.
 */
export interface RunAsPrincipal {
  id: string;
  kind: 'person' | 'role';
  name: string;
  /** Job title for a person; who holds it for a role. */
  title: string;
  team: string;
  /** Knowledge collections this principal can read; `null` means every collection. */
  collections: string[] | null;
  /** Highest document sensitivity this principal can read. */
  clearance: Sensitivity;
  /** Tools this principal may have an agent call for them; `null` means every tool. */
  tools: string[] | null;
  /** Plain-language entitlements shown in the context bar. */
  entitlements: string[];
}

/** What permissions removed from one answer or test turn. */
export interface PermissionScope {
  runAsId: string;
  runAsName: string;
  hiddenDocuments: number;
  /** Collections the hidden documents belong to. */
  hiddenCollections: string[];
  /** Tools the principal is not entitled to, which the turn could not call. */
  blockedTools: string[];
}
