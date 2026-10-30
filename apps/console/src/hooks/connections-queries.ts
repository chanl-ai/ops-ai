'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api, personalSignIn } from '@/lib/api';
import type { ConnectionEnvironment, SignInAccount, SignInSetting } from '@/lib/types/connections';
import { useTeamQuery } from './team-query';

const KEY = ['connections'] as const;

/** Whether the console offers each person's own sign-in (the NEXT_PUBLIC_OPS_PERSONAL_SIGNIN switch, c-558). */
export const usePersonalSignIn = (): boolean => personalSignIn;
const MINE = [...KEY, 'mine'] as const;

// Sign-ins change in another window (the sign-in pop-up) and a screen may open from a saved copy, so a connection's
// sign-in state is always asked for again when its screen opens.
export const useConnection = (id: string) => useTeamQuery({ queryKey: [...KEY, id], queryFn: () => api.connections.get(id), enabled: Boolean(id), refetchOnMount: 'always' });
export const useConnectionKinds = () => useTeamQuery({ queryKey: [...KEY, 'kinds'], queryFn: () => api.connections.kinds(), staleTime: Infinity });
/** The person's own sign-ins (Your connections). */
export const useMyConnections = () => useTeamQuery({ queryKey: MINE, queryFn: () => api.connections.mine(), refetchOnMount: 'always' });

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
export const useDisconnect = () =>
  useConnectionMutation((i: { connectionId: string; environment: ConnectionEnvironment }) => api.connections.disconnect(i.connectionId, i.environment));
