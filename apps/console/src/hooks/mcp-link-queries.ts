'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { McpLinkInput } from '@/lib/types/mcp-links';
import { useTeamQuery } from './team-query';

const mk = {
  all: ['mcp-links'] as const,
  list: () => ['mcp-links', 'list'] as const,
  one: (id: string) => ['mcp-links', 'one', id] as const,
};

/** The team's MCP links, each with its newest call. */
export const useMcpLinks = () => useTeamQuery({ queryKey: mk.list(), queryFn: () => api.mcpLinks.list() });

export const useMcpLink = (id: string) => useTeamQuery({ queryKey: mk.one(id), queryFn: () => api.mcpLinks.get(id), enabled: !!id, retry: false });

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: mk.all });
}

export function useCreateMcpLink() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (input: McpLinkInput) => api.mcpLinks.create(input), onSuccess: invalidate });
}

/** Pausing makes the link's address refuse every request until it is resumed. */
export function usePauseMcpLink(id: string) {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (paused: boolean) => api.mcpLinks.setPaused(id, paused), onSuccess: invalidate });
}
