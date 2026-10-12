'use client';

import * as React from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import { MfaVerifyForm } from '@/components/auth/mfa-verify-form';
import { demoAccount } from '@/lib/api';
import { useMfaVerify } from '@/hooks/auth-queries';
import { safeNext } from '@/lib/auth/next-path';

export default function MfaVerifyPage() {
  const router = useRouter();
  const params = useSearchParams();
  const verify = useMfaVerify();
  const [error, setError] = React.useState<string | null>(null);
  return (
    <MfaVerifyForm
      email={params.get('email') ?? undefined}
      initialCode={demoAccount()?.code}
      pending={verify.isPending}
      error={error}
      onVerify={async (code) => {
        setError(null);
        try {
          await verify.mutateAsync({ code, challengeId: params.get('challenge') ?? undefined });
          router.replace(safeNext(params.get('next')));
        } catch (e) {
          setError((e as Error).message);
        }
      }}
    />
  );
}
