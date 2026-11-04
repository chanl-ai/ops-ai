'use client';

import * as React from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';

import { SignInCard } from '@/components/connections/sign-in-card';
import { goSignIn, READY_MESSAGE, START_MESSAGE, STOP_MESSAGE, type WindowMessage, rememberSignInApp } from '@/components/connections/sign-in';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useOpenConnectLink } from '@/hooks/connections-queries';
import { ApiError } from '@/lib/api/contract';

const Starting = ({ app, logo }: { app?: string | null; logo?: string | null }) => (
  <SignInCard testId="connect-starting" app={app} logo={logo} title={app ? `Connecting to ${app}` : 'Connecting your account'} description="You sign in on the app’s own page next.">
    <Skeleton className="h-4 w-3/4" />
    <Skeleton className="h-4 w-1/2" />
  </SignInCard>
);

/**
 * Where a chat's Connect card sends the person: opens the single-use link made for them and goes on to the
 * system's own sign-in. Errors keep them here: another person's link, an expired or used one.
 */
function LinkConnect({ link }: { link: string }) {
  const open = useOpenConnectLink();
  const started = React.useRef(false);
  React.useEffect(() => {
    if (started.current || !link) return;
    started.current = true;
    open.mutate(link, {
      // Finishing needs the account's app, which the link's answer names; without it the return page says to start again.
      onSuccess: (s) => goSignIn(s, { appId: s.appId ?? '', accountId: s.connectionId ?? '' }),
    });
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
  return <Starting />;
}

/**
 * The window a Connect button opens on the click: it shows which app it connects while the console starts the
 * sign-in, then goes on to the app's page; a start that failed shows here and in the window that opened it.
 */
function OpenedConnect({ app, logo }: { app: string; logo: string | null }) {
  const [failed, setFailed] = React.useState<string | null>(null);
  React.useEffect(() => {
    rememberSignInApp(app, logo);
    const opener = window.opener as Window | null;
    const onMessage = (e: MessageEvent<WindowMessage>) => {
      if (e.origin !== window.location.origin || e.source !== opener) return;
      if (e.data?.type === START_MESSAGE) goSignIn(e.data.start, e.data.account, { check: e.data.check });
      else if (e.data?.type === STOP_MESSAGE) setFailed(e.data.message);
    };
    window.addEventListener('message', onMessage);
    opener?.postMessage({ type: READY_MESSAGE }, window.location.origin);
    return () => window.removeEventListener('message', onMessage);
  }, [app, logo]);
  if (failed)
    return (
      <SignInCard
        testId="connect-failed"
        app={app}
        logo={logo}
        title={`${app} could not connect`}
        description={failed}
        footer={
          <>
            <Button variant="outline" onClick={() => window.close()} data-testid="connect-close">
              Close
            </Button>
            {/* Reloading says ready again, and the page that opened this window starts the same sign-in again. */}
            <Button onClick={() => window.location.reload()} data-testid="connect-retry">
              Try again
            </Button>
          </>
        }
      />
    );
  return <Starting app={app} logo={logo} />;
}

function ConnectPage() {
  const params = useSearchParams();
  const link = params.get('link') ?? '';
  const app = params.get('app');
  if (app && !link) return <OpenedConnect app={app} logo={params.get('logo')} />;
  return <LinkConnect link={link} />;
}

export default function Page() {
  return <ConnectPage />;
}

