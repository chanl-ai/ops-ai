'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';

/**
 * Opens a page's create dialog from a link: `?create=1` (or `?create=<variant>`, e.g. `email`). Closing the
 * dialog drops the parameter so a reload does not reopen it. Used by the command palette's actions.
 */
export function useCreateParam(): [boolean, (open: boolean) => void, string | null] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const value = params.get('create');
  const setOpen = (open: boolean) => {
    const next = new URLSearchParams(params.toString());
    if (open) next.set('create', value ?? '1');
    else next.delete('create');
    const q = next.toString();
    router.replace(q ? `${pathname}?${q}` : pathname, { scroll: false });
  };
  return [value !== null, setOpen, value];
}
