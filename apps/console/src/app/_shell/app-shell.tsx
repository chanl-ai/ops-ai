'use client';

import * as React from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Clock, CloudOff, Users } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';

import { WhatsNew } from '@/components/shared/whats-new';
import { AppSidebar } from '@/components/app-sidebar';
import { SettingsSidebar } from '@/components/settings/settings-sidebar';
import { AuthFormWrapper, AuthHeading } from '@/components/auth/auth-form-wrapper';
import { ClientGate } from '@/components/client-gate';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { SiteHeader } from '@/components/site-header';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';
import { useSession, useSignInPolicy, useSignOut } from '@/hooks/auth-queries';
import { useTeam, useTeamReady } from '@/hooks/use-team';
import { currentTeamId, ownTeamId, setCurrentTeamId } from '@/lib/api';
import { isUnreachable } from '@/lib/api/unreachable';
import { authProvider } from '@/lib/auth';
import { isAuthPath } from '@/lib/auth/next-path';
import { teamToUse } from '@/lib/session-gate';
import { inSettings, LIVE_TREE } from '@/lib/settings-tree';

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
  // The c-131 embed mock draws a bank intranet page and the iframe chat bare, as the embed app will; only on a
  // development server (src/proxy.ts answers 404 for /dev otherwise), and dropped with the mock in c-158.
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
  // The person's teams are the first thing every page needs. A 401 there, after the token was renewed once, means the
  // session is over; a 5xx or no answer at all means the services are down, which one shell state says for every page.
  const { error: teamsError, teams, isPending: teamsPending } = useTeam();
  const teamsStatus = (teamsError as { status?: number } | null)?.status;
  const unreachable = isUnreachable(teamsError);
  // Pages render, and team queries run (hooks/team-query.ts), only once the current team is one the person holds. A team
  // remembered in this tab from an earlier sign-in, or the console default, gives way to their own team or their first.
  const teamReady = useTeamReady();
  const teamIds = teams.map((t) => t.id).join(',');
  React.useEffect(() => {
    if (status !== 'signed_in' || teamReady || !teamIds) return;
    const pick = teamToUse(currentTeamId(), ownTeamId(), teamIds.split(','));
    if (pick) setCurrentTeamId(pick);
  }, [status, teamReady, teamIds]);
  React.useEffect(() => {
    if (status === 'signed_out' || teamsStatus === 401) router.replace(`/login?next=${encodeURIComponent(here)}`);
    if (needsMfa) router.replace(`/mfa/setup?next=${encodeURIComponent(here)}`);
  }, [status, needsMfa, teamsStatus]); // eslint-disable-line react-hooks/exhaustive-deps

  if (status === 'expired') return <SessionExpired name={session?.user.name} next={here} />;
  if (status === 'signed_in' && unreachable) return <ServicesUnavailable />;
  if (status !== 'signed_in' || needsMfa) return <Loading />;
  if (!teamsPending && !teamsError && teams.length === 0) return <NoTeam />;
  if (!teamReady) return <Loading />;
  return (
    <SidebarProvider style={{ '--header-height': 'calc(var(--spacing) * 14)', '--sidebar-width': '14rem' } as React.CSSProperties}>
      {/* Inside settings the app sidebar is replaced by the settings sidebar. */}
      {inSettings(pathname) ? <SettingsSidebar variant="inset" tree={LIVE_TREE} /> : <AppSidebar variant="inset" />}
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
      <WhatsNew />
    </SidebarProvider>
  );
}

/** Shown in place of the console when the session lifetime has passed; nothing behind it renders. */
/** Every page's data is out of reach: said once, with a retry that asks again for everything on screen. */
export function ServicesUnavailable() {
  const qc = useQueryClient();
  const [retrying, setRetrying] = React.useState(false);
  return (
    <div className="flex min-h-svh flex-col items-center justify-center bg-muted p-6 md:p-10">
      <div className="w-full max-w-sm">
        <AuthFormWrapper showPanel={false}>
          <div className="flex flex-col gap-6" data-testid="services-unavailable">
            <AuthHeading icon={<CloudOff className="size-6" />} title="Ops AI can’t reach its services right now" description="Your work is safe. Try again in a moment; if it keeps happening, tell your administrator." />
            <LoadingButton
              className="w-full"
              isLoading={retrying}
              onClick={async () => {
                setRetrying(true);
                await qc.refetchQueries({ type: 'active' }).finally(() => setRetrying(false));
              }}
              data-testid="services-retry"
            >
              Try again
            </LoadingButton>
          </div>
        </AuthFormWrapper>
      </div>
    </div>
  );
}

/** Signed in, but in no team yet: every page's data belongs to a team, so nothing behind this can load. */
function NoTeam() {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center bg-muted p-6 md:p-10">
      <div className="w-full max-w-sm">
        <AuthFormWrapper showPanel={false}>
          <div className="flex flex-col gap-6" data-testid="no-team">
            <AuthHeading icon={<Users className="size-6" />} title="You aren’t in a team yet" description="Everything in Ops AI belongs to a team. Ask a workspace admin to add you to one, then sign in again." />
          </div>
        </AuthFormWrapper>
      </div>
    </div>
  );
}

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
