'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ArrowLeft, Search } from 'lucide-react';

import { Kbd } from '@/components/ui/kbd';
import { Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuButton, SidebarInput, SidebarMenuItem, SidebarMenuSub, SidebarMenuSubButton, SidebarMenuSubItem, SidebarSeparator } from '@/components/ui/sidebar';
import type { SidebarTree } from '@/lib/settings-tree';

/**
 * Replaces the app sidebar while a person is in settings: a back arrow, a Find box (press F) that searches every
 * setting, a flat list of sections, and the person's own items at the bottom.
 */
export function SettingsSidebar({ tree, ...props }: React.ComponentProps<typeof Sidebar> & { tree: SidebarTree }) {
  const pathname = usePathname();
  const [query, setQuery] = React.useState('');
  const find = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.key.toLowerCase() !== 'f' || e.metaKey || e.ctrlKey || e.altKey) return;
      if (t && (t.isContentEditable || /^(input|textarea|select)$/i.test(t.tagName))) return;
      e.preventDefault();
      find.current?.focus();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);
  const hits = tree.find(query);
  // The longest matching route is the current page, so /settings/team lights for General and not for Webhooks beneath it.
  const hrefs = tree.groups.flatMap((g) => g.items.flatMap((i) => [i.href, ...(i.children?.map((c) => c.href) ?? [])]));
  const current = hrefs.filter((h) => pathname === h || pathname.startsWith(`${h}/`)).sort((a, b) => b.length - a.length)[0];
  const link = (href: string) => (href.includes('#') ? href.split('#')[0] : href);

  return (
    <Sidebar collapsible="offcanvas" {...props}>
      <SidebarHeader className="gap-3">
        <div className="flex items-center gap-2 px-1">
          <Link href="/" aria-label="Back to the console" className="flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
            <ArrowLeft className="size-4" />
          </Link>
          <Link href={tree.home} className="text-sm font-semibold">
            Settings
          </Link>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <SidebarInput
            ref={find}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Escape' && (setQuery(''), find.current?.blur())}
            placeholder="Find a setting"
            aria-label="Find a setting"
            data-testid="settings-find"
            className="h-9 bg-card pr-9 pl-8"
          />
          <Kbd className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2">F</Kbd>
        </div>
      </SidebarHeader>
      <SidebarContent>
        {query.trim() ? (
          <SidebarGroup>
            <SidebarGroupLabel>{hits.length ? `${hits.length} found` : 'Nothing found'}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu data-testid="settings-find-results">
                {hits.map((h) => (
                  <SidebarMenuItem key={`${h.label}-${h.href}`}>
                    <SidebarMenuButton asChild className="h-auto flex-col items-start gap-0 py-1.5">
                      <Link href={h.href} onClick={() => setQuery('')}>
                        <span className="text-sm">{h.label}</span>
                        <span className="text-xs text-muted-foreground">{h.where}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ) : (
          tree.groups.map((g) => (
            <SidebarGroup key={g.label}>
              <SidebarGroupLabel>{g.label}</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {g.items.map((s) => {
                    const within = (href: string) => href === current;
                    const active = s.children ? s.children.some((c) => within(c.href)) : within(s.href);
                    return (
                      <SidebarMenuItem key={s.id}>
                        <SidebarMenuButton asChild isActive={active && !s.children}>
                          <Link href={s.href}>{s.label}</Link>
                        </SidebarMenuButton>
                        {s.children && (
                          <SidebarMenuSub>
                            {s.children.map((c) => (
                              <SidebarMenuSubItem key={c.id}>
                                <SidebarMenuSubButton asChild isActive={within(c.href)}>
                                  <Link href={c.href}>{c.label}</Link>
                                </SidebarMenuSubButton>
                              </SidebarMenuSubItem>
                            ))}
                          </SidebarMenuSub>
                        )}
                      </SidebarMenuItem>
                    );
                  })}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ))
        )}
      </SidebarContent>
      <SidebarFooter className="gap-2">
        <SidebarSeparator className="mx-0" />
        <SidebarMenu>
          {tree.personal.map((s) => (
            <SidebarMenuItem key={s.id}>
              <SidebarMenuButton asChild isActive={pathname === link(s.href)}>
                <Link href={s.href}>{s.label}</Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
