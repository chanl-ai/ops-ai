'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { sdk } from '@/lib/api/ops-sdk';
import type { OpsAI } from '@chanl-ai/ops-ai';
import type { AccountRef, SignInAccount, SignInReturn } from '@/lib/types/connections';
import { refreshAppState } from './app-state-refresh';
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

/** One of the person's connectors on Connectors (Mine): one app that acts as them, joined by tools-service. */
export type MyConnector = Awaited<ReturnType<OpsAI['raw']['tools']['apps_my_connections']>>[number];
/** The person's connectors, one row per app (GET /v1/me/connections); asked again whenever the page opens, since a
 * sign-in finishes in another window. */
export const useMyConnectors = () =>
  useTeamQuery({ queryKey: [...MINE, 'connectors'], queryFn: () => sdk((ops) => ops.raw.tools.apps_my_connections()), refetchOnMount: 'always' });

/** Reads the person's connections again, after a sign-in window says they connected. */
export function useRefreshMine() {
  const qc = useQueryClient();
  return () => void refreshAppState(qc);
}

function useConnectionMutation<I, O>(fn: (i: I) => Promise<O>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: KEY }), refreshAppState(qc)]) });
}

/** Nothing changes until the sign-in completes, so nothing is invalidated here. */
export const useStartSignIn = () =>
  useMutation({ mutationFn: (i: AccountRef & { account?: SignInAccount }) => api.connections.startSignIn(i, { account: i.account }) });
export const useOpenConnectLink = () => useMutation({ mutationFn: (link: string) => api.connections.openConnectLink(link) });
/** The return page's one call: finishes whatever the state was sent out for, from what the system sent back. */
export function useFinishSignIn() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (i: SignInReturn) => api.connections.finishSignIn(i),
    // A refusal is recorded on the account too, so either way the account's answer changed.
    onSettled: () => (void qc.invalidateQueries({ queryKey: KEY }), void refreshAppState(qc)),
  });
}
/** The person's own key, password or token on an account each person signs in to. */
export const useGiveOwn = () =>
  useConnectionMutation((i: { connectionId: string; credentials: Record<string, string> }) => api.connections.giveOwn(i.connectionId, { credentials: i.credentials }));
export const useDisconnect = () => useConnectionMutation((connectionId: string) => api.connections.disconnect(connectionId));

/** Test with my account: where the admin signs in; the return page finishes it (useFinishSignIn). */
export const useStartCredentialCheck = () => useMutation({ mutationFn: (ref: AccountRef) => api.connections.startCredentialCheck(ref) });

/** Starts the person's sign-in for another account of their own on a connector's app, through the same auth config
 * (POST /v1/me/accounts/{id}/another); a login already linked updates that account instead. */
export const useAddOwnAccount = () =>
  useMutation({
    mutationFn: (i: { accountId: string; name: string; settings: Record<string, string> }) =>
      sdk((ops) => ops.raw.tools.apps_add_own_account({ path: { account_id: i.accountId }, body: { name: i.name, settings: i.settings } })),
  });
