'use client';

import * as React from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { CircleCheck } from 'lucide-react';

import { SignInCard } from '@/components/connections/sign-in-card';
import { CONNECTED_MESSAGE, FAILED_MESSAGE, forgetSignIn, retrySignInHref, signInFor, signInIsCheck, type ConnectedMessage, type FailedMessage } from '@/components/connections/sign-in';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useCompleteSignIn, useFinishCredentialCheck } from '@/hooks/connections-queries';

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
  const [account] = React.useState(() => (state ? signInFor(state) : null));
  // Test with my account comes back here too: it finishes as a test of the app credential and keeps no sign-in.
  const [check] = React.useState(() => (state ? signInIsCheck(state) : false));
  const complete = useCompleteSignIn(account);
  const finish = useFinishCredentialCheck(account);
  const started = React.useRef(false);
  React.useEffect(() => {
    if (started.current || denied || !account || !code) return;
    started.current = true;
    if (check) {
      finish.mutate(
        { code, state },
        {
          onSuccess: (res) => {
            forgetSignIn(state);
            const opener = window.opener as Window | null;
            if (res.health.status !== 'ok' || !opener || opener.closed) return;
            const said: ConnectedMessage = { type: CONNECTED_MESSAGE, connectionId: account.accountId, connection: 'the app credential', account: res.health.account };
            opener.postMessage(said, window.location.origin);
            window.close();
          },
        },
      );
      return;
    }
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
  }, [account, check, code, complete, denied, finish, state]);

  // The page that opened this window learns of a refusal or a failure too, so its Connect window stops waiting.
  const failure = denied
    ? `Access to the app was not given${denied === 'access_denied' ? '' : ` (${denied})`}.`
    : !account || !code
      ? 'This sign-in has expired or was already used.'
      : complete.isError
        ? complete.error.message
        : finish.isError
          ? finish.error.message
          : finish.data?.health.status === 'failed'
            ? (finish.data.health.message ?? 'The test with your account did not pass.')
            : null;
  React.useEffect(() => {
    const opener = window.opener as Window | null;
    if (!failure || !opener || opener.closed) return;
    const said: FailedMessage = { type: FAILED_MESSAGE, message: failure };
    opener.postMessage(said, window.location.origin);
  }, [failure]);
  // Read after mount: the server render has no window, and a popup closes itself where a tab goes back to chat.
  const [popup, setPopup] = React.useState(false);
  React.useEffect(() => {
    setPopup(Boolean(window.opener));
  }, []);
  const back = popup ? (
    <Button variant="outline" onClick={() => window.close()} data-testid="sign-in-close">
      Close
    </Button>
  ) : (
    <Button asChild variant="outline">
      <Link href="/chat">Back to chat</Link>
    </Button>
  );
  // In the window a Connect button opened, Try again opens the connect page for the same app, whose load asks the page
  // that opened this window to start the sign-in once more.
  const again = popup ? (
    <>
      {back}
      <Button onClick={() => window.location.assign(retrySignInHref())} data-testid="sign-in-retry">
        Try again
      </Button>
    </>
  ) : (
    back
  );
  if (denied)
    return <SignInCard testId="sign-in-denied" title="Access was not given" description="You chose not to allow access on the app’s own page, so nothing was connected." footer={again} />;
  if (!account || !code)
    return <SignInCard testId="sign-in-lost" title="This sign-in has expired or was already used" description="Start it again from the chat or from the app’s page." footer={back} />;
  if (complete.isError) return <SignInCard testId="sign-in-failed" title="The sign-in did not finish" description={complete.error.message} footer={again} />;
  if (check && (finish.isError || finish.data?.health.status === 'failed'))
    return <SignInCard testId="sign-in-check-failed" title="The test with your account did not pass" description={failure ?? undefined} footer={back} />;
  if (check && finish.isSuccess)
    return (
      <SignInCard testId="sign-in-check-ok" title="The app credential works" description={finish.data.health.account ? `Signed in as ${finish.data.health.account}. You can close this window.` : 'You can close this window.'} footer={back}>
        <CircleCheck className="size-8 text-success-text" />
      </SignInCard>
    );
  if (complete.isSuccess)
    return (
      <SignInCard testId="sign-in-connected" title={`${complete.data.name} is connected`} description={popup ? 'You can close this window.' : 'Go back to the chat; it goes on with your account.'} footer={back}>
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

export default function Page() {
  return <SignInReturnPage />;
}
