'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { Separator } from '@/components/ui/separator';
import { SidebarTrigger } from '@/components/ui/sidebar';
import { useWorkspaceIdentity } from '@/hooks/me-queries';
import { useBrand } from '@/hooks/queries';
import { crumbsFor } from '@/lib/nav';

/** `actions` sits at the right of the bar (search, notifications); the layout passes them in. */
export function SiteHeader({ actions }: { actions?: React.ReactNode }) {
  const pathname = usePathname();
  const crumbs = crumbsFor(pathname);
  const identity = useWorkspaceIdentity();
  const brand = useBrand();
  return (
    <header className="flex h-(--header-height) shrink-0 items-center gap-2 border-b">
      <div className="flex w-full items-center gap-1 px-4 lg:gap-2 lg:px-6">
        <SidebarTrigger className="-ml-1" />
        <Separator orientation="vertical" className="mx-2 data-[orientation=vertical]:h-4" />
        <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-sm">
          {crumbs.map((c, i) => (
            // On a phone the trail keeps its links and the page; a label with no page of its own (a group) is dropped.
            <span key={`${i}-${c.label}`} className={`flex min-w-0 items-center gap-1.5 ${!c.href && i > 0 && i < crumbs.length - 1 ? 'max-sm:hidden' : ''}`} title={c.label}>
              {i > 0 && <span className="text-muted-foreground/40">/</span>}
              {c.href ? (
                <Link href={c.href} className={`truncate underline-offset-4 hover:underline ${i === crumbs.length - 1 ? 'font-medium' : 'text-muted-foreground hover:text-foreground'}`}>
                  {c.label}
                </Link>
              ) : (
                <span className={`truncate ${i === crumbs.length - 1 ? 'font-medium' : 'text-muted-foreground'}`}>{c.label}</span>
              )}
            </span>
          ))}
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {identity && (
            <span className="hidden text-sm text-muted-foreground xl:inline" data-testid="header-workspace">
              {brand.name ?? identity.workspace}
              {identity.environment ? ` · ${identity.environment}` : ''}
            </span>
          )}
          {actions}
        </div>
      </div>
    </header>
  );
}
