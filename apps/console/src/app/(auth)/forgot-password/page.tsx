'use client';

import * as React from 'react';

import { ForgotPasswordForm } from '@/components/auth/forgot-password-form';
import { useAskSignInOptions, useSendReset, useStartSso } from '@/hooks/auth-queries';

export default function ForgotPasswordPage() {
  const send = useSendReset();
  const sso = useStartSso();
  const ask = useAskSignInOptions();
  const [sent, setSent] = React.useState<{ to: string; previewUrl?: string } | null>(null);
  const [managedBy, setManagedBy] = React.useState<{ email: string; idp: string } | undefined>();
  const [error, setError] = React.useState<string | null>(null);
  return (
    <ForgotPasswordForm
      pending={send.isPending}
      error={error}
      sentTo={sent?.to ?? null}
      previewUrl={sent?.previewUrl}
      managedBy={managedBy}
      ssoPending={sso.isPending}
      onSend={async (email) => {
        setError(null);
        try {
          // SSO people have no password here to reset; the API sends nothing either, this says why.
          const options = await ask.mutateAsync(email).catch(() => null);
          if (options?.sso && !options.password) return setManagedBy({ email, idp: options.sso.label });
          const r = await send.mutateAsync(email);
          setSent({ to: email, previewUrl: r.previewUrl });
        } catch (e) {
          setError((e as Error).message);
        }
      }}
      onSso={async (email) => {
        setError(null);
        try {
          window.location.assign((await sso.mutateAsync({ email })).redirectUrl);
        } catch (e) {
          setError((e as Error).message);
        }
      }}
    />
  );
}
