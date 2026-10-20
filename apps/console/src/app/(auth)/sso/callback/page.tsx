'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Loader2 } from 'lucide-react';

import { AuthError, AuthFormWrapper, AuthHeading } from '@/components/auth/auth-form-wrapper';
import { useCompleteSso, useCompleteSsoStepUp } from '@/hooks/auth-queries';
import { safeNext } from '@/lib/auth/next-path';

/** Where the identity provider sends the browser back: exchanges its code for a session, or with ?stepUp=1 for a step-up token. */
export default function SsoCallbackPage() {
  const router = useRouter();
  const params = useSearchParams();
  const complete = useCompleteSso();
  const completeStepUp = useCompleteSsoStepUp();
  const stepUp = params.get('stepUp') === '1';
  const [error, setError] = React.useState<string | null>(null);
  const started = React.useRef(false);
  React.useEffect(() => {
    if (started.current) return;
    started.current = true;
    const code = params.get('code');
    if (params.get('error')) {
      setError(stepUp ? 'Your company sign-in did not confirm it is you. Try again.' : 'Your company sign-in did not let you in. Try again, or ask your workspace admin.');
      return;
    }
    if (!code) {
      setError('The sign-in link from your identity provider is missing its code. Start again.');
      return;
    }
    (stepUp ? completeStepUp.mutateAsync(code) : complete.mutateAsync(code)).then(
      () => router.replace(safeNext(params.get('next'))),
      (e: Error) => setError(e.message),
    );
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <AuthFormWrapper showPanel={false} className="mx-auto max-w-sm">
      <div className="flex flex-col gap-6" data-testid="sso-callback">
        <AuthHeading icon={error ? undefined : <Loader2 className="size-6 animate-spin" />} title={error ? (stepUp ? 'Verification did not finish' : 'Sign-in did not finish') : stepUp ? 'Confirming it’s you…' : 'Signing you in…'} />
        <AuthError message={error} />
        {error && (
          <Link href={stepUp ? safeNext(params.get('next')) : '/sso'} className="text-center text-sm underline underline-offset-4">
            {stepUp ? 'Go back' : 'Try SSO again'}
          </Link>
        )}
      </div>
    </AuthFormWrapper>
  );
}
