'use client';

import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';

import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { TabLabel } from '@/components/shared/tab-label';

/**
 * Page-level tabs where each tab is its own route, rendered in PageLayout's `tabs` slot. A tab may carry a query
 * (`/tools?kind=app`, a filtered view of the same list): it is active only on its path with that query, and wins over a
 * tab of the same path without one.
 */
export function RouteTabs({ tabs }: { tabs: { href: string; label: React.ReactNode; testId?: string }[] }) {
  const pathname = usePathname();
  const search = useSearchParams();
  const matches = (href: string) => {
    const [path, query] = href.split('?');
    if (!query) return pathname.startsWith(path);
    return pathname === path && [...new URLSearchParams(query)].every(([k, v]) => search.get(k) === v);
  };
  const score = (href: string) => (href.includes('?') ? 10_000 : 0) + href.length;
  const active = [...tabs].sort((a, b) => score(b.href) - score(a.href)).find((t) => matches(t.href))?.href;
  return (
    <Tabs value={active}>
      <TabsList>
        {tabs.map((t) => (
          // Each tab is a page, not a panel on this one: no aria-controls naming a panel that does not exist, and the
          // current page marked as such.
          <TabsTrigger key={t.href} value={t.href} asChild aria-controls={undefined}>
            <Link href={t.href} data-testid={t.testId} aria-current={t.href === active ? 'page' : undefined}>
              <TabLabel label={t.label} />
            </Link>
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
