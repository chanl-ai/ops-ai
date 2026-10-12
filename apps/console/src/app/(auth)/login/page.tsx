'use client';

import * as React from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import { LoginForm } from '@/components/auth/login-form';
import { demoAccount } from '@/lib/api';
import { Skeleton } from '@/components/ui/skeleton';
import { ssoDomainFor, useSignInPolicy, useSignInWithGoogle, useSignInWithPassword, useStartSso } from '@/hooks/auth-queries';
import { safeNext } from '@/lib/auth/next-path';
import type { SignInResult } from '@/lib/auth';

export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get('next'));
  const policy = useSignInPolicy();
  const password = useSignInWithPassword();
  const google = useSignInWithGoogle();
  const sso = useStartSso();
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState<'password' | 'sso' | 'google' | null>(null);

  const after = (r: SignInResult) => {
    if (r.status === 'mfa_required') return router.push(`/mfa/verify?next=${encodeURIComponent(next)}&challenge=${r.challengeId}&email=${encodeURIComponent(r.email)}`);
    // Policy may still require enrolment; the app shell sends an unenrolled session to /mfa/setup.
    router.replace(next);
  };
  const run = async (kind: 'password' | 'sso' | 'google', fn: () => Promise<void>) => {
    setError(null);
    setPending(kind);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
      setPending(null);
    }
  };

  if (policy.isPending) return <Skeleton className="h-[28rem] w-full rounded-xl" />;
  const p = policy.data;
  return (
    <LoginForm
      methods={p?.methods ?? { password: true, sso: false, google: false }}
      ssoDomainOf={(email) => ssoDomainFor(email, p?.sso.domains)}
      selfSignup={!!p?.selfSignup}
      initialEmail={params.get('email') ?? ''}
      demo={demoAccount()}
      pending={pending}
      error={error ?? (policy.isError ? 'Sign-in options could not be loaded. Password sign-in still works.' : null)}
      onPassword={(email, pw) => run('password', async () => after(await password.mutateAsync({ email, password: pw })))}
      onSso={(email) =>
        run('sso', async () => {
          const { redirectUrl } = await sso.mutateAsync({ email });
          window.location.assign(`${redirectUrl}${redirectUrl.includes('?') ? '&' : '?'}next=${encodeURIComponent(next)}`);
        })
      }
      onGoogle={() => run('google', async () => after(await google.mutateAsync()))}
    />
  );
}
