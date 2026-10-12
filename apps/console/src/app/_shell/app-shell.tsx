'use client';

import * as React from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Clock } from 'lucide-react';

import { AppSidebar } from '@/components/app-sidebar';
import { AuthFormWrapper, AuthHeading } from '@/components/auth/auth-form-wrapper';
import { ClientGate } from '@/components/client-gate';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { SiteHeader } from '@/components/site-header';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';
import { useSession, useSignInPolicy, useSignOut } from '@/hooks/auth-queries';
import { authProvider } from '@/lib/auth';
import { isAuthPath } from '@/lib/auth/next-path';

import { HeaderNotifications } from './header-notifications';
import { HeaderSearch } from './header-search';

const Loading = () => (
  <div className="px-6 py-6 lg:px-8">
    <PageSkeleton statCards={4} tableRows={6} />
  </div>
);

/**
 * Sign-in screens render bare; every other route needs a session. Signed out goes to /login with `next`, an expired
 * session gets a sign-in-again screen, and a workspace that requires two-step verification sends an unenrolled
 * session to /mfa/setup before any page loads.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (isAuthPath(pathname)) return <React.Suspense>{children}</React.Suspense>;
  return (
    <React.Suspense fallback={<Loading />}>
      <Guarded>{children}</Guarded>
    </React.Suspense>
  );
}

function Guarded({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const router = useRouter();
  const { session, status } = useSession();
  const policy = useSignInPolicy();
  // `mock` selects a designed state for one load; carried into `next` it would sign the person out again on return.
  const kept = new URLSearchParams(params.toString());
  kept.delete('mock');
  const here = `${pathname}${kept.toString() ? `?${kept.toString()}` : ''}`;
  // Only password sessions enrol here, and only through an adapter that can enrol; SSO and Google people get MFA from their IdP.
  const needsMfa = authProvider.enrolsMfa && status === 'signed_in' && session?.authMethod === 'password' && !!policy.data?.mfaRequired && !session.mfaEnrolled;
  React.useEffect(() => {
    if (status === 'signed_out') router.replace(`/login?next=${encodeURIComponent(here)}`);
    if (needsMfa) router.replace(`/mfa/setup?next=${encodeURIComponent(here)}`);
  }, [status, needsMfa]); // eslint-disable-line react-hooks/exhaustive-deps

  if (status === 'expired') return <SessionExpired name={session?.user.name} next={here} />;
  if (status !== 'signed_in' || needsMfa) return <Loading />;
  return (
    <SidebarProvider style={{ '--header-height': 'calc(var(--spacing) * 14)', '--sidebar-width': '14rem' } as React.CSSProperties}>
      <AppSidebar variant="inset" />
      <SidebarInset className="h-[calc(100svh-1rem)] min-w-0 overflow-hidden">
        <SiteHeader
          actions={
            <>
              <HeaderSearch />
              <HeaderNotifications />
            </>
          }
        />
        <div className="@container/main flex min-h-0 flex-1 flex-col overflow-x-hidden overflow-y-auto">
          <ClientGate fallback={<Loading />}>{children}</ClientGate>
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}

/** Shown in place of the console when the session lifetime has passed; nothing behind it renders. */
function SessionExpired({ name, next }: { name?: string; next: string }) {
  const router = useRouter();
  const signOut = useSignOut();
  return (
    <div className="flex min-h-svh flex-col items-center justify-center bg-muted p-6 md:p-10">
      <div className="w-full max-w-sm">
        <AuthFormWrapper showPanel={false}>
          <div className="flex flex-col gap-6" data-testid="session-expired">
            <AuthHeading icon={<Clock className="size-6" />} title="Your session has ended" description={`${name ? `${name}, you` : 'You'} were signed out after the workspace’s session limit. Sign in again to pick up where you left off.`} />
            <LoadingButton
              className="w-full"
              isLoading={signOut.isPending}
              onClick={async () => {
                await signOut.mutateAsync();
                router.replace(`/login?next=${encodeURIComponent(next)}`);
              }}
            >
              Sign in again
            </LoadingButton>
          </div>
        </AuthFormWrapper>
      </div>
    </div>
  );
}
