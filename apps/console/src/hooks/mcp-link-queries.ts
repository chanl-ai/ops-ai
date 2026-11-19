'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { sdk } from '@/lib/api/ops-sdk';
import type { OpsAI } from '@chanl-ai/ops-ai';
import { usePagedQuery } from './paged-query';
import type { McpLinkInput } from '@/lib/types/mcp-links';
import { useTeamQuery } from './team-query';

const mk = {
  all: ['mcp-links'] as const,
  list: () => ['mcp-links', 'list'] as const,
  one: (id: string) => ['mcp-links', 'one', id] as const,
};

type Tools = OpsAI['raw']['tools'];
/** One MCP link as the list answers it, with its newest call. */
export type McpLinkRow = Awaited<ReturnType<Tools['mcp_links_list_mcp_links']>>['data'][number];

/** One page of the MCP links of the teams the person works in (GET /v1/mcp-links), searched on the name and narrowed to teams (`teamId`), by name. */
export const useMcpLinks = (p: { page: number; pageSize: number; search?: string; teamId?: string[] }) =>
  usePagedQuery({
    queryKey: [...mk.list(), p.page, p.pageSize, p.search ?? '', p.teamId ?? []],
    queryFn: () => sdk((ops) => ops.raw.tools.mcp_links_list_mcp_links({ query: { page: p.page, pageSize: p.pageSize, search: p.search, teamId: p.teamId } })),
  });

export const useMcpLink = (id: string) => useTeamQuery({ queryKey: mk.one(id), queryFn: () => api.mcpLinks.get(id), enabled: !!id, retry: false });

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: mk.all });
}

export function useCreateMcpLink() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (input: McpLinkInput) => api.mcpLinks.create(input), onSuccess: invalidate });
}

/** Pause or resume any of the listed links, from a row's menu. */
export function useSetMcpLinkPaused() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: ({ id, paused }: { id: string; paused: boolean }) => api.mcpLinks.setPaused(id, paused), onSuccess: invalidate });
}

export function useDeleteMcpLink() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (id: string) => api.mcpLinks.remove(id), onSuccess: invalidate });
}

/** Pausing makes the link's address refuse every request until it is resumed. */
export function usePauseMcpLink(id: string) {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (paused: boolean) => api.mcpLinks.setPaused(id, paused), onSuccess: invalidate });
}
