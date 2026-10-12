'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { Clock, MailCheck, SearchX, UserPlus } from 'lucide-react';

import { AuthFormWrapper, AuthHeading } from '@/components/auth/auth-form-wrapper';
import { InviteForm } from '@/components/auth/invite-form';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { Skeleton } from '@/components/ui/skeleton';
import { useAcceptInvite, useInvite } from '@/hooks/account-queries';
import { useSignInWithPassword, useStartSso } from '@/hooks/auth-queries';
import { ApiError } from '@/lib/api';
import { relativeTime } from '@/lib/format';

/** Accept an invitation and land signed in: password accounts sign in with the password just set, SSO accounts go to their IdP. */
export default function InvitePage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const invite = useInvite(token);
  const accept = useAcceptInvite(token);
  const signIn = useSignInWithPassword();
  const sso = useStartSso();
  const [error, setError] = React.useState<string>();

  const onSubmit = async (input: { name: string; password?: string }) => {
    setError(undefined);
    try {
      const res = await accept.mutateAsync(input);
      if (res.authMethod === 'sso') {
        const { redirectUrl } = await sso.mutateAsync({ email: res.email });
        return router.push(redirectUrl);
      }
      const r = await signIn.mutateAsync({ email: res.email, password: input.password ?? '' });
      router.push(r.status === 'mfa_required' ? `/mfa/verify?challenge=${encodeURIComponent(r.challengeId)}` : res.next);
    } catch (e) {
      setError((e as Error).message);
      invite.refetch();
    }
  };

  const body = (() => {
    if (invite.isPending)
      return (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton className="h-14" />
          <Skeleton className="h-9" />
          <Skeleton className="h-9" />
          <Skeleton className="h-9 w-32" />
        </div>
      );
    if (invite.isError)
      return invite.error instanceof ApiError && invite.error.status === 404 ? (
        <EmptyState icon={SearchX} title="This invitation link is not valid" description="Check the link in the email, or ask the person who invited you to send a new one." action={{ label: 'Go to sign in', href: '/login' }} testId="invite-not-found" />
      ) : (
        <QueryError what="the invitation" onRetry={() => invite.refetch()} retrying={invite.isFetching} />
      );
    const i = invite.data;
    if (i.state === 'expired')
      return <EmptyState icon={Clock} title="This invitation expired" description={`It was sent ${relativeTime(i.invitedAt)} and links last 7 days. Ask ${i.invitedBy} to send a new one.`} action={{ label: 'Go to sign in', href: '/login' }} testId="invite-expired" />;
    if (i.state === 'accepted')
      return <EmptyState icon={MailCheck} title="This invitation was already used" description={`${i.email} has joined ${i.team}. Sign in with that account.`} action={{ label: 'Sign in', href: `/login?email=${encodeURIComponent(i.email)}` }} testId="invite-used" />;
    return <InviteForm invite={i} pending={accept.isPending || signIn.isPending || sso.isPending} error={error} onSubmit={onSubmit} />;
  })();

  return (
    <AuthFormWrapper>
      <div className="flex flex-col gap-6">
        <AuthHeading title="Join Ops AI" description="Set up your account to accept the invitation." icon={<UserPlus className="size-6" />} />
        {body}
        <p className="text-center text-sm text-muted-foreground">
          Already have an account?{' '}
          <Link href="/login" className="underline underline-offset-4">
            Sign in
          </Link>
        </p>
      </div>
    </AuthFormWrapper>
  );
}
