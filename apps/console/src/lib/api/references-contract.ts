import type { RefKind, ReferenceContext, ReferenceSearch } from '@/lib/types/references';

/**
 * What an agent brief or a skill step can point at (agents-service `GET /v1/references`): the team's tools, knowledge
 * bases, skills, agents and workflows, grouped, with only the kinds the person may view.
 */
export interface ReferencesApi {
  /** The `@` menu: groups matching `search`, or one group paged with `kind`. `limit` is 1 to 25 a group, 8 when left out. */
  search(context: ReferenceContext, params: { search: string; kind?: RefKind; limit?: number }): Promise<ReferenceSearch>;
  /**
   * The current names of stored references, each id as `kind:id`, at most 100. One that is not found, not visible to
   * the person or no longer offered is left out of the answer, and the document draws it as Missing.
   */
  labels(context: ReferenceContext, ids: string[]): Promise<ReferenceSearch>;
}
