'use client';

import { usePathname } from 'next/navigation';

import { Separator } from '@/components/ui/separator';
import { SidebarTrigger } from '@/components/ui/sidebar';
import { useLookups } from '@/hooks/queries';
import { crumbsFor } from '@/lib/nav';

/** `actions` sits at the right of the bar (search, notifications); the layout passes them in. */
export function SiteHeader({ actions }: { actions?: React.ReactNode }) {
  const pathname = usePathname();
  const crumbs = crumbsFor(pathname);
  const { data: lookups } = useLookups();
  return (
    <header className="flex h-(--header-height) shrink-0 items-center gap-2 border-b">
      <div className="flex w-full items-center gap-1 px-4 lg:gap-2 lg:px-6">
        <SidebarTrigger className="-ml-1" />
        <Separator orientation="vertical" className="mx-2 data-[orientation=vertical]:h-4" />
        <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-sm">
          {crumbs.map((c, i) => (
            <span key={c} className="flex items-center gap-1.5">
              {i > 0 && <span className="text-muted-foreground/40">/</span>}
              <span className={i === crumbs.length - 1 ? 'font-medium' : 'text-muted-foreground'}>{c}</span>
            </span>
          ))}
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {lookups && <span className="hidden text-sm text-muted-foreground xl:inline">{lookups.workspace.name} · {lookups.workspace.environment}</span>}
          {actions}
        </div>
      </div>
    </header>
  );
}
