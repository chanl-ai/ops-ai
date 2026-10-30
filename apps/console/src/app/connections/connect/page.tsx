'use client';

import * as React from 'react';
import Link from 'next/link';
import { notFound, useSearchParams } from 'next/navigation';

import { SignInCard } from '@/components/connections/sign-in-card';
import { goSignIn } from '@/components/connections/sign-in';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useOpenConnectLink } from '@/hooks/connections-queries';
import { ApiError } from '@/lib/api/contract';
import { personalSignIn } from '@/lib/api';

/**
 * Where a chat's Connect card sends the person (c-558): opens the single-use link made for them and goes on to the
 * system's own sign-in. Errors keep them here: another person's link, an expired or used one.
 */
function ConnectPage() {
  const link = useSearchParams().get('link') ?? '';
  const open = useOpenConnectLink();
  const started = React.useRef(false);
  React.useEffect(() => {
    if (started.current || !link) return;
    started.current = true;
    open.mutate(link, { onSuccess: (s) => goSignIn(s, s.connectionId ?? '') });
  }, [link, open]);

  const code = open.error instanceof ApiError ? open.error.code : undefined;
  const back = (
    <Button asChild variant="outline">
      <Link href="/chat">Back to chat</Link>
    </Button>
  );
  if (!link || code === 'connect_link_expired')
    return <SignInCard testId="connect-expired" title="This link has expired" description="Ask again in the chat for a new one." footer={back} />;
  if (code === 'connect_link_not_yours')
    return <SignInCard testId="connect-not-yours" title="This link was made for someone else" description="Open the system from your own chat to connect your account." footer={back} />;
  if (open.isError)
    return (
      <SignInCard testId="connect-failed" title="The sign-in could not start" description={open.error.message} footer={<Button onClick={() => window.location.reload()}>Try again</Button>} />
    );
  return (
    <SignInCard testId="connect-starting" title="Connecting your account" description="You sign in as yourself, on the system's own page.">
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
    </SignInCard>
  );
}

/** Not offered until the personal sign-in switch is on (lib/api/index.ts). */
export default function Page() {
  if (!personalSignIn) notFound();
  return <ConnectPage />;
}
