'use client';

import Link from 'next/link';
import { UserPlus } from 'lucide-react';

import { AuthFormWrapper, AuthHeading } from '@/components/auth/auth-form-wrapper';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useSignInPolicy } from '@/hooks/auth-queries';

/** Accounts come from invites unless the workspace turns on self sign-up, and then through the company IdP. */
export default function SignupPage() {
  const policy = useSignInPolicy();
  if (policy.isPending) return <Skeleton className="h-72 w-full rounded-xl" />;
  const open = !!policy.data?.selfSignup;
  return (
    <AuthFormWrapper>
      <div className="flex flex-col gap-6" data-testid="signup">
        <AuthHeading
          icon={<UserPlus className="size-6" />}
          title={open ? 'Create your account' : 'Ask your admin for an invite'}
          description={open ? 'Sign up with your work email through your company’s identity provider.' : 'Harbor & Pine Ops AI accounts are created by invite. Your workspace admin can send you one from Settings → Members.'}
        />
        <Button asChild className="w-full">
          <Link href={open ? '/sso' : '/login'}>{open ? 'Continue with SSO' : 'Back to sign in'}</Link>
        </Button>
      </div>
    </AuthFormWrapper>
  );
}
