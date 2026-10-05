'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { AlertCircle, RotateCw } from 'lucide-react';

import { NavUser } from '@/components/nav-user';
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
  SidebarRail,
} from '@/components/ui/sidebar';
import { useLookups, useOpenReviewCount } from '@/hooks/queries';
import { useTeam } from '@/hooks/use-team';
import { NAV, navMatch } from '@/lib/nav';

export function AppSidebar(props: React.ComponentProps<typeof Sidebar>) {
  const pathname = usePathname();
  const { data: openReviews } = useOpenReviewCount();
  const { data: lookups, isError: lookupsFailed, refetch: retryLookups } = useLookups();
  const { team, teams, switchTeam, create, isError: teamsFailed, retry: retryTeams } = useTeam();
  const badges: Record<string, number | undefined> = { '/reviews': openReviews };

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <TeamSwitcher
          error={teamsFailed}
          onRetry={() => void retryTeams()}
          teams={teams}
          activeTeam={team}
          subtitle={`${lookups?.workspace.name ?? 'Northfield Bank'} · Ops AI`}
          onSelect={switchTeam}
          ownerGroups={lookups?.owners ?? []}
          onCreate={(input) => create.mutateAsync(input)}
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
                  const active = navMatch(pathname)?.item.url === item.url;
                  const count = badges[item.url];
                  return (
                    <SidebarMenuItem key={item.url}>
                      <SidebarMenuButton asChild tooltip={item.title} isActive={active}>
                        <Link href={item.url}>
                          <item.icon />
                          <span className="flex-1">{item.title}</span>
                          {!!count && (
                            <Badge className="ml-auto h-5 px-1.5 py-0 text-[10px] tabular-nums" aria-label={`${count} open`}>
                              {count}
                            </Badge>
                          )}
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        {lookups ? (
          <NavUser user={{ ...lookups.currentUser, avatar: '' }} />
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
