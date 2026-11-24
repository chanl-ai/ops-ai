'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Loader2 } from 'lucide-react';

import { AuthError, AuthFormWrapper, AuthHeading } from '@/components/auth/auth-form-wrapper';
import { toast } from 'sonner';

import { useCompleteSso, useCompleteSsoLink, useCompleteSsoStepUp } from '@/hooks/auth-queries';
import { safeNext } from '@/lib/auth/next-path';
import { ssoReturn } from '@/lib/auth/sso-return';

/** Where the identity provider sends the browser back: exchanges its code for a session, with ?stepUp=1 for a step-up token, or with ?link=1 links the signed-in person's account there. */
export default function SsoCallbackPage() {
  const router = useRouter();
  const params = useSearchParams();
  const complete = useCompleteSso();
  const completeStepUp = useCompleteSsoStepUp();
  const completeLink = useCompleteSsoLink();
  const stepUp = params.get('stepUp') === '1';
  const link = params.get('link') === '1';
  const returned = ssoReturn(params);
  const linkRequired = returned === 'link_required';
  const [error, setError] = React.useState<string | null>(null);
  const started = React.useRef(false);
  React.useEffect(() => {
    if (started.current) return;
    started.current = true;
    const code = params.get('code');
    if (linkRequired) return; // Shown below as its own message, not as an error.
    if (returned === 'refused') {
      setError(link ? 'Your company sign-in did not link: it must be your own, verified email at the provider. Nothing was linked.' : stepUp ? 'Your company sign-in did not confirm it is you. Try again.' : 'Your company sign-in did not let you in. Try again, or ask your workspace admin.');
      return;
    }
    if (!code) {
      setError('The sign-in link from your identity provider is missing its code. Start again.');
      return;
    }
    if (link) {
      completeLink.mutateAsync(code).then(
        () => (toast.success('Linked', { description: 'You can now sign in with your company account.' }), router.replace(safeNext(params.get('next')))),
        (e: Error & { status?: number }) => setError(e.status === 409 ? 'This account at your company’s provider is linked already, or you already have one linked. Nothing changed.' : e.message === 'Sign in again.' ? 'Your company sign-in did not link: it must be your own, verified email at the provider, from this browser. Nothing was linked.' : e.message),
      );
      return;
    }
    (stepUp ? completeStepUp.mutateAsync(code) : complete.mutateAsync(code)).then(
      () => router.replace(safeNext(params.get('next'))),
      (e: Error) => setError(e.message),
    );
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (linkRequired)
    return (
      <AuthFormWrapper showPanel={false} className="mx-auto max-w-sm">
        <div className="flex flex-col gap-6" data-testid="sso-link-required">
          <AuthHeading title="This email already has an account" description="Sign in the usual way, then link your company account from My security. Or ask an admin for a new invite." />
          <Link href="/login" className="text-center text-sm underline underline-offset-4">
            Go to sign in
          </Link>
        </div>
      </AuthFormWrapper>
    );
  return (
    <AuthFormWrapper showPanel={false} className="mx-auto max-w-sm">
      <div className="flex flex-col gap-6" data-testid="sso-callback">
        <AuthHeading icon={error ? undefined : <Loader2 className="size-6 animate-spin" />} title={error ? (link ? 'Linking did not finish' : stepUp ? 'Verification did not finish' : 'Sign-in did not finish') : link ? 'Linking your account…' : stepUp ? 'Confirming it’s you…' : 'Signing you in…'} />
        <AuthError message={error} />
        {error && (
          <Link href={stepUp || link ? safeNext(params.get('next')) : '/sso'} className="text-center text-sm underline underline-offset-4">
            {stepUp || link ? 'Go back' : 'Try SSO again'}
          </Link>
        )}
      </div>
    </AuthFormWrapper>
  );
}
