'use client';

import * as React from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

import { useSession } from '@/hooks/auth-queries';
import { safeNext } from '@/lib/auth/next-path';

/** Screens a signed-in person has no reason to see; they go on to `next`. */
const SIGNED_OUT_ONLY = ['/login', '/signup', '/sso'];

/** Sign-in screens: no sidebar, a centred column on a muted background. */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const router = useRouter();
  const { status } = useSession();
  const leave = status === 'signed_in' && SIGNED_OUT_ONLY.includes(pathname);
  React.useEffect(() => {
    if (leave) router.replace(safeNext(params.get('next')));
  }, [leave, params, router]);
  return (
    <div className="flex min-h-svh flex-col items-center justify-center bg-muted p-6 md:p-10">
      <div className="w-full max-w-sm md:max-w-3xl">{leave ? null : children}</div>
    </div>
  );
}
