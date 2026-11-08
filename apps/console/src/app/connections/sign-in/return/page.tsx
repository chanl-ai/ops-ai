'use client';

import * as React from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { CircleCheck } from 'lucide-react';

import { SignInCard } from '@/components/connections/sign-in-card';
import { announceSignIn, CONNECTED_MESSAGE, FAILED_MESSAGE } from '@/components/connections/sign-in';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useFinishSignIn } from '@/hooks/connections-queries';
import { setCurrentTeamId } from '@/lib/api/team-context';
import type { ApiError } from '@/lib/api/contract';

/** The team a sign-in's state names, before its secret part: the account's team, where it is finished. */
const teamOf = (state: string) => (state.includes('.') ? state.slice(0, state.indexOf('.')) : null);

/**
 * Where a connected system sends the person back after signing in (tools-service's SIGN_IN_RETURN_PATH): hands what
 * the system sent back (the state with its code, or with the error it refused with) to the one call that finishes it,
 * tells the window that started it, and closes. The state alone names the sign-in, so a window that started nothing
 * (another tab, a fresh browser) finishes it too. A refusal shows the service's one plain sentence; opened in a tab of
 * its own (a phone) the page offers the way back.
 */
function SignInReturnPage() {
  const params = useSearchParams();
  const state = params.get('state') ?? '';
  const code = params.get('code') ?? '';
  const error = params.get('error') ?? '';
  const finish = useFinishSignIn();
  const started = React.useRef(false);
  React.useEffect(() => {
    if (started.current || !state || (!code && !error)) return;
    started.current = true;
    // Finished in the account's team, whatever team this window was last working in.
    const team = teamOf(state);
    if (team) setCurrentTeamId(team);
    finish.mutate(
      { state, ...(code ? { code } : { error, ...(params.get('error_description') ? { errorDescription: params.get('error_description') ?? '' } : {}) }) },
      {
        onSuccess: (done) => {
          if (done.check && done.health?.status !== 'ok') {
            announceSignIn({ type: FAILED_MESSAGE, state, message: done.health?.message ?? 'The test with your account did not pass.' });
            return;
          }
          announceSignIn({ type: CONNECTED_MESSAGE, state, connectionId: done.accountId, connection: done.account?.name ?? 'the auth config', account: done.health?.account });
          if (window.opener) window.close();
        },
        onError: (e) => announceSignIn({ type: FAILED_MESSAGE, state, message: e.message }),
      },
    );
  }, [code, error, finish, params, state]);

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
      <Link href="/integrations">Back to Connectors</Link>
    </Button>
  );
  const refused = finish.error as (ApiError & { details?: { who?: string; app?: string } }) | null;
  if (!state || (!code && !error))
    return <SignInCard testId="sign-in-lost" title="This sign-in has expired or was already used" description="Start it again from the app’s page." footer={back} />;
  if (refused?.code === 'sign_in_refused')
    return (
      <SignInCard
        testId="sign-in-denied"
        title={refused.details?.who === 'person' ? 'Access was not given' : 'Someone else needs to act first'}
        description={refused.message}
        footer={back}
      />
    );
  if (refused?.code === 'sign_in_expired')
    return <SignInCard testId="sign-in-lost" title="This sign-in has expired or was already used" description="Start it again from the app’s page." footer={back} />;
  if (finish.isError) return <SignInCard testId="sign-in-failed" title="The sign-in did not finish" description={finish.error.message} footer={back} />;
  if (finish.data?.check && finish.data.health?.status !== 'ok')
    return <SignInCard testId="sign-in-check-failed" title="The test with your account did not pass" description={finish.data.health?.message ?? undefined} footer={back} />;
  if (finish.data?.check)
    return (
      <SignInCard
        testId="sign-in-check-ok"
        title="The auth config works"
        description={finish.data.health?.account ? `Signed in as ${finish.data.health.account}. You can close this window.` : 'You can close this window.'}
        footer={back}
      >
        <CircleCheck className="size-8 text-success-text" />
      </SignInCard>
    );
  if (finish.isSuccess)
    return (
      <SignInCard
        testId="sign-in-connected"
        title={finish.data.alreadyConnectedAs ? `Already connected as ${finish.data.alreadyConnectedAs}` : `${finish.data.account?.name ?? 'The account'} is connected`} description={popup ? 'You can close this window.' : 'Go back to Ops AI; it goes on with your account.'} footer={back}>
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
