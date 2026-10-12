'use client';

import * as React from 'react';

import { ForgotPasswordForm } from '@/components/auth/forgot-password-form';
import { SSO_PROVIDER_LABEL } from '@/components/settings/sign-in-sections';
import { ssoDomainFor, useSendReset, useSignInPolicy, useStartSso } from '@/hooks/auth-queries';

export default function ForgotPasswordPage() {
  const send = useSendReset();
  const sso = useStartSso();
  const { data: policy } = useSignInPolicy();
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
        // SSO people have no password here to reset; the API refuses too, this only saves the round trip.
        if (policy?.methods.sso && ssoDomainFor(email, policy.sso.domains)) return setManagedBy({ email, idp: SSO_PROVIDER_LABEL[policy.sso.provider] });
        try {
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
