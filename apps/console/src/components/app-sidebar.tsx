'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { AlertCircle, RotateCw, SquarePen } from 'lucide-react';

import { NavUser } from '@/components/nav-user';
import { SidebarChats } from '@/components/shell/sidebar-chats';
import { writeSidebarOpen } from '@/components/shell/sidebar-open';
import { sidebarFoldHeld } from '@/components/shared/collapsed-sidebar';
import { PreviewBadge } from '@/components/shared/preview-badge';
import { TeamSwitcher } from '@/components/team-switcher';
import { Badge } from '@/components/ui/badge';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarRail,
  useSidebar,
} from '@/components/ui/sidebar';
import { useFlag } from '@/hooks/flag-queries';
import { useNavAllows, useWorkspaceIdentity } from '@/hooks/me-queries';
import { useBrand, useLookups, useOverview } from '@/hooks/queries';
import { usePreviewCheck } from '@/hooks/use-preview';
import { useTeam } from '@/hooks/use-team';
import { type NavItem, childrenOffered, itemOffered, navMatch, rowsOfArea, sidebarSections } from '@/lib/nav';
import { useAreas } from '@/components/shared/area-switcher';
import { readOverview } from '@/lib/overview';


// Groups a viewer has opened or folded, kept in this browser only. Chats starts open, the rest folded.
const GROUPS_KEY = 'ops.sidebar.groups';
const OPEN_AT_FIRST: Record<string, boolean> = { Chats: true };

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

/** A sidebar section: a plain label over its links, always open (owner, 12 November: sections and links, no folding). */
function FoldingGroup({ label, children }: { label: string; open?: boolean; onOpenChange?: (open: boolean) => void; children: React.ReactNode }) {
  return (
    <SidebarGroup data-nav-group={label}>
      {/* Folded, the label fades and slides up over the previous section's last icon; without this it takes that
          icon's clicks. */}
      <SidebarGroupLabel className="group-data-[collapsible=icon]:pointer-events-none">{label}</SidebarGroupLabel>
      <SidebarGroupContent>{children}</SidebarGroupContent>
    </SidebarGroup>
  );
}

