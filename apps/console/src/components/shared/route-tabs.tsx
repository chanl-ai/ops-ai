'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';

/** Page-level tabs where each tab is its own route, rendered in PageLayout's `tabs` slot. */
export function RouteTabs({ tabs }: { tabs: { href: string; label: React.ReactNode }[] }) {
  const pathname = usePathname();
  const active = [...tabs].sort((a, b) => b.href.length - a.href.length).find((t) => pathname.startsWith(t.href))?.href;
  return (
    <Tabs value={active}>
      <TabsList>
        {tabs.map((t) => (
          <TabsTrigger key={t.href} value={t.href} asChild>
            <Link href={t.href}>{t.label}</Link>
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
