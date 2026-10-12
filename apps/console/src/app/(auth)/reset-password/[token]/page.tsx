'use client';

import * as React from 'react';
import { useParams } from 'next/navigation';

import { ResetPasswordForm } from '@/components/auth/reset-password-form';
import { useResetPassword } from '@/hooks/auth-queries';

export default function ResetPasswordPage() {
  const { token } = useParams<{ token: string }>();
  const reset = useResetPassword();
  const [error, setError] = React.useState<string | null>(null);
  return (
    <ResetPasswordForm
      pending={reset.isPending}
      done={reset.isSuccess}
      error={error}
      onReset={async (password) => {
        setError(null);
        try {
          await reset.mutateAsync({ token, password });
        } catch (e) {
          setError((e as Error).message);
        }
      }}
    />
  );
}
