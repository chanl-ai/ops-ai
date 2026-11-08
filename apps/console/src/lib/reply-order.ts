// The order a reply reads in (chat presentation, "a run of calls, collapsed"): the plan's checklist first, the reply's
// plain calls folded into one quiet line under it, then the calls that are themselves cards (a Connect card, a record
// card), then the other cards, then the text. With no plan, one plain call keeps its row and two or more fold into the
// line. Loading a skill is the assistant's own housekeeping: it stays in the call log and never shows in the reply.

/** The id of a reply's plan part (agents-service chat_history.PLAN_PART). */
export const PLAN_PART = 'wp_plan';
/** Calls the person never sees in the reply. */
export const HOUSEKEEPING = new Set(['load_skill']);

export interface OrderedReply<C, P> {
  plan?: P;
  /** Plain calls shown as one quiet line ("3 steps · Salesforce"), expandable to their rows. */
  folded: C[];
  /** Calls shown as they are: cards, or the one plain call of a reply without a plan. */
  shown: C[];
  /** The reply's other parts, in their order. */
  parts: P[];
}

export function orderReply<C extends { id: string; name: string }, P extends { id: string }>(
  calls: C[],
  parts: P[],
  isCard: (c: C) => boolean,
): OrderedReply<C, P> {
  const plan = parts.find((p) => p.id === PLAN_PART);
  const visible = calls.filter((c) => !HOUSEKEEPING.has(c.name));
  const cards = visible.filter(isCard);
  const plain = visible.filter((c) => !isCard(c));
  const fold = !!plan || plain.length >= 2;
  return {
    plan,
    folded: fold ? plain : [],
    shown: visible.filter((c) => isCard(c) || !fold),
    parts: parts.filter((p) => p.id !== PLAN_PART),
  };
}

/** The quiet line for folded calls: how many steps and which systems, as "3 steps · Salesforce". */
export function foldedLine(calls: { server: string }[]): string {
  const systems = [...new Set(calls.map((c) => c.server).filter(Boolean))];
  const steps = `${calls.length} ${calls.length === 1 ? 'step' : 'steps'}`;
  return systems.length ? `${steps} · ${systems.join(', ')}` : steps;
}
