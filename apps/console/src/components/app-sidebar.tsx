'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { AlertCircle, ChevronRight, LayoutGrid, RotateCw, SquarePen } from 'lucide-react';

import { NavUser } from '@/components/nav-user';
import { SidebarChats } from '@/components/shell/sidebar-chats';
import { writeSidebarOpen } from '@/components/shell/sidebar-open';
import { sidebarFoldHeld } from '@/components/shared/collapsed-sidebar';
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
  useSidebar,
} from '@/components/ui/sidebar';
import { useTeamRole, useWorkspaceIdentity } from '@/hooks/me-queries';
import { useBrand, useLookups, useOverview } from '@/hooks/queries';
import { usePreviewCheck } from '@/hooks/use-preview';
import { useTeam } from '@/hooks/use-team';
import { NAV, navMatch } from '@/lib/nav';
import { readOverview } from '@/lib/overview';

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

// Groups a viewer has opened or folded, kept in this browser only (c-552). Chats starts open, the rest folded.
const GROUPS_KEY = 'ops.sidebar.groups';
const OPEN_AT_FIRST: Record<string, boolean> = { Chats: true };
// The console's first group (Work) has no heading: its pages are rows at the top of the sidebar.
const TOP_GROUP = NAV[0];

function useGroupFolds(): [(label: string) => boolean, (label: string, open: boolean) => void] {
  const [saved, setSaved] = React.useState<Record<string, boolean>>({});
  React.useEffect(() => {
    try {
      const read = JSON.parse(window.localStorage.getItem(GROUPS_KEY) ?? '{}');
      if (read && typeof read === 'object' && !Array.isArray(read)) setSaved(Object.fromEntries(Object.entries(read).filter(([, v]) => typeof v === 'boolean')) as Record<string, boolean>);
    } catch {
      // No storage, or a value this version cannot read: the groups open as they start.
    }
  }, []);
  const isOpen = React.useCallback((label: string) => saved[label] ?? !!OPEN_AT_FIRST[label], [saved]);
  const set = React.useCallback((label: string, open: boolean) => {
    setSaved((prev) => {
      const next = { ...prev, [label]: open };
      try {
        window.localStorage.setItem(GROUPS_KEY, JSON.stringify(next));
      } catch {
        // Not remembered; the change still applies on this page.
      }
      return next;
    });
  }, []);
  return [isOpen, set];
}

/** A sidebar group whose label folds it. Folded to icons, every group shows its rows as icons. */
function FoldingGroup({ label, open, onOpenChange, children }: { label: string; open: boolean; onOpenChange: (open: boolean) => void; children: React.ReactNode }) {
  const { state } = useSidebar();
  const shown = state === 'collapsed' || open;
  return (
    <Collapsible open={shown} onOpenChange={onOpenChange} asChild>
      <SidebarGroup data-nav-group={label}>
        <SidebarGroupLabel asChild>
          {/* Folded to icons the label slides up over the row above it, invisible; it must not take that row's clicks. */}
          <CollapsibleTrigger className="w-full justify-between group-data-[collapsible=icon]:pointer-events-none" aria-expanded={shown}>
            {label}
            <ChevronRight className={`size-3.5 transition-transform ${shown ? 'rotate-90' : ''}`} />
          </CollapsibleTrigger>
        </SidebarGroupLabel>
        <CollapsibleContent>
          <SidebarGroupContent>{children}</SidebarGroupContent>
        </CollapsibleContent>
      </SidebarGroup>
    </Collapsible>
  );
}

export function AppSidebar(props: React.ComponentProps<typeof Sidebar>) {
  const pathname = usePathname();
  const isPreview = usePreviewCheck();
  const [closed, toggleSection] = useClosedSections();
  const brand = useBrand();
  // One count in the sidebar: Human Tasks waiting for you, the same number as Assigned to me and Overview's first widget.
  const overview = useOverview().data;
  const waiting = readOverview(overview).counts.waitingForMe;
  const [groupOpen, setGroupOpen] = useGroupFolds();
  const { isMobile, setOpenMobile, open } = useSidebar();
  React.useEffect(() => {
    if (!isMobile && !sidebarFoldHeld()) writeSidebarOpen(open);
  }, [open, isMobile]);
  const closeOnPhone = () => isMobile && setOpenMobile(false);
  const { data: lookups, isError: lookupsFailed, refetch: retryLookups } = useLookups();
  const identity = useWorkspaceIdentity();
  const { team, teams, switchTeam, create, canCreate, isError: teamsFailed, retry: retryTeams } = useTeam();
  const role = useTeamRole();
  const badges: Record<string, number | undefined> = { '/reviews': waiting };

  // One console page as a sidebar row, with its child pages as sub-rows under a fold.
  const navRow = (item: (typeof NAV)[number]['items'][number]) => {
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
        <Link href={item.url} onClick={closeOnPhone}>
          <item.icon />
          <span className="flex-1">{item.title}</span>
          {isPreview(item.url) && <PreviewBadge className="ml-auto h-5 px-1.5 py-0 text-[10px] group-data-[collapsible=icon]:hidden" />}
          {!!count && (
            <Badge className="ml-auto h-5 px-1.5 py-0 text-[10px] tabular-nums" aria-label={`${count} waiting for you`} data-testid={`sidebar-count${item.url.replaceAll('/', '-')}`}>
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
                    <Link href={child.url} onClick={closeOnPhone}>
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
  };

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
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild tooltip="New chat" isActive={pathname === '/chat'}>
              <Link href="/chat" onClick={closeOnPhone} data-testid="sidebar-new-chat">
                <SquarePen />
                <span>New chat</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton asChild tooltip="Overview" isActive={pathname === '/'}>
              <Link href="/" onClick={closeOnPhone} data-testid="sidebar-overview">
                <LayoutGrid />
                <span className="flex-1">Overview</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          {/* The first group's pages (Cases, Human Tasks) sit with New chat and Overview, under no heading (owner, 2026-10-28). */}
          {TOP_GROUP.items.filter((item) => !item.top).map(navRow)}
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent className="gap-0 [&>[data-sidebar=group]:not(:first-child)]:pt-1">
        <div className="group-data-[collapsible=icon]:hidden">
          <FoldingGroup label="Chats" open={groupOpen('Chats')} onOpenChange={(o) => setGroupOpen('Chats', o)}>
            <SidebarChats onNavigate={closeOnPhone} />
          </FoldingGroup>
        </div>
        {NAV.filter((group) => group !== TOP_GROUP).map((group) => {
          const items = group.items.filter((item) => !item.top);
          if (!items.length) return null;
          // The current page's group opens even if the viewer folded it, so the active row is always in view.
          const here = navMatch(pathname)?.group.label === group.label && !navMatch(pathname)?.item.top;
          return (
            <FoldingGroup key={group.label} label={group.label} open={groupOpen(group.label) || here} onOpenChange={(o) => setGroupOpen(group.label, o)}>
              <SidebarMenu>
                {items.map(navRow)}
              </SidebarMenu>
            </FoldingGroup>
          );
        })}
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
