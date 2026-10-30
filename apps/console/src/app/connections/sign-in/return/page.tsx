'use client';

import * as React from 'react';
import Link from 'next/link';
import { notFound, useSearchParams } from 'next/navigation';
import { CircleCheck } from 'lucide-react';

import { SignInCard } from '@/components/connections/sign-in-card';
import { CONNECTED_MESSAGE, forgetSignIn, signInFor, type ConnectedMessage } from '@/components/connections/sign-in';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useCompleteSignIn } from '@/hooks/connections-queries';
import { personalSignIn } from '@/lib/api';

/**
 * Where a connected system sends the person back after signing in (tools-service's SIGN_IN_RETURN_PATH, c-558):
 * finishes the sign-in, tells the chat that opened this window, and closes it. Opened in a tab of its own (a phone),
 * it offers the way back instead. Errors keep the person here: consent denied, a sign-in already used or expired.
 */
function SignInReturnPage() {
  const params = useSearchParams();
  const state = params.get('state') ?? '';
  const code = params.get('code') ?? '';
  const denied = params.get('error');
  const [connectionId] = React.useState(() => (state ? signInFor(state) : null));
  const complete = useCompleteSignIn(connectionId ?? '');
  const started = React.useRef(false);
  React.useEffect(() => {
    if (started.current || denied || !connectionId || !code) return;
    started.current = true;
    complete.mutate(
      { code, state },
      {
        onSuccess: (conn) => {
          forgetSignIn(state);
          const opener = window.opener as Window | null;
          if (!opener || opener.closed) return;
          const said: ConnectedMessage = { type: CONNECTED_MESSAGE, connectionId: conn.id, connection: conn.name };
          opener.postMessage(said, window.location.origin);
          window.close();
        },
      },
    );
  }, [code, complete, connectionId, denied, state]);

  const back = (
    <Button asChild variant="outline">
      <Link href="/chat">Back to chat</Link>
    </Button>
  );
  if (denied)
    return <SignInCard testId="sign-in-denied" title="Access was not given" description="You chose not to allow access on the system's page, so nothing was connected. Ask again in the chat to try once more." footer={back} />;
  if (!connectionId || !code)
    return <SignInCard testId="sign-in-lost" title="This sign-in has expired or was already used" description="Start it again from the chat or from Your connections." footer={back} />;
  if (complete.isError) return <SignInCard testId="sign-in-failed" title="The sign-in did not finish" description={complete.error.message} footer={back} />;
  if (complete.isSuccess)
    return (
      <SignInCard testId="sign-in-connected" title={`${complete.data.name} is connected`} description="Go back to the chat; it goes on with your account." footer={back}>
        <CircleCheck className="size-8 text-success-text" />
      </SignInCard>
    );
  return (
    <SignInCard testId="sign-in-finishing" title="Finishing your sign-in">
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-4 w-2/3" />
    </SignInCard>
  );
}

/** Not offered until the personal sign-in switch is on (lib/api/index.ts). */
export default function Page() {
  if (!personalSignIn) notFound();
  return <SignInReturnPage />;
}
