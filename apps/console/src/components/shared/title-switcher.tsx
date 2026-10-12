'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Check, ChevronsUpDown } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { sectionFor } from '@/lib/nav';

/**
 * The page title as a menu of the other pages in its sidebar section (Brain: Knowledge bases, Sources, Changes,
 * Files). Renders the plain title when the route's sidebar item has no child pages.
 */
export function TitleSwitcher({ title }: { title: string }) {
  const pathname = usePathname();
  const section = sectionFor(pathname);
  if (!section) return <>{title}</>;
  // The longest matching href wins, so /knowledge/changes is not also read as /knowledge.
  const current = [...section.pages].sort((a, b) => b.href.length - a.href.length).find((p) => pathname === p.href || pathname.startsWith(`${p.href}/`))?.href;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="-ml-2 h-auto gap-1.5 px-2 py-0.5 text-xl font-semibold sm:text-2xl" aria-label={`Switch page in ${section.label}`} data-testid="title-switcher">
          {title}
          <ChevronsUpDown className="size-4 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-56">
        <DropdownMenuLabel className="text-xs text-muted-foreground">{section.label}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {section.pages.map((p) => (
          <DropdownMenuItem key={p.href} asChild>
            <Link href={p.href} aria-current={p.href === current ? 'page' : undefined} data-testid={`title-switcher-${p.href.replace(/\//g, '-').slice(1)}`}>
              <Check className={p.href === current ? 'size-4' : 'size-4 opacity-0'} />
              {p.label}
            </Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
