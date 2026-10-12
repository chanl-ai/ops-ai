'use client';

import * as React from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import { MfaSetupForm } from '@/components/auth/mfa-setup-form';
import { Skeleton } from '@/components/ui/skeleton';
import { useMfaEnrol, useMfaSetup, useSession } from '@/hooks/auth-queries';
import { safeNext } from '@/lib/auth/next-path';

/** Enrolment, reached when the workspace requires two-step verification and the session has none. Needs a session. */
export default function MfaSetupPage() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get('next'));
  const { status } = useSession();
  const setup = useMfaSetup();
  const enrol = useMfaEnrol();
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (status === 'signed_out') router.replace(`/login?next=${encodeURIComponent(`/mfa/setup?next=${next}`)}`);
    if (status === 'signed_in' && !setup.data && !setup.isPending) setup.mutate();
  }, [status]); // eslint-disable-line react-hooks/exhaustive-deps
  if (status === 'loading' || status === 'signed_out') return <Skeleton className="h-[32rem] w-full rounded-xl" />;
  return (
    <MfaSetupForm
      setup={setup.data}
      loading={setup.isPending}
      pending={enrol.isPending}
      error={error ?? (setup.isError ? setup.error.message : null)}
      onEnrol={async (code) => {
        setError(null);
        try {
          await enrol.mutateAsync(code);
          router.replace(next);
        } catch (e) {
          setError((e as Error).message);
        }
      }}
    />
  );
}
