import type { Agent, AgentLimits } from '@/lib/types/domain';

/**
 * The fields that grant `add` to and remove `remove` from the agent as just read, or null when its list already is
 * that. A removed tool also leaves the tools callers may switch off: agents-service refuses limits that name a tool
 * the version does not grant.
 */
export function toolChange(agent: Pick<Agent, 'toolIds' | 'limits'>, { add = [], remove = [] }: { add?: string[]; remove?: string[] }): { toolIds: string[]; limits?: AgentLimits } | null {
  const toolIds = [...agent.toolIds.filter((t) => !remove.includes(t)), ...add.filter((t) => !agent.toolIds.includes(t))];
  if (toolIds.length === agent.toolIds.length && toolIds.every((t, i) => t === agent.toolIds[i])) return null;
  const switchable = agent.limits.switchableToolIds.filter((t) => toolIds.includes(t));
  return switchable.length === agent.limits.switchableToolIds.length ? { toolIds } : { toolIds, limits: { ...agent.limits, switchableToolIds: switchable } };
}

/**
 * The fields that add `add` to and remove `remove` from the agent's knowledge bases as just read, or null when its
 * list already is that. An added base also joins the bases callers may choose from: agents-service refuses limits
 * that leave out one of the agent's own.
 */
export function knowledgeChange(agent: Pick<Agent, 'collections' | 'limits'>, { add = [], remove = [] }: { add?: string[]; remove?: string[] }): { collections: string[]; limits?: AgentLimits } | null {
  const collections = [...agent.collections.filter((k) => !remove.includes(k)), ...add.filter((k) => !agent.collections.includes(k))];
  if (collections.length === agent.collections.length && collections.every((k, i) => k === agent.collections[i])) return null;
  const allowed = agent.limits.allowedKnowledgeBaseIds;
  const missing = collections.filter((k) => !allowed.includes(k));
  return missing.length ? { collections, limits: { ...agent.limits, allowedKnowledgeBaseIds: [...missing, ...allowed] } } : { collections };
}

/** What a picker's new selection adds to and removes from the list it was showing. */
export const listChange = (shown: string[], picked: string[]): { add: string[]; remove: string[] } => ({ add: picked.filter((p) => !shown.includes(p)), remove: shown.filter((s) => !picked.includes(s)) });
