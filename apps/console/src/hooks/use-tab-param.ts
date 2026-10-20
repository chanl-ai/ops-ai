'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';

/** Keeps the active tab in `?tab=` so record tabs can be linked to and survive a reload. */
export function useTabParam<T extends string>(tabs: readonly T[], fallback: T): [T, (t: T) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get('tab') as T | null;
  const tab = raw && tabs.includes(raw) ? raw : fallback;
  const setTab = (t: T) => {
    const next = new URLSearchParams(params.toString());
    if (t === fallback) next.delete('tab');
    else next.set('tab', t);
    const q = next.toString();
    router.replace(q ? `${pathname}?${q}` : pathname, { scroll: false });
  };
  return [tab, setTab];
}
