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
