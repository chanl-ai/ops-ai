'use client';

import { api } from '@/lib/api';
import { useTeamQuery } from './team-query';

export const pk = {
  variables: ['prompt-variables'] as const,
};

export const usePromptVariables = () => useTeamQuery({ queryKey: pk.variables, queryFn: api.prompts.variables, staleTime: 10 * 60_000 });
