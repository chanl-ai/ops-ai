import type { KnowledgeBaseRow } from '@/lib/types/knowledge';

type Citing = Pick<KnowledgeBaseRow, 'agentNames' | 'agentsKnown'>;

/**
 * What deleting a knowledge base says, on the list and the detail alike. The name must be typed whenever an agent may
 * cite the base: named, or not known because agents-service did not answer. A base is its team's alone, so no other
 * team's agent cites it.
 */
export function retireBase(kb: Citing): { requireName: boolean; description: string } {
  const kept = 'Sources and their items are kept.';
  const after = 'stop citing it and keep answering from their other knowledge bases.';
  if (kb.agentsKnown === false) return { requireName: true, description: `Which agents cite this knowledge base is unknown right now; any that do ${after} ${kept}` };
  if (kb.agentNames.length) {
    const who = kb.agentNames.join(', ');
    return { requireName: true, description: `${who} cite this knowledge base; they ${after} ${kept}` };
  }
  return { requireName: false, description: `The index and its retrieval settings are removed. ${kept}` };
}
