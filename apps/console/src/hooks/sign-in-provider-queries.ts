'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { SignInProviderInput } from '@/lib/types/sign-in';
import { useTeamQuery } from './team-query';

const KEY = ['sign-in-providers'] as const;

/** The workspace's sign-in providers with each domain's proof (Security team admins, c-195). */
export const useSignInProviders = () => useTeamQuery({ queryKey: KEY, queryFn: () => api.signInProviders.list(), retry: false });

/** The secret names an OIDC provider may name; values stay in the installation's settings. */
export const useSignInSecretNames = (enabled: boolean) => useTeamQuery({ queryKey: [...KEY, 'secret-names'], queryFn: () => api.signInProviders.secretNames(), enabled });

function useProviderWrite<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: KEY }) });
}

/** Where a bank's identity provider reads this installation's SAML metadata; unset when no service serves it. */
export const useSamlMetadataUrl = (): string | undefined => api.signInProviders.samlMetadataUrl;

export const useSaveSignInProvider = () => useProviderWrite(({ id, input }: { id: string; input: SignInProviderInput }) => api.signInProviders.save(id, input));
export const useRemoveSignInProvider = () => useProviderWrite((id: string) => api.signInProviders.remove(id));
export const useVerifySignInDomain = () => useProviderWrite((domain: string) => api.signInProviders.verifyDomain(domain));
