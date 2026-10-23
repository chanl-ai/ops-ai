'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { SessionFilters } from '@/lib/types/account';
import type { InviteAcceptInput } from '@/lib/types/invites';
import type { ListParams } from '@/lib/types/query';
import type { SignInPolicyPatch } from '@/lib/types/sign-in';
import { useSessionQuery, useTeamQuery } from './team-query';

// ── Invites (public: the person is not signed in yet) ──
export const useInvite = (token: string) => useSessionQuery({ queryKey: ['invite', token], queryFn: () => api.invites.get(token), retry: false });
export const useAcceptInvite = (token: string) => useMutation({ mutationFn: (input: InviteAcceptInput) => api.invites.accept(token, input) });

// ── Sign-in policy (Settings → Sign-in). Same key as useSignInPolicy, so a save refreshes the login screen too. ──
const POLICY_KEY = ['sign-in-policy'] as const;
export const useSignInPolicySettings = () => useTeamQuery({ queryKey: POLICY_KEY, queryFn: () => api.signInPolicy.get() });
function usePolicyWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: POLICY_KEY }), qc.invalidateQueries({ queryKey: ['governance'] })]) });
}
export const useSaveSignInPolicy = () => usePolicyWrite((p: SignInPolicyPatch) => api.signInPolicy.save(p));
export const useAddSsoDomain = () => usePolicyWrite((d: string) => api.signInPolicy.addDomain(d));
export const useVerifySsoDomain = () => usePolicyWrite((d: string) => api.signInPolicy.verifyDomain(d));
export const useRemoveSsoDomain = () => usePolicyWrite((d: string) => api.signInPolicy.removeDomain(d));
export const useTestSsoConnection = () => usePolicyWrite(() => api.signInPolicy.testConnection());

// ── Account (the signed-in person) ──
const AK = { profile: ['account', 'profile'] as const, mfa: ['account', 'mfa'] as const, sessions: (p: unknown) => ['account', 'sessions', p] as const };
export const useAccountProfile = () => useTeamQuery({ queryKey: AK.profile, queryFn: () => api.account.profile() });
export const useMfaDevices = () => useTeamQuery({ queryKey: AK.mfa, queryFn: () => api.account.mfa.list() });
export const useAccountSessions = (p: ListParams<SessionFilters>) => usePagedQuery({ queryKey: AK.sessions(p), queryFn: () => api.account.sessions.list(p) });
function useAccountWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: ['account'] }) });
}
export const useUpdateProfile = () => useAccountWrite((i: { name: string }) => api.account.updateProfile(i));
export const useChangePassword = () => useAccountWrite((password: string) => api.account.changePassword({ password }));
export const useRegenerateRecoveryCodes = () => useAccountWrite(() => api.account.mfa.regenerateCodes());
export const useRemoveMfaDevice = () => useAccountWrite((id: string) => api.account.mfa.remove(id));
export const useRevokeSession = () => useAccountWrite((id: string) => api.account.sessions.revoke(id));
export const useRevokeOtherSessions = () => useAccountWrite(() => api.account.sessions.revokeOthers());
