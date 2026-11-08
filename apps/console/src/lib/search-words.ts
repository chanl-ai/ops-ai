/**
 * How a list search matches, the same as the server's (agents-service CaseStore.list): every word of the query, in any
 * order and ignoring case, each found in one of the record's searched texts.
 */
export function hasEveryWord(texts: (string | null | undefined)[], query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const held = texts.filter((t): t is string => !!t).map((t) => t.toLowerCase());
  return words.every((w) => held.some((t) => t.includes(w)));
}
