'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { AccountRef, SignInAccount } from '@/lib/types/connections';
import { useTeamQuery } from './team-query';

const KEY = ['connections'] as const;

const MINE = [...KEY, 'mine'] as const;

export const useConnectionKinds = () => useTeamQuery({ queryKey: [...KEY, 'kinds'], queryFn: () => api.connections.kinds(), staleTime: Infinity });
/**
 * The person's own sign-ins (My accounts); `every` adds each account they can connect themselves and have not. Sign-ins
 * change in another window (the sign-in pop-up), so the list is always asked for again when its screen opens.
 */
export const useMyConnections = (every = false) =>
  useTeamQuery({ queryKey: [...MINE, every], queryFn: () => api.connections.mine(every), refetchOnMount: 'always' });

/** Reads the person's connections again, after a sign-in window says they connected. */
export function useRefreshMine() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: MINE });
}

function useConnectionMutation<I, O>(fn: (i: I) => Promise<O>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}

/** Nothing changes until the sign-in completes, so nothing is invalidated here. */
export const useStartSignIn = () =>
  useMutation({ mutationFn: (i: AccountRef & { account?: SignInAccount }) => api.connections.startSignIn(i, { account: i.account }) });
export const useOpenConnectLink = () => useMutation({ mutationFn: (link: string) => api.connections.openConnectLink(link) });
export const useCompleteSignIn = (ref: AccountRef | null) =>
  useConnectionMutation((i: { code: string; state: string }) => api.connections.completeSignIn(ref ?? { appId: '', accountId: '' }, i));
/** The person's own key, password or token on an account each person signs in to. */
export const useGiveOwn = () =>
  useConnectionMutation((i: { connectionId: string; credentials: Record<string, string> }) => api.connections.giveOwn(i.connectionId, { credentials: i.credentials }));
export const useDisconnect = () => useConnectionMutation((connectionId: string) => api.connections.disconnect(connectionId));

/** Test with my account: its start (where to sign in) and its finish (the result, kept as the credential's status). */
export const useStartCredentialCheck = () => useMutation({ mutationFn: (ref: AccountRef) => api.connections.startCredentialCheck(ref) });
export function useFinishCredentialCheck(ref: AccountRef | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (i: { state: string; code: string }) => api.connections.finishCredentialCheck(ref ?? { appId: '', accountId: '' }, i),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['systems'] }),
  });
}
