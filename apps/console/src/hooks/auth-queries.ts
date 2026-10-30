'use client';

import * as React from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

import { authProvider, isExpired, type ReauthInput, type Session } from '@/lib/auth';
import { wipeSavedQueries } from '@/lib/query-cache';

import { useLookups } from './queries';
import { useSessionQuery } from './team-query';

export type SessionStatus = 'loading' | 'signed_in' | 'signed_out' | 'expired';

/**
 * The current session and its status, kept live through the provider's change events. `expired` keeps the old
 * session so the re-sign-in screen can name who was signed in.
 */
export function useSession(): { session: Session | null; status: SessionStatus } {
  const [state, setState] = React.useState<{ session: Session | null; status: SessionStatus }>({ session: null, status: 'loading' });
  React.useEffect(() => {
    let live = true;
    const apply = (next: Session | null) => live && setState({ session: next, status: !next ? 'signed_out' : isExpired(next) ? 'expired' : 'signed_in' });
    authProvider.getSession().then(apply, () => apply(null));
    const off = authProvider.onSessionChange(apply);
    return () => {
      live = false;
      off();
    };
  }, []);
  return state;
}

/** What the workspace allows at sign-in (methods, SSO domains, MFA, session length). Policy comes from the API, not the adapter. */
export const useSignInPolicy = () => useSessionQuery({ queryKey: ['sign-in-policy'], queryFn: () => api.signInPolicy.get(), staleTime: 5 * 60_000 });

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/**
 * How the typed email signs in, asked of the sign-in adapter once the email is complete. Keyed by domain, since the
 * answer depends on the domain alone; the last answer stays while the next loads, so the form does not flicker.
 */
export function useSignInOptions(email: string) {
  const deferred = React.useDeferredValue(email.trim().toLowerCase());
  const valid = EMAIL.test(deferred);
  const domain = valid ? deferred.split('@')[1] : '';
  return useSessionQuery({
    queryKey: ['sign-in-options', domain],
    queryFn: () => authProvider.signInOptions(deferred),
    enabled: valid,
    staleTime: 60_000,
    placeholderData: (previous) => previous,
  });
}

/** The verified SSO domain an email belongs to, if any. */
export const ssoDomainFor = (email: string, domains: { domain: string; verified: boolean }[] = []) => {
  const host = email.trim().toLowerCase().split('@')[1];
  return host ? domains.find((d) => d.verified && d.domain.toLowerCase() === host)?.domain : undefined;
};

/** Sign-in calls change who every query runs as, so a finished sign-in or sign-out drops cached data, in memory and
 * saved in the browser for anyone (c-560). */
function useAuthWrite<A, R>(fn: (a: A) => Promise<R>, clear = false) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      if (!clear) return;
      qc.clear();
      await wipeSavedQueries();
    },
  });
}

export const useSignInWithPassword = () => useAuthWrite(({ email, password }: { email: string; password: string }) => authProvider.signInWithPassword(email, password), true);
export const useSignInWithGoogle = () => useAuthWrite(() => authProvider.signInWithGoogle(), true);
/** The seeded demo people to offer as one-click sign-ins (c-504). A production build never asks, and the sign-in
 * service answers only in development. */
export const useDemoPeople = () =>
  useSessionQuery({
    queryKey: ['demo-people'],
    queryFn: () => authProvider.demoPeople?.() ?? Promise.resolve([]),
    enabled: process.env.NODE_ENV !== 'production' && !!authProvider.demoPeople,
    staleTime: Infinity,
    retry: false,
  });
export const useSignInAsDemo = () =>
  useAuthWrite((email: string) => {
    if (!authProvider.signInAsDemo) throw new Error('This sign-in adapter has no demo sign-in.');
    return authProvider.signInAsDemo(email);
  }, true);
export const useStartSso = () => useAuthWrite((input: { email?: string; domain?: string; next?: string }) => authProvider.startSso(input));
export const useCompleteSso = () => useAuthWrite((code: string) => authProvider.completeSso(code), true);
/** How one email signs in, asked once (the forgot-password page, before it sends). */
export const useAskSignInOptions = () => useAuthWrite((email: string) => authProvider.signInOptions(email));
export const useSendReset = () => useAuthWrite((email: string) => authProvider.sendReset(email));
export const useResetPassword = () => useAuthWrite(({ token, password }: { token: string; password: string }) => authProvider.resetPassword(token, password));
export const useMfaSetup = () => useAuthWrite(() => authProvider.mfa.setup());
export const useMfaEnrol = () => useAuthWrite((code: string) => authProvider.mfa.enrol(code));
export const useMfaVerify = () => useAuthWrite(({ code, challengeId }: { code: string; challengeId?: string }) => authProvider.mfa.verify(code, challengeId), true);
/** Step-up before a sensitive action; the token is good for a few minutes. */
export const useReauthenticate = () => useAuthWrite((input: ReauthInput) => authProvider.reauthenticate(input));
/** Step-up for SSO and Google sessions: the redirect to the IdP, which comes back through /sso/callback?stepUp=1. */
export const useStartSsoStepUp = () => useAuthWrite((input: { returnTo: string }) => authProvider.startSsoStepUp(input));
export const useCompleteSsoStepUp = () => useAuthWrite((code: string) => authProvider.completeSsoStepUp(code));
/** A stable function returning the step-up an IdP round trip left (cleared on read), or null. */
export const useTakeStepUp = () => React.useCallback(() => authProvider.takeStepUp(), []);
export const useSignOut = () => useAuthWrite(() => authProvider.signOut(), true);

/**
 * The person using the console: the signed-in session's name, and every form a request may record them by (name and
 * email; platform-recorded requests carry the email). The workspace lookup's user stands in only when no adapter
 * session exists, as with the mock provider; under a real sign-in it is a fixed seed value, never the viewer.
 */
export function useCurrentPerson(): { name: string; ids: string[] } {
  const { session } = useSession();
  const lookups = useLookups();
  const name = session?.user.name ?? lookups.data?.currentUser.name ?? '';
  return { name, ids: [session?.user.name, session?.user.email, session ? undefined : lookups.data?.currentUser.name].filter((x): x is string => !!x) };
}
