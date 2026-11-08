// A reply's parts as a streamed part arrives: a part whose id the reply already holds is redrawn in place (the plan,
// which each plan call sends again), any other part is added after the rest.
import type { MessagePart } from './types/widgets';

export function withPart(parts: MessagePart[] | undefined, part: MessagePart): MessagePart[] {
  const held = parts ?? [];
  const at = held.findIndex((p) => p.id === part.id);
  return at < 0 ? [...held, part] : held.map((p, i) => (i === at ? part : p));
}
