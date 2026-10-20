import type { KnowledgeBaseRow } from '@/lib/types/knowledge';

type Citing = Pick<KnowledgeBaseRow, 'agentNames' | 'agentsElsewhere' | 'agentsKnown'>;

/**
 * What deleting a knowledge base says, on the list and the detail alike. The name must be typed whenever an agent may
 * cite the base: named, in another team, or not known because agents-service did not answer.
 */
export function retireBase(kb: Citing): { requireName: boolean; description: string } {
  const elsewhere = kb.agentsElsewhere ?? 0;
  const kept = 'Sources and their items are kept.';
  const after = 'stop citing it and keep answering from their other knowledge bases.';
  if (kb.agentsKnown === false) return { requireName: true, description: `Which agents cite this knowledge base is unknown right now; any that do ${after} ${kept}` };
  if (kb.agentNames.length || elsewhere) {
    const who = [...kb.agentNames, ...(elsewhere ? [`${elsewhere} agent${elsewhere === 1 ? '' : 's'} in other teams`] : [])].join(', ');
    return { requireName: true, description: `${who} cite this knowledge base; they ${after} ${kept}` };
  }
  return { requireName: false, description: `The index and its retrieval settings are removed. ${kept}` };
}
