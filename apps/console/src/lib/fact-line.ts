/** Joins the facts of a header or caption with a middle dot. An empty fact is left out, so it leaves no stray dot. */
export function factLine(facts: ReadonlyArray<string | null | undefined>): string {
  return facts
    .map((f) => f?.trim())
    .filter(Boolean)
    .join(' · ');
}

/** A knowledge base's header line: its description (`lead`, carrying the dot to what follows) and the smaller facts. */
export function baseHeader(kb: { description?: string | null; collections: string[]; synced: string }): { lead: string | null; facts: string } {
  return {
    lead: kb.description?.trim() ? `${kb.description.trim()} · ` : null,
    facts: factLine([kb.collections.length ? `Collections: ${kb.collections.join(', ')}` : 'All collections', `synced ${kb.synced}`]),
  };
}
