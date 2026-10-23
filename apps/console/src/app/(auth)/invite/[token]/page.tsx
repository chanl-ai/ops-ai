'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { Clock, LogIn, MailCheck, SearchX, UserPlus } from 'lucide-react';

import { AuthFormWrapper, AuthHeading } from '@/components/auth/auth-form-wrapper';
import { InviteForm } from '@/components/auth/invite-form';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { Skeleton } from '@/components/ui/skeleton';
import { useAcceptInvite, useInvite } from '@/hooks/account-queries';
import { useSession, useSignInWithPassword, useSignOut, useStartSso } from '@/hooks/auth-queries';
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
  const signOut = useSignOut();
  const { session } = useSession();
  const [error, setError] = React.useState<string>();
  // Set once Join succeeds: the invitation then reads as accepted, which is this person joining, not a used link.
  const [joined, setJoined] = React.useState(false);

  const onSubmit = async (input: { name: string; password?: string }) => {
    setError(undefined);
    try {
      const res = await accept.mutateAsync(input);
      setJoined(true);
      if (invite.data) toast.success(`Welcome to ${invite.data.team}`, { description: `You joined as ${invite.data.role}.` });
      if (res.authMethod === 'session') return router.push(res.next);
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
        <QueryError what="the invitation" onRetry={() => invite.refetch()} error={invite.error} retrying={invite.isFetching} />
      );
    const i = invite.data;
    if (i.state === 'expired')
      return <EmptyState icon={Clock} title="This invitation expired" description={`It was sent ${relativeTime(i.invitedAt)} and links last 7 days. Ask ${i.invitedBy} to send a new one.`} action={{ label: 'Go to sign in', href: '/login' }} testId="invite-expired" />;
    // The person who just joined, or who opens their own accepted invitation signed in, is welcomed in.
    if (joined || (i.state === 'accepted' && session?.user.email?.toLowerCase() === i.email.toLowerCase()))
      return <EmptyState icon={MailCheck} title={`Welcome to ${i.team}`} description={`You joined as ${i.role}. Taking you in…`} action={{ label: `Open ${i.team}`, href: '/' }} />;
    if (i.state === 'accepted')
      return <EmptyState icon={MailCheck} title="This invitation was already used" description={`${i.email} has joined ${i.team}. Sign in with that account.`} action={{ label: 'Sign in', href: `/login?email=${encodeURIComponent(i.email)}` }} testId="invite-used" />;
    // An invitation to an existing account is accepted by that person, signed in as themselves; the link alone never
    // opens their account (platform-service refuses it too).
    if (i.existingAccount) {
      const signedInAs = session?.user.email?.toLowerCase();
      if (signedInAs === i.email.toLowerCase())
        return (
          <EmptyState
            icon={UserPlus}
            title={`Join ${i.team} as ${i.role}`}
            description={`${i.invitedBy} invited you. You are signed in as ${i.email}.${error ? ` ${error}` : ''}`}
            action={{ label: accept.isPending ? 'Joining…' : `Join ${i.team}`, onClick: () => void onSubmit({ name: session?.user.name ?? i.email }), disabled: accept.isPending }}
            testId="invite-join"
          />
        );
      const login = `/login?email=${encodeURIComponent(i.email)}&next=${encodeURIComponent(`/invite/${token}`)}`;
      return (
        <EmptyState
          icon={LogIn}
          title={`Sign in as ${i.email} to accept`}
          description={signedInAs ? `This invitation is for ${i.email}, and you are signed in as ${signedInAs}. Sign out, then sign in as ${i.email}.` : `${i.email} already has an account. Sign in, and you come back here to join ${i.team}.`}
          action={signedInAs ? { label: 'Sign out', onClick: () => void signOut.mutateAsync().then(() => router.push(login)) } : { label: `Sign in as ${i.email}`, href: login }}
          testId="invite-sign-in-first"
        />
      );
    }
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
