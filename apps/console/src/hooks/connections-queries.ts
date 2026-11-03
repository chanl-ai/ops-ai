'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { AppCredentialInput, ConnectionEnvironment, SignInAccount, SignInSetting } from '@/lib/types/connections';
import { useTeamQuery } from './team-query';

const KEY = ['connections'] as const;

const MINE = [...KEY, 'mine'] as const;

// Sign-ins change in another window (the sign-in pop-up) and a screen may open from a saved copy, so a connection's
// sign-in state is always asked for again when its screen opens.
export const useConnection = (id: string) => useTeamQuery({ queryKey: [...KEY, id], queryFn: () => api.connections.get(id), enabled: Boolean(id), refetchOnMount: 'always' });
export const useConnectionKinds = () => useTeamQuery({ queryKey: [...KEY, 'kinds'], queryFn: () => api.connections.kinds(), staleTime: Infinity });
/** The person's own sign-ins (Your connections); `every` adds each connection they can connect themselves and have not. */
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

export const useSetSignIn = (id: string) =>
  useConnectionMutation((i: { revision: number; signIn: SignInSetting; teamBackup?: boolean }) => api.connections.setSignIn(id, i));
export const useTestConnection = (id: string) =>
  useConnectionMutation((i: { environment: ConnectionEnvironment; account?: SignInAccount }) => api.connections.test(id, i));
/** Nothing changes until the sign-in completes, so nothing is invalidated here. */
export const useStartSignIn = (id: string) =>
  useMutation({ mutationFn: (i: { environment: ConnectionEnvironment; account?: SignInAccount }) => api.connections.startSignIn(id, i) });
export const useOpenConnectLink = () => useMutation({ mutationFn: (link: string) => api.connections.openConnectLink(link) });
export const useCompleteSignIn = (id: string) => useConnectionMutation((i: { code: string; state: string }) => api.connections.completeSignIn(id, i));
/** The person's own key, password or token on a connection each person signs in to (c-595). */
export const useGiveOwn = () =>
  useConnectionMutation((i: { connectionId: string; environment: ConnectionEnvironment; credentials: Record<string, string> }) =>
    api.connections.giveOwn(i.connectionId, { environment: i.environment, credentials: i.credentials }),
  );
export const useDisconnect = () =>
  useConnectionMutation((i: { connectionId: string; environment: ConnectionEnvironment }) => api.connections.disconnect(i.connectionId, i.environment));

/** The team's own client for an app; the Apps pages and Credentials read again after it. */
export function useCreateAppCredential() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (i: AppCredentialInput) => api.connections.createAppCredential(i),
    onSuccess: () => void Promise.all([qc.invalidateQueries({ queryKey: KEY }), qc.invalidateQueries({ queryKey: ['systems'] })]),
  });
}
/** Test with my account: its start (where to sign in) and its finish (the result, kept as the credential's status). */
export const useStartCredentialCheck = () =>
  useMutation({ mutationFn: (i: { id: string; environment: ConnectionEnvironment }) => api.connections.startCredentialCheck(i.id, { environment: i.environment }) });
export function useFinishCredentialCheck(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (i: { state: string; code: string }) => api.connections.finishCredentialCheck(id, i),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['systems'] }),
  });
}
