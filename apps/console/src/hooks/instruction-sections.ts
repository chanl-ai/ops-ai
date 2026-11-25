'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { InstructionSectionList } from '@/lib/types/domain';

import { useTeamQuery } from './team-query';

const KEY = ['instruction-sections'] as const;

/**
 * The workspace's list of sections an agent's brief may add (agents-service `GET /v1/agent-instruction-sections`):
 * their labels, order, groups, example lines and presets. Read by the agent editor's Add section menu and by the
 * Agent instructions settings page.
 */
export const useInstructionSections = () => useTeamQuery({ queryKey: KEY, queryFn: () => api.agents.instructionSections(), staleTime: 30_000 });

function useWriteList<A>(fn: (a: A) => Promise<InstructionSectionList>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    // The list also decides how saved agents are drawn and what View prompt reads, so they are read again too.
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: KEY }), qc.invalidateQueries({ queryKey: ['agent'] })]),
  });
}

export const useSaveInstructionSections = () => useWriteList((list: InstructionSectionList) => api.agents.saveInstructionSections(list));
export const useResetInstructionSections = () => useWriteList((_: void) => api.agents.resetInstructionSections());
