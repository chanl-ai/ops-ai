'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Check, ChevronsUpDown } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { useFlagState } from '@/hooks/flag-queries';
import { useNavAllows } from '@/hooks/me-queries';
import { sectionFor } from '@/lib/nav';

/**
 * The page title as a menu of the other pages in its sidebar section (Brain: Knowledge bases, Sources, Changes,
 * Files). Renders the plain title when the route's sidebar item has no child pages.
 */
/** The pages of the route's sidebar item the person may open, and which one is showing. */
function useSection() {
  const pathname = usePathname();
  const allows = useNavAllows();
  const found = sectionFor(pathname);
  // Only pages the person may open; a page whose answer is still loading waits for it rather than flashing in.
  const section = found && { ...found, pages: found.pages.filter((p) => allows(p.needs) === true) };
  if (!section || section.pages.length < 2) return null;
  // The longest matching href wins, so /knowledge/changes is not also read as /knowledge.
  const current = [...section.pages].sort((a, b) => b.href.length - a.href.length).find((p) => pathname === p.href || pathname.startsWith(`${p.href}/`))?.href;
  return { section, current };
}

/**
 * With the one sidebar (area tabs off), a page's sibling pages are tabs under its title, each its own address
 * (Workflows | Runs, Members | Roles | Tool access), since the sidebar lists one link per page. Nothing with area tabs on,
 * where the title menu and the sidebar's sub-rows offer them.
 */
export function SectionTabs() {
  const found = useSection();
  if (useFlagState('area_tabs') !== 'off' || !found) return null;
  const { section, current } = found;
  return (
    <Tabs value={current ?? ''}>
      <TabsList aria-label={section.label} data-testid="section-tabs">
        {section.pages.map((p) => (
          <TabsTrigger key={p.href} value={p.href} asChild>
            <Link href={p.href} aria-current={p.href === current ? 'page' : undefined} data-testid={`section-tab-${p.href.replace(/\//g, '-').slice(1)}`}>
              {p.icon ? <p.icon className="size-4" /> : null}
              {p.label}
            </Link>
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}

export function TitleSwitcher({ title }: { title: string }) {
  const found = useSection();
  // The one sidebar shows the sibling pages as tabs instead (SectionTabs).
  const single = useFlagState('area_tabs') !== 'on';
  if (!found || single) return <>{title}</>;
  const { section, current } = found;
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
              {p.icon ? <p.icon className="size-4 text-muted-foreground" /> : null}
              <span className="flex-1">{p.label}</span>
              <Check className={p.href === current ? 'size-4' : 'size-4 opacity-0'} />
            </Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
