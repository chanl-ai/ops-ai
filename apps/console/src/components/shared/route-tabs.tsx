'use client';

import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';

import { TabLabel } from '@/components/shared/tab-label';

/**
 * Page-level tabs where each tab is its own route, rendered in PageLayout's `tabs` slot. A tab may carry a query
 * (`/tools?kind=app`, a filtered view of the same list): it is active only on its path with that query, and wins over a
 * tab of the same path without one.
 *
 * Each tab navigates to a page, so this is a nav of links with `aria-current="page"` on the active one, drawn like the
 * Tabs primitive. ARIA tab roles would promise panels on this page that a screen reader cannot reach.
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
    <nav aria-label="Page sections">
      {/* data-slot keeps PageLayout's tab row sizing (`[data-slot=tabs-list]`); the classes match components/ui/tabs.tsx. */}
      <ul data-slot="tabs-list" className="bg-muted text-muted-foreground inline-flex h-9 w-fit items-center justify-center rounded-lg p-[3px]">
        {tabs.map((t) => (
          <li key={t.href} className="flex h-full">
            <Link
              href={t.href}
              data-testid={t.testId}
              aria-current={t.href === active ? 'page' : undefined}
              className="aria-[current=page]:bg-card dark:aria-[current=page]:text-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:outline-ring dark:aria-[current=page]:border-input dark:aria-[current=page]:bg-input/30 text-foreground dark:text-muted-foreground inline-flex h-[calc(100%-1px)] flex-1 items-center justify-center gap-1.5 rounded-md border border-transparent px-2 py-1 text-sm font-medium whitespace-nowrap transition-[color,box-shadow] focus-visible:ring-[3px] focus-visible:outline-1 aria-[current=page]:shadow-sm [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4"
            >
              <TabLabel label={t.label} />
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
