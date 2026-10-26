'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { AlertCircle, ChevronRight, RotateCw } from 'lucide-react';

import { NavUser } from '@/components/nav-user';
import { PreviewBadge } from '@/components/shared/preview-badge';
import { TeamSwitcher } from '@/components/team-switcher';
import { Badge } from '@/components/ui/badge';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarRail,
} from '@/components/ui/sidebar';
import { useTeamRole, useWorkspaceIdentity } from '@/hooks/me-queries';
import { useBrand, useLookups, useOpenReviewCount } from '@/hooks/queries';
import { usePreviewCheck } from '@/hooks/use-preview';
import { useTeam } from '@/hooks/use-team';
import { NAV, navMatch } from '@/lib/nav';

// Parents a viewer has closed, kept in this browser only: every parent starts open, and the sidebar works the same
// when storage is unavailable.
const CLOSED_KEY = 'ops.sidebar.closed';

function useClosedSections(): [Set<string>, (url: string, open: boolean) => void] {
  const [closed, setClosed] = React.useState<Set<string>>(() => new Set());
  React.useEffect(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem(CLOSED_KEY) ?? '[]');
      if (Array.isArray(saved)) setClosed(new Set(saved.filter((x): x is string => typeof x === 'string')));
    } catch {
      // No storage, or a value this version cannot read: every parent stays open.
    }
  }, []);
  const toggle = React.useCallback((url: string, open: boolean) => {
    setClosed((prev) => {
      const next = new Set(prev);
      if (open) next.delete(url);
      else next.add(url);
      try {
        window.localStorage.setItem(CLOSED_KEY, JSON.stringify([...next]));
      } catch {
        // Not remembered; the change still applies on this page.
      }
      return next;
    });
  }, []);
  return [closed, toggle];
}

export function AppSidebar(props: React.ComponentProps<typeof Sidebar>) {
  const pathname = usePathname();
  const isPreview = usePreviewCheck();
  const [closed, toggleSection] = useClosedSections();
  const brand = useBrand();
  const { data: openReviews } = useOpenReviewCount();
  const { data: lookups, isError: lookupsFailed, refetch: retryLookups } = useLookups();
  const identity = useWorkspaceIdentity();
  const { team, teams, switchTeam, create, canCreate, isError: teamsFailed, retry: retryTeams } = useTeam();
  const role = useTeamRole();
  const badges: Record<string, number | undefined> = { '/reviews': openReviews };

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <TeamSwitcher
          error={teamsFailed}
          onRetry={() => void retryTeams()}
          teams={teams}
          activeTeam={team}
          subtitle={`${brand.name ?? identity?.workspace ?? 'Workspace'} · Ops AI`}
          onSelect={switchTeam}
          ownerGroups={lookups?.owners ?? []}
          onCreate={canCreate ? (input) => create.mutateAsync(input) : undefined}
          isCreating={create.isPending}
        />
      </SidebarHeader>
      <SidebarContent className="gap-0 [&>[data-sidebar=group]:not(:first-child)]:pt-1">
        {NAV.map((group, gi) => (
          <SidebarGroup key={gi}>
            {group.label && <SidebarGroupLabel>{group.label}</SidebarGroupLabel>}
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => {
                  const hit = navMatch(pathname);
                  const inSection = hit?.item.url === item.url;
                  // On a child page the child's own row is the active one; the parent only shows which section it is in.
                  const onParentPage = inSection && !hit?.child;
                  // A lone child reads as the section's only page, so the parent page gets its own sub-row beside it and the row that lights is always a sub-row.
                  // A page only an admin may read is not offered to anyone else.
                  const children = item.children?.filter((c) => !c.adminOnly || role === 'admin');
                  const parentSubRow = children?.length === 1;
                  const subRows = parentSubRow && children ? [{ title: item.tabTitle ?? item.title, url: item.url, icon: item.tabIcon }, ...children] : (children ?? []);
                  const active = onParentPage && !parentSubRow;
                  const count = badges[item.url];
                  const row = (
                    <SidebarMenuButton asChild tooltip={item.title} isActive={active}>
                      <Link href={item.url}>
                        <item.icon />
                        <span className="flex-1">{item.title}</span>
                        {isPreview(item.url) && <PreviewBadge className="ml-auto h-5 px-1.5 py-0 text-[10px] group-data-[collapsible=icon]:hidden" />}
                        {!!count && (
                          <Badge className="ml-auto h-5 px-1.5 py-0 text-[10px] tabular-nums" aria-label={`${count} open`}>
                            {count}
                          </Badge>
                        )}
                      </Link>
                    </SidebarMenuButton>
                  );
                  if (!item.children?.length) return <SidebarMenuItem key={item.url}>{row}</SidebarMenuItem>;
                  // The current page's section opens even if the viewer closed it, so the active row is always in view.
                  const open = !closed.has(item.url) || (inSection && (!!hit?.child || parentSubRow));
                  return (
                    <Collapsible key={item.url} asChild open={open} onOpenChange={(o) => toggleSection(item.url, o)}>
                      <SidebarMenuItem>
                        {row}
                        <CollapsibleTrigger asChild>
                          <SidebarMenuAction className="data-[state=open]:rotate-90" aria-label={`${open ? 'Hide' : 'Show'} ${item.title} pages`}>
                            <ChevronRight />
                          </SidebarMenuAction>
                        </CollapsibleTrigger>
                        <CollapsibleContent>
                          <SidebarMenuSub>
                            {subRows.map((child) => (
                              <SidebarMenuSubItem key={child.url}>
                                <SidebarMenuSubButton asChild isActive={child.url === item.url ? onParentPage : hit?.child?.url === child.url}>
                                  <Link href={child.url}>
                                    {child.icon && <child.icon />}
                                    <span>{child.title}</span>
                                  </Link>
                                </SidebarMenuSubButton>
                              </SidebarMenuSubItem>
                            ))}
                          </SidebarMenuSub>
                        </CollapsibleContent>
                      </SidebarMenuItem>
                    </Collapsible>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        {identity ? (
          <NavUser user={{ ...identity.user, avatar: '' }} />
        ) : lookupsFailed ? (
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" onClick={() => void retryLookups()} aria-label="Account unavailable. Try again">
                <AlertCircle className="size-4 text-destructive" />
                <div className="grid flex-1 text-left leading-tight">
                  <span className="truncate text-sm font-medium">Account unavailable</span>
                  <span className="truncate text-xs text-muted-foreground">Try again</span>
                </div>
                <RotateCw className="ml-auto size-4 text-muted-foreground" />
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        ) : null}
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
