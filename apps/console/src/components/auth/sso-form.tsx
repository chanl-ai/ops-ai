'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowLeft, KeyRound } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Input } from '@/components/ui/input';

import { AuthError, AuthFormWrapper, AuthHeading } from './auth-form-wrapper';

/** Work email for single sign-on; the page sends the browser to the identity provider it resolves to. */
export function SsoForm({ initialEmail = '', pending, error, onContinue }: { initialEmail?: string; pending: boolean; error: string | null; onContinue: (email: string) => void }) {
  const [email, setEmail] = React.useState(initialEmail);
  const [missing, setMissing] = React.useState<string | null>(null);
  return (
    <AuthFormWrapper>
      <form
        noValidate
        data-testid="sso-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) return setMissing('Enter your work email.');
          onContinue(email.trim());
        }}
      >
        <div className="flex flex-col gap-6">
          <AuthHeading icon={<KeyRound className="size-6" />} title="Sign in with SSO" description="Use your company account. You will be sent to your identity provider and back." />
          <FormField id="sso-email" label="Work email" error={missing ?? undefined}>
            <Input id="sso-email" type="email" autoFocus value={email} aria-invalid={!!missing} onChange={(e) => (setEmail(e.target.value), setMissing(null))} placeholder="e.g. name@northfield.ca" />
          </FormField>
          <AuthError message={error} />
          <LoadingButton type="submit" className="w-full" isLoading={pending} loadingText="Opening your sign-in…" data-testid="sso-continue">
            Continue
          </LoadingButton>
          <Link href="/login" className="inline-flex items-center justify-center gap-1 text-sm underline underline-offset-4">
            <ArrowLeft className="size-3" /> Back to sign in
          </Link>
        </div>
      </form>
    </AuthFormWrapper>
  );
}
