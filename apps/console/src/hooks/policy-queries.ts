'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { PolicyEditor, PolicyValue } from '@/lib/types/workspace-policies';

import { useMyPermissions } from './me-queries';
import { useTeam } from './use-team';
import { useTeamQuery } from './team-query';

const KEY = ['workspace-policies'] as const;

export const useWorkspacePolicies = () => useTeamQuery({ queryKey: KEY, queryFn: () => api.workspacePolicies.list() });
/** Whether the person may change policies in the team they act in, as the server's own permissions say. */
export function usePolicyEditor(): { data?: PolicyEditor; isPending: boolean } {
  // The resolved team: the stored choice may name a team the person is not in, and the requests then act in their first one.
  const { team } = useTeam();
  const teamId = team?.id ?? '';
  // Under platform sign-in the cells come from the one GET /v1/me answer; the mock serves its own.
  const perms = useMyPermissions();
  const sample = useTeamQuery({ queryKey: [...KEY, 'editor', teamId], queryFn: () => api.workspacePolicies.editor!(teamId), enabled: !!teamId && !api.teams.me });
  if (!api.teams.me) return sample;
  const cells: PolicyEditor['cells'] = {};
  for (const p of perms.data?.teams.find((t) => t.teamId === teamId)?.permissions ?? []) cells[`${p.area}.${p.action}`] = [...new Set(p.roles.map((r) => r.name))];
  return { data: perms.data ? { cells } : undefined, isPending: perms.isPending };
}
export function useSetWorkspacePolicy() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (i: { key: string; value: PolicyValue; teamId?: string }) => api.workspacePolicies.set(i.key, i.value, i.teamId), onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}

/** Where one tool's answer sits inside the team's `appChangesByApp`; no app id starts with it. */
export const TOOL_KEY = 'tool:';
export const BY_REVIEWER = 'reviewer';
export type ToolAnswer = { answer: 'none' | 'person' | typeof BY_REVIEWER; reviewerRole?: string | null };
/**
 * The team's own answer for one tool, kept in the policy store so it works for a plugin's tools too (their module row
 * has no editor). `entry` is null while the tool follows its app; `save(null)` goes back to that.
 */
export function useToolAnswer(tool: string) {
  const { team } = useTeam();
  const teamId = team?.id ?? '';
  const policies = useWorkspacePolicies();
  const set = useSetWorkspacePolicy();
  const read = (key: string) => {
    const value = policies.data?.find((p) => p.key === key)?.value;
    const mine = value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>)[teamId] : undefined;
    return mine && typeof mine === 'object' ? (mine as Record<string, unknown>) : {};
  };
  const all = read('appChangesByApp') as Record<string, ToolAnswer>;
  return {
    entry: all[`${TOOL_KEY}${tool}`] ?? null,
    teamRole: (read('appChanges').reviewerRole as string | null | undefined) ?? null,
    pending: set.isPending,
    save: (next: ToolAnswer | null) => {
      const { [`${TOOL_KEY}${tool}`]: _old, ...rest } = all;
      return set.mutateAsync({ key: 'appChangesByApp', teamId, value: next ? { ...rest, [`${TOOL_KEY}${tool}`]: next } : rest });
    },
  };
}
