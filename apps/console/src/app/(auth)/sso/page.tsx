'use client';

import * as React from 'react';
import { useSearchParams } from 'next/navigation';

import { SsoForm } from '@/components/auth/sso-form';
import { useStartSso } from '@/hooks/auth-queries';
import { safeNext } from '@/lib/auth/next-path';

export default function SsoPage() {
  const params = useSearchParams();
  const next = safeNext(params.get('next'));
  const sso = useStartSso();
  const [error, setError] = React.useState<string | null>(null);
  return (
    <SsoForm
      initialEmail={params.get('email') ?? ''}
      pending={sso.isPending}
      error={error}
      onContinue={async (email) => {
        setError(null);
        try {
          const { redirectUrl } = await sso.mutateAsync({ email, next });
          window.location.assign(redirectUrl);
        } catch (e) {
          setError((e as Error).message);
        }
      }}
    />
  );
}
