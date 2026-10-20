'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { WidgetDeploymentInput, WidgetDeploymentPatch } from '@/lib/types/widget-deployments';

const key = (agentId: string) => ['widget-deployments', agentId] as const;

/** One agent's widget deployments, newest first, filtered by the service. */
export const useWidgetDeployments = (agentId: string) => useQuery({ queryKey: key(agentId), queryFn: () => api.widgetDeployments.list(agentId) });

export function useCreateWidgetDeployment() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (input: WidgetDeploymentInput) => api.widgetDeployments.create(input), onSuccess: (d) => qc.invalidateQueries({ queryKey: key(d.agentId) }) });
}

export function useUpdateWidgetDeployment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: WidgetDeploymentPatch }) => api.widgetDeployments.update(id, patch),
    // The channel API answers with the channel row or a review, not the deployment, so every embed list and the
    // Channels pages read again.
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: ['widget-deployments'] }), qc.invalidateQueries({ queryKey: ['channels'] })]),
  });
}

const keysKey = (id: string) => ['widget-deployments', 'keys', id] as const;

/** One deployment's mint keys, fetched fresh each time its keys dialog opens: the bank's server uses them meanwhile. */
export const useWidgetMintKeys = (id: string | undefined) =>
  useQuery({ queryKey: keysKey(id ?? ''), queryFn: () => api.widgetDeployments.keys(id ?? ''), enabled: !!id, refetchOnMount: 'always' });

export function useCreateWidgetMintKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name, expiresInDays }: { id: string; name: string; expiresInDays?: number }) => api.widgetDeployments.createKey(id, name, expiresInDays),
    onSuccess: (_, { id }) => qc.invalidateQueries({ queryKey: keysKey(id) }),
  });
}

export function useRevokeWidgetMintKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, keyId }: { id: string; keyId: string }) => api.widgetDeployments.revokeKey(id, keyId),
    onSuccess: (_, { id }) => qc.invalidateQueries({ queryKey: keysKey(id) }),
  });
}

/** Where pages load the widget script from; the snippet names it. */
export const useWidgetScriptUrl = () => api.widgetDeployments.scriptUrl();

/** A preview session for the signed-in builder, bound to the console's origin (Preview as a person, c-232). */
export const useWidgetPreviewSession = () => useMutation({ mutationFn: (id: string) => api.widgetDeployments.previewSession(id) });
