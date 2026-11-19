'use client';

import * as React from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

import { ConsentCard } from '@/components/auth/consent-card';
import { Skeleton } from '@/components/ui/skeleton';
import { useSession } from '@/hooks/auth-queries';
import { useDecideOAuth, useOAuthConsent } from '@/hooks/oauth-queries';
import { isUnreachable, UNREACHABLE } from '@/lib/api/unreachable';

/**
 * Where an assistant's request to connect lands (the authorization server sends the browser here with the request in the
 * query). A signed-out person signs in first and returns; the answer goes back to the assistant through the browser.
 * The page is served with frame-ancestors 'none' (next.config.ts) so no other site can draw it and click Allow.
 */
export default function AuthorizePage() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { status } = useSession();
  const request = React.useMemo(() => {
    const q = new URLSearchParams(params.toString());
    // `mock` picks a designed state on the sample stack and is not part of the request.
    q.delete('mock');
    return Object.fromEntries(q);
  }, [params]);
  const here = `${pathname}?${new URLSearchParams(request)}`;
  const consent = useOAuthConsent(request, status === 'signed_in');
  const decide = useDecideOAuth();
  const [pending, setPending] = React.useState<'allow' | 'deny' | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (status === 'signed_out' || status === 'expired') router.replace(`/login?next=${encodeURIComponent(here)}`);
  }, [status, router, here]);

  const answer = async (decision: 'allow' | 'deny') => {
    setError(null);
    setPending(decision);
    try {
      const { redirectTo } = await decide.mutateAsync({ request, decision });
      window.location.assign(redirectTo);
    } catch (e) {
      setPending(null);
      setError(isUnreachable(e) ? UNREACHABLE : (e as Error).message);
    }
  };

  if (status !== 'signed_in' || consent.isPending) {
    return (
      <div className="mx-auto w-full max-w-md" aria-busy="true">
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }
  if (consent.isError) {
    // A refused request (unknown assistant, a return address it did not register, a person outside the team) shows the
    // reason and no buttons: nothing can be allowed, and the browser is never sent back to the assistant.
    return <ConsentCard pending={null} error={isUnreachable(consent.error) ? UNREACHABLE : consent.error.message} onAnswer={answer} />;
  }
  return <ConsentCard consent={consent.data} pending={pending} error={error} onAnswer={answer} />;
}
