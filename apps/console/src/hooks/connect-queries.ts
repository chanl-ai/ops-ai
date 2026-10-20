'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ConnectAudience, ConnectRange, ConnectSettingsInput } from '@/lib/types/connect';

export const ck = { overview: (p: unknown) => ['connect', p] as const };

/** Everything the Connect page shows for one range, computed by the API. */
export const useConnect = (p: { range: ConnectRange }) => useQuery({ queryKey: ck.overview(p), queryFn: () => api.connect.get(p), placeholderData: keepPreviousData });

function useConnectWrite<A, R>(fn: (a: A) => Promise<R>, roots: string[]) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => Promise.all(roots.map((r) => qc.invalidateQueries({ queryKey: [r] }))) });
}

/** Exposing to assistants creates or resumes an MCP deployment; exposing to agents adds or removes a tool. Both lists refresh. */
export const useSetExposed = () => useConnectWrite(({ workflowId, audience, exposed }: { workflowId: string; audience: ConnectAudience; exposed: boolean }) => api.connect.setExposed(workflowId, audience, exposed), ['connect', 'deployments', 'tools', 'agents', 'agent', 'skills']);
/** Fetches the workspace MCP URL on demand, for the ⌘K action, from the same cache the Connect page uses. */
export function useConnectUrl() {
  const qc = useQueryClient();
  return () => qc.fetchQuery({ queryKey: ck.overview({ range: '7d' }), queryFn: () => api.connect.get({ range: '7d' }) }).then((o) => o.url);
}
export const useRecordCopy = () => useConnectWrite(() => api.connect.recordCopy(), ['connect']);
export const useSaveConnectSettings = () => useConnectWrite((i: ConnectSettingsInput) => api.connect.saveSettings(i), ['connect']);