export function AppSidebar(props: React.ComponentProps<typeof Sidebar>) {
  const pathname = usePathname();
  const isPreview = usePreviewCheck();
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
  const allows = useNavAllows();
  const { current: area, ready: cellsReady, failed: cellsFailed, retry: retryCells } = useAreas();
  // Area tabs on: the sidebar lists the area picked in the top bar. Off (the default): every area as a section.
  const areaTabs = useFlag('area_tabs');
  const chats = allows({ area: 'chat', action: 'run' }) === true;
  const sections = sidebarSections(allows);
  const badges: Record<string, number | undefined> = { '/work/tasks': waiting };

  // One console page as a sidebar row, with its child pages as sub-rows under a fold.
  const navRow = (item: NavItem) => {
    const hit = navMatch(pathname);
    const inSection = hit?.item.url === item.url;
    // On a child page the child's own row is the active one; the parent only shows which section it is in.
    const onParentPage = inSection && !hit?.child;
    // A lone child reads as the section's only page, so the parent page gets its own sub-row beside it and the row that lights is always a sub-row.
    // A page the person's roles do not open is not offered (lib/nav.ts `needs`).
    const children = childrenOffered(allows, item);
    if (!itemOffered(allows, item)) return null;
    const parentSubRow = children?.length === 1;
    const subRows = parentSubRow && children ? [{ title: item.tabTitle ?? item.title, url: item.url, icon: item.tabIcon }, ...children] : (children ?? []);
    const active = onParentPage && !parentSubRow;
    const count = badges[item.url];
    const row = (
      <SidebarMenuButton asChild tooltip={item.title} isActive={active}>
        <Link href={item.url} onClick={closeOnPhone} data-testid={item.url === '/' ? 'sidebar-overview' : undefined}>
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
    // Owner, 12 November: sections and links, no folding. A row with pages under it always lists them.
    return (
      <SidebarMenuItem key={item.url}>
        {row}
        <SidebarMenuSub>
          {subRows.map((child) => (
            <SidebarMenuSubItem key={child.url}>
              {/* A long name ("Model inventory") wraps to a second line rather than being cut at the sidebar's width. */}
              <SidebarMenuSubButton asChild isActive={child.url === item.url ? onParentPage : hit?.child?.url === child.url} className="h-auto min-h-7 py-1 [&>span:last-child]:whitespace-normal! [&>span:last-child]:leading-snug">
                <Link href={child.url} onClick={closeOnPhone}>
                  {child.icon && <child.icon />}
                  <span>{child.title}</span>
                </Link>
              </SidebarMenuSubButton>
            </SidebarMenuSubItem>
          ))}
        </SidebarMenuSub>
      </SidebarMenuItem>
    );
  };

  const chatsGroup = (
    <div className="group-data-[collapsible=icon]:hidden">
      <FoldingGroup label="Chats" open={groupOpen('Chats')} onOpenChange={(o) => setGroupOpen('Chats', o)}>
        <SidebarChats onNavigate={closeOnPhone} />
      </FoldingGroup>
    </div>
  );

  // Chat as one link (its child page, All chats, is reached from the chat pages' column).
  const chatItem = navMatch('/chat')?.item;
  const chatRow = chatItem ? navRow({ ...chatItem, children: undefined }) : null;

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <TeamSwitcher
          error={teamsFailed}
          onRetry={() => void retryTeams()}
          teams={teams}
          activeTeam={team}
          subtitle={[brand.name ?? identity?.workspace, 'Ops AI'].filter(Boolean).join(' · ')}
          onSelect={switchTeam}
          ownerGroups={lookups?.owners ?? []}
          onCreate={canCreate ? (input) => create.mutateAsync(input) : undefined}
          isCreating={create.isPending}
        />
        <SidebarMenu>
          {/* New chat leads the sidebar; with area tabs on, only in Work, as every other area is its rows alone. */}
          {(!areaTabs || area === 'Work') && cellsReady && chats && (
            <SidebarMenuItem>
              <SidebarMenuButton asChild tooltip="New chat" isActive={pathname === '/chat'}>
                <Link href="/chat" onClick={closeOnPhone} data-testid="sidebar-new-chat">
                  <SquarePen />
                  <span>New chat</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          )}
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent className="gap-0 [&>[data-sidebar=group]:not(:first-child)]:pt-1">
        {!cellsReady ? (
          cellsFailed ? (
            <SidebarMenu className="px-2 pt-2">
              <SidebarMenuItem>
                <SidebarMenuButton onClick={retryCells} className="text-muted-foreground" aria-label="Pages unavailable. Try again">
                  <RotateCw />
                  <span className="flex flex-col leading-tight">
                    <span>Pages unavailable</span>
                    <span className="text-xs">Try again</span>
                  </span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          ) : (
            <SidebarMenu className="px-2 pt-2" data-testid="sidebar-cells-loading">
              {Array.from({ length: 5 }, (_, i) => (
                <SidebarMenuItem key={i}>
                  <SidebarMenuSkeleton showIcon />
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          )
        ) : (
          areaTabs ? (
            <>
              <SidebarGroup className="pb-0">
                <SidebarGroupContent>
                  <SidebarMenu>{rowsOfArea(area, allows).map(navRow)}</SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
              {area === 'Work' && chats && chatsGroup}
            </>
          ) : (
            // Each area as its own section, one link per page. Chat is a link in Work: its list of chats is a column on
            // the chat pages. A person with no Work page (chat only) still gets a Work section holding Chat.
            <>
              {chats && !sections.some((s) => s.label === 'Work') && (
                <FoldingGroup label="Work">
                  <SidebarMenu>{chatRow}</SidebarMenu>
                </FoldingGroup>
              )}
              {sections.map((section) => (
                <FoldingGroup key={section.label} label={section.label}>
                  <SidebarMenu>
                    {section.items.map(navRow)}
                    {section.label === 'Work' && chats && chatRow}
                  </SidebarMenu>
                </FoldingGroup>
              ))}
            </>
          )
        )}
      </SidebarContent>
      <SidebarFooter>
        {identity ? (
          <NavUser user={{ ...identity.user, avatar: '' }} />
        ) : lookupsFailed ? (
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" onClick={() => void retryLookups()} aria-label="Account unavailable. Try again">
                <AlertCircle className="size-4 text-destructive-text" />
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
