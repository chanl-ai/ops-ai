'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { OAuthRequest } from '@/lib/types/oauth';
import { useSessionQuery, useTeamQuery } from './team-query';

// ── The consent page: read for the signed-in person, whichever team is current (the address names the team). ──
export const useOAuthConsent = (request: OAuthRequest, enabled: boolean) =>
  useSessionQuery({ queryKey: ['oauth', 'consent', request], queryFn: () => api.oauth.consent(request), retry: false, enabled });
export const useDecideOAuth = () => useMutation({ mutationFn: ({ request, decision }: { request: OAuthRequest; decision: 'allow' | 'deny' }) => api.oauth.decide(request, decision) });

// ── My security → Connected assistants ──
const GRANTS = ['oauth', 'grants'] as const;
export const useConnectedAssistants = () => useTeamQuery({ queryKey: GRANTS, queryFn: () => api.oauth.grants() });
export function useDisconnectAssistant() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => api.oauth.disconnect(id), onSuccess: () => qc.invalidateQueries({ queryKey: GRANTS }) });
}
