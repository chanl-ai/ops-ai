'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowLeft, Smartphone } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Input } from '@/components/ui/input';

import { AuthError, AuthFormWrapper, AuthHeading } from './auth-form-wrapper';

/** The second step of a password sign-in: the code from the authenticator app. */
export function MfaVerifyForm({ email, initialCode, pending, error, onVerify }: { email?: string; initialCode?: string; pending: boolean; error: string | null; onVerify: (code: string) => void }) {
  const [code, setCode] = React.useState(initialCode ?? '');
  return (
    <AuthFormWrapper>
      <form
        noValidate
        data-testid="mfa-verify"
        onSubmit={(e) => {
          e.preventDefault();
          if (code.length === 6) onVerify(code);
        }}
      >
        <div className="flex flex-col gap-6">
          <AuthHeading icon={<Smartphone className="size-6" />} title="Two-step verification" description={email ? `Enter the 6-digit code from the authenticator app for ${email}.` : 'Enter the 6-digit code from your authenticator app.'} />
          <FormField id="mfa-code" label="Code">
            <Input id="mfa-code" inputMode="numeric" autoComplete="one-time-code" autoFocus maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} placeholder="e.g. 482913" className="text-center text-lg tracking-widest" />
          </FormField>
          <AuthError message={error} />
          <LoadingButton type="submit" className="w-full" isLoading={pending} loadingText="Checking…" disabled={code.length !== 6} data-testid="mfa-verify-submit">
            Verify
          </LoadingButton>
          <Link href="/login" className="inline-flex items-center justify-center gap-1 text-sm underline underline-offset-4">
            <ArrowLeft className="size-3" /> Back to sign in
          </Link>
        </div>
      </form>
    </AuthFormWrapper>
  );
}
